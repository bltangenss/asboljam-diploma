"""Dated recipe decisions on isolated SQLite or explicitly opted-in PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from apps.api import migrations
from apps.api.db import (Audit, Base, Organization, OrganizationSource, RecipeActivation, RecipeCommandReceipt,
                         Record, StockLedger, StockMovement, User, make_engine, migrate, sessions)
from apps.api.importing import insert_rows
from apps.api.stock import StockError, fingerprint, recipe_requirements
from apps.api.stock_recipes import activate_recipe, list_activations, preview_activation, resolve_recipes
from database_fixture import isolated_database_url
import test_stock_migration as prior_fixture


class RecipeActivationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='recipe-activation-')
        self.addCleanup(self.temp.cleanup)
        self.engine = make_engine(isolated_database_url('sqlite:///' + (Path(self.temp.name) / 'fixture.sqlite').as_posix()))
        self.addCleanup(self.engine.dispose)
        migrate(self.engine)
        self.sessions = sessions(self.engine)
        with self.sessions.begin() as db:
            for org in ('A', 'B'):
                db.add(Organization(id=org, name='Generated fixture', timezone='Asia/Qyzylorda', currency='KZT',
                                    status='active', data_policy='synthetic_only', provenance='test_fixture'))
                for role in ('admin', 'manager', 'warehouse', 'analyst'):
                    db.add(User(id=org + role, organization_id=org, email=org + role + '@fixture.invalid',
                                password_hash='not-a-login-password', role=role, branch_ids=['001'], active=True))
                insert_rows(db, org, 'branches', [dict(branch_id='001', branch_name='Generated branch', data_origin='SYNTHETIC')])
                insert_rows(db, org, 'meals', [dict(meal_id=meal, meal_name='Generated meal', base_price_kzt='1000',
                    data_origin='SYNTHETIC') for meal in ('01', '02')])
                insert_rows(db, org, 'ingredients', [dict(ingredient_id='0007', ingredient_name='Generated rice',
                    unit='kg', reference_cost_kzt='400.50', shelf_life_days=5, yield_factor='0.5', storage_capacity='100',
                    data_origin='SYNTHETIC')])
                insert_rows(db, org, 'recipes', [dict(meal_id='01', ingredient_id='0007', net_qty_per_portion='0.1',
                    recipe_version='legacy CSV', data_origin='SYNTHETIC')])

    def payload(self, **changes):
        return dict(branch_id='001', meal_id='01', recipe_version='v1.0 тест', effective_date='2026-01-01',
                    rows=[dict(ingredient_id='0007', net_qty_per_portion='0.25')], expected_version=0,
                    reason='Explicit complete generated recipe') | changes

    def preview(self, payload=None, actor='Amanager'):
        with self.sessions.begin() as db:
            return preview_activation(db, db.get(User, actor), **(payload or self.payload()))

    def activate(self, payload=None, actor='Amanager', key='fixture-key', preview=None):
        values = payload or self.payload()
        preview = preview or self.preview(values, actor)
        with self.sessions.begin() as db:
            return activate_recipe(db, db.get(User, actor), **values,
                expected_fingerprint=preview['preview_fingerprint'], idempotency_key=key)

    def expect_code(self, code, callback):
        with self.assertRaises(StockError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def resolve(self, date='2026-01-01', meals=('01',), org='A'):
        with self.sessions() as db:
            return resolve_recipes(db, org, '001', date, meals)

    def change_ingredient(self, **changes):
        with self.sessions.begin() as db:
            row = db.scalar(select(Record).where(Record.organization_id == 'A', Record.kind == 'ingredients'))
            row.data = row.data | changes

    def test_csv_is_not_autoactivated_and_preview_does_not_create_decision(self):
        self.expect_code('STOCK_RECIPE_NOT_ACTIVE', self.resolve)
        preview = self.preview()
        self.assertEqual((preview['version'], preview['next_version']), (0, 1))
        self.assertEqual(preview['rows'][0]['captured_yield_factor'], '0.5')
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(RecipeActivation)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(Audit)), 0)
            self.assertEqual(list_activations(db, db.get(User, 'Aanalyst'), '001')['items'], [])

    def test_complete_activation_resolves_dates_and_does_not_mix_previous_rows(self):
        first = self.activate()
        second = self.activate(self.payload(recipe_version='v2 / полный рецепт', effective_date='2026-01-03',
            expected_version=1, rows=[dict(ingredient_id='0007', net_qty_per_portion='0.1')]), key='second')
        self.expect_code('STOCK_RECIPE_NOT_ACTIVE', lambda: self.resolve('2025-12-31'))
        for date, activation in [('2026-01-01', first), ('2026-01-02', first), ('2026-01-03', second)]:
            with self.subTest(date=date):
                result = self.resolve(date)
                self.assertEqual(len(result['recipes']), 1)
                self.assertEqual(result['recipes'][0]['activation_id'], activation['id'])
                self.assertEqual(result['recipes'][0]['net_qty_per_portion'], activation['rows'][0]['net_qty_per_portion'])
                self.assertEqual(result['fingerprint'], fingerprint(result['evidence']))
        self.expect_code('STOCK_RECIPE_NOT_ACTIVE', lambda: self.resolve(meals=('01', '02')))
        with self.sessions() as db:
            legacy = db.scalar(select(Record).where(Record.organization_id == 'A', Record.kind == 'recipes'))
            self.assertEqual(legacy.data['recipe_version'], 'legacy CSV')

    def test_captured_yield_is_per_meal_and_used_once_despite_later_catalog_change(self):
        self.activate()
        self.change_ingredient(yield_factor='0.8')
        self.activate(self.payload(meal_id='02'), key='second-meal')
        resolved = self.resolve(meals=('01', '02'))
        self.assertEqual([row['captured_yield_factor'] for row in resolved['recipes']], ['0.5', '0.8'])
        required, evidence = recipe_requirements(resolved['recipes'], resolved['ingredients'], {'01': 10, '02': 10}, resolved['versions'])
        self.assertEqual(required, [{'ingredient_id': '0007', 'unit': 'kg', 'gross_required': '8.125'}])
        self.assertEqual([row['yield_factor'] for row in evidence['rows']], ['0.5', '0.8'])
        self.change_ingredient(unit='L')
        self.expect_code('STOCK_UNIT_MISMATCH', lambda: self.resolve(meals=('01', '02')))

    def test_receipt_replay_is_exact_after_later_activation_and_payload_conflict_rejected(self):
        values, preview = self.payload(), self.preview()
        original = self.activate(values, preview=preview)
        self.activate(self.payload(recipe_version='v2', effective_date='2026-01-02', expected_version=1), key='v2')
        self.assertEqual(self.activate(values, preview=preview), original)
        self.expect_code('STOCK_IDEMPOTENCY_CONFLICT', lambda: self.activate(values | {'reason': 'Changed reason'}, preview=preview))
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(RecipeActivation)), 2)
            self.assertEqual(db.scalar(select(func.count()).select_from(RecipeCommandReceipt)), 2)
            self.assertEqual(db.scalar(select(func.count()).select_from(Audit)), 2)

    def test_preview_fences_catalog_changes_and_stale_version(self):
        preview = self.preview()
        self.change_ingredient(yield_factor='0.75')
        self.expect_code('STOCK_PREVIEW_STALE', lambda: self.activate(preview=preview))
        self.activate()
        self.expect_code('STOCK_VERSION_CONFLICT', self.preview)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(RecipeActivation)), 1)

    def test_access_is_current_on_preview_post_read_and_idempotent_replay(self):
        for actor in ('Awarehouse', 'Aanalyst'):
            self.expect_code('STOCK_FORBIDDEN', lambda: self.preview(actor=actor))
        preview = self.preview()
        self.activate(preview=preview)
        with self.sessions.begin() as db:
            db.get(User, 'Amanager').branch_ids = []
        self.expect_code('STOCK_FORBIDDEN', lambda: self.activate(preview=preview))
        with self.sessions() as db:
            self.expect_code('STOCK_FORBIDDEN', lambda: list_activations(db, db.get(User, 'Amanager'), '001'))
            self.assertEqual(list_activations(db, db.get(User, 'Bmanager'), '001')['total'], 0)
        self.expect_code('STOCK_RECIPE_NOT_ACTIVE', lambda: self.resolve(org='B'))
        with self.sessions.begin() as db:
            db.get(Organization, 'A').status = 'suspended'
        self.expect_code('STOCK_ACCESS_REVOKED', lambda: self.preview(actor='Aadmin'))

    def test_stale_actor_cannot_switch_organization_during_identity_refresh(self):
        with self.sessions() as db:
            user = db.get(User, 'Amanager')
            self.assertEqual(user.organization_id, 'A')
            with self.sessions.begin() as other:
                other.get(User, 'Amanager').organization_id = 'B'
            self.expect_code('STOCK_ACCESS_REVOKED', lambda: list_activations(db, user, '001'))

    def test_reversed_usage_still_prevents_retroactive_recipe_rewrite(self):
        self.activate()
        with self.sessions.begin() as db:
            db.add(StockLedger(id='ledger', organization_id='A', branch_id='001', baseline_date='2026-01-01',
                baseline_rows=[], baseline_lineage={}, data_context={}, created_by='Amanager'))
            db.flush()
            for sequence, kind, business_date in [(1, 'recipe_usage', '2026-01-04'), (2, 'reversal', '2026-01-05')]:
                db.add(StockMovement(id=kind, ledger_id='ledger', organization_id='A', branch_id='001', sequence=sequence,
                    kind=kind, business_date=business_date, reason='Generated fixture', source_reference=kind,
                    entries=[], reverses_id='recipe_usage' if kind == 'reversal' else None, actor_id='Amanager'))
        self.expect_code('STOCK_RECIPE_HISTORY_CLOSED', lambda: self.preview(self.payload(
            recipe_version='v2', expected_version=1, effective_date='2026-01-04')))
        self.activate(self.payload(recipe_version='v2', expected_version=1, effective_date='2026-01-05'), key='after-usage')

    def test_invalid_rows_numbers_labels_and_reused_versions_are_atomic(self):
        cases = [({'rows': []}, 'STOCK_RECIPE_REQUIRED'),
            ({'rows': [dict(ingredient_id='0007', net_qty_per_portion='0')]}, 'STOCK_QUANTITY_INVALID'),
            ({'rows': [dict(ingredient_id='0007', net_qty_per_portion=0.2)]}, 'STOCK_QUANTITY_INVALID'),
            ({'rows': [dict(ingredient_id='0007', net_qty_per_portion='0.2', captured_yield_factor='1')]}, 'STOCK_RECIPE_ROWS_INVALID'),
            ({'rows': self.payload()['rows'] * 2}, 'STOCK_RECIPE_AMBIGUOUS'),
            ({'rows': [dict(ingredient_id='missing', net_qty_per_portion='0.2')]}, 'STOCK_INGREDIENT_UNKNOWN'),
            ({'recipe_version': 'x' * 256}, 'STOCK_RECIPE_VERSION_INVALID'),
            ({'expected_version': True}, 'STOCK_VERSION_INVALID'), ({'reason': ' '}, 'STOCK_REASON_REQUIRED')]
        for changes, code in cases:
            with self.subTest(changes=changes):
                self.expect_code(code, lambda: self.preview(self.payload(**changes)))
        self.activate()
        self.expect_code('STOCK_RECIPE_VERSION_EXISTS', lambda: self.preview(self.payload(expected_version=1, effective_date='2026-01-02')))
        self.expect_code('STOCK_RECIPE_DATE_ORDER', lambda: self.preview(self.payload(expected_version=1, recipe_version='v2')))

    def test_error_after_activation_insert_rolls_back_decision_receipt_and_audit(self):
        preview = self.preview()
        with patch('apps.api.stock_recipes.Audit', side_effect=RuntimeError('Controlled audit failure')):
            with self.assertRaises(RuntimeError):
                self.activate(preview=preview)
        with self.sessions() as db:
            for model in (RecipeActivation, RecipeCommandReceipt, Audit):
                self.assertEqual(db.scalar(select(func.count()).select_from(model)), 0)
        self.activate(preview=preview)

    def test_concurrent_same_receipt_posts_once_and_conflicting_versions_have_one_winner(self):
        preview = self.preview()
        barrier = threading.Barrier(2)
        def repeat(_):
            barrier.wait(timeout=10)
            return self.activate(preview=preview)
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(repeat, range(2)))
        self.assertEqual(outcomes[0], outcomes[1])
        payload = self.payload(expected_version=1, recipe_version='v2', effective_date='2026-01-02')
        preview2 = self.preview(payload)
        barrier = threading.Barrier(2)
        def conflict(index):
            barrier.wait(timeout=10)
            try:
                self.activate(payload, key='contender-' + str(index), preview=preview2)
                return 'success'
            except StockError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(conflict, range(2)))
        self.assertCountEqual(outcomes, ['success', 'STOCK_VERSION_CONFLICT'])
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Audit)), 2)

    def test_real_test_source_preserved_and_context_change_does_not_relabel_evidence(self):
        with self.sessions.begin() as db:
            db.get(Organization, 'A').data_policy = 'real_only'
            db.add(OrganizationSource(organization_id='A', source_id='generated-source', mapping_version='v1',
                branch_id='001', authorization_reference='generated-test-only', purpose='test_fixture', actor_id='operator'))
            for row in db.scalars(select(Record).where(Record.organization_id == 'A')):
                row.data = row.data | {'data_origin': 'REAL'}
        result = self.activate()
        self.assertEqual(result['data_context']['usage_mode'], 'TEST')
        self.assertNotIn('authorization_reference', result['data_context']['source'])
        resolved = self.resolve()
        self.assertEqual(resolved['recipes'][0]['data_origin'], 'REAL')
        with self.sessions.begin() as db:
            db.get(OrganizationSource, 'A').mapping_version = 'changed-after-activation'
        self.expect_code('STOCK_RECIPE_CONTEXT_CHANGED', self.resolve)
        with self.sessions() as db:
            stored = db.get(RecipeActivation, result['id'])
            self.assertEqual(stored.data_context['source']['mapping_version'], 'v1')


class RecipeMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='recipe-migration-')
        self.addCleanup(self.temp.cleanup)
        self.engine = make_engine(isolated_database_url('sqlite:///' + (Path(self.temp.name) / 'fixture.sqlite').as_posix()))
        self.addCleanup(self.engine.dispose)

    def versions(self):
        with self.engine.connect() as db:
            return tuple(db.execute(text('SELECT version FROM schema_migrations ORDER BY version')).scalars())

    def prepare(self):
        prior_fixture.StockMigrationTests.prepare_v5(self)
        with self.engine.begin() as db:
            migrations._stock_journal_schema(db)
            db.execute(text("INSERT INTO schema_migrations VALUES ('0006')"))
            db.execute(StockLedger.__table__.insert(), prior_fixture.StockMigrationTests.ledger_values(self))
            db.execute(StockMovement.__table__.insert(), prior_fixture.StockMigrationTests.movement_values(self))

    def snapshot(self):
        with self.engine.connect() as db:
            return {name: [dict(row) for row in db.execute(select(table).order_by(*table.primary_key.columns)).mappings()]
                    for name, table in Base.metadata.tables.items()
                    if name not in migrations.RECIPE_TABLE_NAMES + migrations.COUNT_ANCHOR_TABLE_NAMES + migrations.PRODUCTION_TABLE_NAMES + migrations.PROFILE_TABLE_NAMES + migrations.CLOSURE_TABLE_NAMES}

    def test_upgrade_preserves_prior_rows_and_creates_no_implicit_recipe_versions(self):
        self.prepare()
        before = self.snapshot()
        self.assertEqual(migrate(self.engine), migrations.VERSIONS[6:])
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.versions(), migrations.VERSIONS)
        self.assertEqual(migrate(self.engine), ())
        with self.engine.connect() as db:
            for name in migrations.RECIPE_TABLE_NAMES:
                self.assertEqual(list(db.execute(select(Base.metadata.tables[name]))), [])

    def test_failed_upgrade_rolls_back_tables_and_marker(self):
        self.prepare()
        before = self.snapshot()
        def fail(db):
            RecipeActivation.__table__.create(db)
            raise RuntimeError('Controlled recipe migration interruption')
        with patch.object(migrations, '_dated_recipes_schema', side_effect=fail):
            with self.assertRaises(RuntimeError):
                migrate(self.engine)
        self.assertEqual(self.versions(), migrations.VERSIONS[:6])
        self.assertTrue(set(migrations.RECIPE_TABLE_NAMES).isdisjoint(inspect(self.engine).get_table_names()))
        self.assertEqual(before, self.snapshot())
        self.assertEqual(migrate(self.engine), migrations.VERSIONS[6:])

    def test_fresh_failure_rolls_back_even_initial_schema(self):
        with patch.object(migrations, '_dated_recipes_schema', side_effect=RuntimeError('Controlled failure')):
            with self.assertRaises(RuntimeError):
                migrate(self.engine)
        self.assertEqual(inspect(self.engine).get_table_names(), [])
        self.assertEqual(migrate(self.engine), migrations.VERSIONS)

    def test_concurrent_migration_creates_recipe_tables_once(self):
        self.prepare()
        before = self.snapshot()
        with ThreadPoolExecutor(max_workers=3) as pool:
            outcomes = list(pool.map(lambda _: migrate(self.engine), range(3)))
        self.assertCountEqual(outcomes, [migrations.VERSIONS[6:], (), ()])
        self.assertEqual(before, self.snapshot())

    def test_unknown_existing_table_is_preserved_and_not_stamped(self):
        self.prepare()
        with self.engine.begin() as db:
            db.execute(text('CREATE TABLE recipe_command_receipts (sentinel TEXT)'))
            db.execute(text("INSERT INTO recipe_command_receipts VALUES ('preserve-me')"))
        with self.assertRaises(SQLAlchemyError):
            migrate(self.engine)
        self.assertNotIn('recipe_activations', inspect(self.engine).get_table_names())
        self.assertEqual(self.versions(), migrations.VERSIONS[:6])
        with self.engine.connect() as db:
            self.assertEqual(db.execute(text('SELECT sentinel FROM recipe_command_receipts')).scalar_one(), 'preserve-me')

    def test_database_constraints_enforce_per_meal_dates_labels_sequence_and_receipts(self):
        migrate(self.engine)
        values = dict(id='activation', organization_id='A', branch_id='001', meal_id='01', sequence=1,
            recipe_version='v1.0 test', effective_date='2026-01-01', rows=[{'net_qty_per_portion': '0.125000000'}],
            snapshot_sha256='a' * 64, data_context={'data_origin': 'SYNTHETIC'}, reason='Generated test', actor_id='manager')
        with self.engine.begin() as db:
            db.execute(RecipeActivation.__table__.insert(), values)
            db.execute(RecipeActivation.__table__.insert(), values | {'id': 'other-org', 'organization_id': 'B'})
            db.execute(RecipeActivation.__table__.insert(), values | {'id': 'other-meal', 'meal_id': '02'})
        for changes in ({'sequence': 0}, {'sequence': 1}, {'effective_date': '2026-01-01'}, {'recipe_version': 'v1.0 test'}):
            attempted = values | {'id': 'bad', 'sequence': 2, 'effective_date': '2026-01-02', 'recipe_version': 'v2'} | changes
            with self.subTest(changes=changes), self.assertRaises(IntegrityError):
                with self.engine.begin() as db:
                    db.execute(RecipeActivation.__table__.insert(), attempted)
        receipt = dict(id='receipt', organization_id='A', actor_id='manager', key='key', payload_hash='b' * 64,
                       activation_id='activation', response={'version': 1})
        with self.engine.begin() as db:
            db.execute(RecipeCommandReceipt.__table__.insert(), receipt)
        for changes in ({'id': 'duplicate'}, {'id': 'missing-parent', 'key': 'other', 'activation_id': 'missing'}):
            with self.subTest(changes=changes), self.assertRaises(IntegrityError):
                with self.engine.begin() as db:
                    db.execute(RecipeCommandReceipt.__table__.insert(), receipt | changes)


if __name__ == '__main__':
    unittest.main()
