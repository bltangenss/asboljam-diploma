"""Migration 0003 preserves old rows and adds scoped import evidence atomically.

Every case uses actual SQLite or the explicitly opted-in PostgreSQL fixture.
No source hashes, revisions or commit times are invented for existing imports.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from apps.api.db import Base, Idempotency, ImportBatch, ImportEvidence, ImportReceipt, RecordRevision, make_engine, migrate
from apps.api.migrations import IMPORT_TABLE_NAMES, LEGACY_TABLE_NAMES, SOURCE_TABLE_NAMES, STOCK_TABLE_NAMES, RECIPE_TABLE_NAMES, COUNT_ANCHOR_TABLE_NAMES, VERSIONS, _tenant_schema
from database_fixture import isolated_database_url
import test_tenant_migration as legacy_fixture


class ImportMigrationTests(unittest.TestCase):
    def setUp(self):
        Path('.cache').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='import-migration-', dir='.cache')
        self.addCleanup(self.temp.cleanup)
        self.engine = make_engine(isolated_database_url(
            'sqlite:///' + (Path(self.temp.name).resolve() / 'migration.sqlite').as_posix()))
        self.addCleanup(self.engine.dispose)

    def versions(self):
        with self.engine.connect() as connection:
            return list(connection.execute(text('SELECT version FROM schema_migrations ORDER BY version')).scalars())

    def prepare_v2(self):
        # Reuse the populated original-table fixture, not the latest migration entrypoint.
        legacy_fixture.TenantMigrationTests.legacy_schema(self)
        with self.engine.begin() as connection:
            _tenant_schema(connection)
            connection.execute(text("INSERT INTO schema_migrations (version) VALUES ('0002')"))
        self.assertEqual(self.versions(), ['0001', '0002'])
        self.assertTrue(set(IMPORT_TABLE_NAMES).isdisjoint(inspect(self.engine).get_table_names()))

    def old_snapshot(self):
        with self.engine.connect() as connection:
            return {name: [dict(row._mapping) for row in connection.execute(
                select(*[c for c in Base.metadata.tables[name].columns
                        if not (name == "jobs" and c.name == "heartbeat_at")]).order_by(*Base.metadata.tables[name].primary_key.columns))]
                for name in (*LEGACY_TABLE_NAMES, 'organizations')}

    def assert_empty_evidence(self):
        with self.engine.connect() as connection:
            for name in IMPORT_TABLE_NAMES:
                self.assertEqual(list(connection.execute(select(Base.metadata.tables[name]))), [], name)

    def test_fresh_database_creates_sidecars_only_in_version_0003(self):
        self.assertTrue(set(IMPORT_TABLE_NAMES).isdisjoint(LEGACY_TABLE_NAMES))
        self.assertEqual(migrate(self.engine), VERSIONS)
        self.assertEqual(self.versions(), list(VERSIONS))
        self.assertEqual(set(inspect(self.engine).get_table_names()),
                         set(LEGACY_TABLE_NAMES) | set(IMPORT_TABLE_NAMES) | set(SOURCE_TABLE_NAMES) | set(STOCK_TABLE_NAMES) | set(RECIPE_TABLE_NAMES) | set(COUNT_ANCHOR_TABLE_NAMES) | {'organizations', 'schema_migrations'})
        self.assert_empty_evidence()

    def test_populated_v2_upgrade_preserves_every_original_row_and_fabricates_nothing(self):
        self.prepare_v2()
        before = self.old_snapshot()
        self.assertTrue(all(before.values()))
        self.assertEqual(migrate(self.engine), VERSIONS[2:])
        self.assertEqual(self.old_snapshot(), before)
        self.assertEqual(self.versions(), list(VERSIONS))
        self.assert_empty_evidence()

    def test_repeat_does_not_backfill_later_legacy_style_batches(self):
        self.prepare_v2()
        migrate(self.engine)
        with self.engine.begin() as connection:
            connection.execute(ImportBatch.__table__.insert(), dict(id='later', organization_id='demo',
                actor_id='demo-user', kind='daily_sales', rows=[], errors=[], status='committed'))
        before = self.old_snapshot()
        self.assertEqual(migrate(self.engine), ())
        self.assertEqual(self.old_snapshot(), before)
        self.assert_empty_evidence()

    def partial_failure(self, connection):
        ImportEvidence.__table__.create(connection)
        connection.execute(ImportEvidence.__table__.insert(), dict(batch_id='partial', organization_id='demo',
            actor_id='demo-user', kind='daily_sales', source={}, summary={}, expected_state={}))
        RecordRevision.__table__.create(connection)
        raise RuntimeError('Simulated interrupted import schema migration')

    def test_failed_v2_upgrade_rolls_back_new_tables_rows_and_marker(self):
        self.prepare_v2()
        before = self.old_snapshot()
        with patch('apps.api.migrations._import_schema', side_effect=self.partial_failure):
            with self.assertRaisesRegex(RuntimeError, 'interrupted import schema'):
                migrate(self.engine)
        self.assertEqual(self.versions(), ['0001', '0002'])
        self.assertTrue(set(IMPORT_TABLE_NAMES).isdisjoint(inspect(self.engine).get_table_names()))
        self.assertEqual(self.old_snapshot(), before)
        self.assertEqual(migrate(self.engine), VERSIONS[2:])
        self.assert_empty_evidence()

    def test_fresh_failure_in_0003_rolls_back_entire_initial_upgrade(self):
        with patch('apps.api.migrations._import_schema', side_effect=self.partial_failure):
            with self.assertRaises(RuntimeError):
                migrate(self.engine)
        self.assertEqual(inspect(self.engine).get_table_names(), [])
        self.assertEqual(migrate(self.engine), VERSIONS)

    def test_concurrent_upgrades_apply_0003_exactly_once(self):
        self.prepare_v2()
        before = self.old_snapshot()
        barrier = threading.Barrier(3)

        def apply():
            barrier.wait(timeout=10)
            return migrate(self.engine)

        with ThreadPoolExecutor(max_workers=3) as pool:
            tasks = [pool.submit(apply) for _ in range(3)]
            results = [task.result(timeout=20) for task in tasks]
        self.assertEqual(results.count(VERSIONS[2:]), 1)
        self.assertEqual(results.count(()), 2)
        self.assertEqual(self.versions(), list(VERSIONS))
        self.assertEqual(self.old_snapshot(), before)
        self.assert_empty_evidence()

    def test_evidence_defaults_preserve_unknown_hashes_and_mode_constraint(self):
        migrate(self.engine)
        values = dict(organization_id='demo', actor_id='operator', kind='daily_sales', source={}, summary={}, expected_state={})
        with self.engine.begin() as connection:
            connection.execute(ImportEvidence.__table__.insert(), dict(batch_id='unknown-source', **values))
        with self.engine.connect() as connection:
            row = connection.execute(select(ImportEvidence.__table__)).mappings().one()
            self.assertEqual((row['contract_version'], row['mode']), ('app-import-v1', 'append'))
            for field in ('received_text_sha256', 'canonical_rows_sha256', 'committed_at', 'receipt', 'corrects_batch_id'):
                self.assertIsNone(row[field])
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as connection:
                connection.execute(ImportEvidence.__table__.insert(), dict(batch_id='bad-mode', mode='replace', **values))

    def test_revision_order_is_positive_and_unique_within_organization_and_key(self):
        migrate(self.engine)
        values = dict(organization_id='A', kind='daily_sales', natural_key='["2025-12-31","1","1"]',
            branch_id='1', revision=1, record_id=None, before_data=None,
            after_data={'units_sold': 2, 'price_kzt': '1200.00', 'data_origin': 'SYNTHETIC'},
            before_sha256=None, after_sha256='a' * 64, batch_id='batch', actor_id='actor')
        with self.engine.begin() as connection:
            connection.execute(RecordRevision.__table__.insert(), dict(id='first', **values))
            connection.execute(RecordRevision.__table__.insert(), dict(values, id='other-organization', organization_id='B'))
            connection.execute(RecordRevision.__table__.insert(), dict(values, id='second-revision', revision=2))
        for identifier, change in (('duplicate', {}), ('zero', {'revision': 0}), ('negative', {'revision': -1})):
            with self.subTest(identifier=identifier), self.assertRaises(IntegrityError):
                with self.engine.begin() as connection:
                    connection.execute(RecordRevision.__table__.insert(), dict(values, id=identifier, **change))

    def test_import_receipt_namespace_does_not_collide_with_plan_idempotency(self):
        migrate(self.engine)
        common = dict(organization_id='A', actor_id='actor', key='same-client-key', payload_hash='a' * 64)
        with self.engine.begin() as connection:
            connection.execute(Idempotency.__table__.insert(), dict(id='plan', response={'entity': 'plan'}, **common))
            connection.execute(ImportReceipt.__table__.insert(), dict(id='import', batch_id='batch', response={'entity': 'import'}, **common))
            connection.execute(ImportReceipt.__table__.insert(), dict(common, id='other-actor', actor_id='peer', batch_id='batch', response={}))
            connection.execute(ImportReceipt.__table__.insert(), dict(common, id='other-org', organization_id='B', batch_id='batch', response={}))
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as connection:
                connection.execute(ImportReceipt.__table__.insert(), dict(id='duplicate', batch_id='other-batch', response={}, **common))

    def test_unexpected_existing_sidecar_is_not_overwritten_or_stamped(self):
        self.prepare_v2()
        before = self.old_snapshot()
        with self.engine.begin() as connection:
            connection.execute(text('CREATE TABLE import_evidence (sentinel TEXT NOT NULL)'))
            connection.execute(text("INSERT INTO import_evidence (sentinel) VALUES ('preserve-me')"))
        with self.assertRaises(SQLAlchemyError):
            migrate(self.engine)
        self.assertEqual(self.versions(), ['0001', '0002'])
        self.assertEqual(self.old_snapshot(), before)
        self.assertNotIn('record_revisions', inspect(self.engine).get_table_names())
        self.assertNotIn('import_receipts', inspect(self.engine).get_table_names())
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text('SELECT sentinel FROM import_evidence')).scalar_one(), 'preserve-me')


if __name__ == '__main__':
    unittest.main()
