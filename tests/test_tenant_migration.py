"""Explicit tenant migration: real transactions, preservation, rollback and concurrency.

Defaults to temporary SQLite; ASBOLJAM_SECURITY_TEST_DATABASE_URL opts into a fresh
PostgreSQL schema through the shared fixture guard. No operational database is used.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from apps.api.db import Base, Organization, make_engine, migrate
from apps.api.migrations import IMPORT_TABLE_NAMES, LEGACY_TABLE_NAMES, SOURCE_TABLE_NAMES, VERSIONS, MigrationError, _initial_schema
from database_fixture import isolated_database_url
from scripts.backup_db import copy_database


class TenantMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='tenant-migration-')
        self.addCleanup(self.temp.cleanup)
        self.engine = make_engine(isolated_database_url(
            'sqlite:///' + (Path(self.temp.name) / 'migration.sqlite').as_posix()))
        self.addCleanup(self.engine.dispose)

    def versions(self):
        with self.engine.connect() as connection:
            return list(connection.execute(text('SELECT version FROM schema_migrations ORDER BY version')).scalars())

    def organizations(self):
        with self.engine.connect() as connection:
            return [dict(row._mapping) for row in connection.execute(select(Organization.__table__).order_by(Organization.id))]

    def legacy_snapshot(self):
        with self.engine.connect() as connection:
            return {name: [dict(row._mapping) for row in connection.execute(
                select(*[c for c in Base.metadata.tables[name].columns
                        if not (name == "jobs" and c.name == "heartbeat_at")]).order_by(*Base.metadata.tables[name].primary_key.columns))]
                for name in LEGACY_TABLE_NAMES}

    def legacy_schema(self, populated=True):
        with self.engine.begin() as connection:
            _initial_schema(connection)
            connection.execute(text('CREATE TABLE schema_migrations (version VARCHAR(32) PRIMARY KEY)'))
            connection.execute(text("INSERT INTO schema_migrations (version) VALUES ('0001')"))
            if populated:
                fixtures = {
                    'users': [
                        dict(id='legacy-user', organization_id='users-only', email='legacy@fixture.invalid', password_hash='preserved-fixture-hash', role='manager', branch_ids=['01', '02'], active=False),
                        dict(id='demo-user', organization_id='demo', email='demo@fixture.invalid', password_hash='another-preserved-fixture-hash', role='admin', branch_ids=['01'], active=True),
                    ],
                    'auth_sessions': [dict(id='session', user_id='legacy-user', token_hash='a' * 64, csrf_token='fixture-csrf', kind='web', family_id='family', expires_at=2000000000, revoked=False)],
                    'refresh_tokens': [dict(token_hash='b' * 64, user_id='legacy-user', family_id='family', expires_at=2000000001, used=True, revoked=False)],
                    'login_attempts': [dict(id='attempt', identity='fixture-identity', timestamp=1900000000)],
                    'operational_records': [
                        dict(id=77, organization_id='records-only', kind='ingredients', natural_key='0007', branch_id=None, data={'ingredient_id': '0007', 'reference_cost_kzt': '105.10', 'unit': 'kg', 'data_origin': 'SYNTHETIC'}),
                        dict(id=78, organization_id='demo', kind='branches', natural_key='01', branch_id='01', data={'branch_id': '01', 'branch_name': 'Fixture branch', 'data_origin': 'SYNTHETIC'}),
                    ],
                    'import_batches': [dict(id='batch', organization_id='imports-only', actor_id='legacy-user', kind='daily_sales', rows=[{'meal_id': '0007'}], errors=[], status='preview')],
                    'jobs': [dict(id='job', organization_id='jobs-only', branch_id='01', actor_id='legacy-user', kind='forecast', status='queued', payload={'origin': '2025-12-31'}, snapshot={'sales': []}, result_id=None, started_at=None)],
                    'forecasts': [dict(id='forecast', organization_id='forecasts-only', branch_id='01', result={'target_date': '2026-01-01', 'predictions': []})],
                    'plans': [dict(id='plan', organization_id='plans-only', branch_id='01', forecast_id='forecast', version=3, status='approved', result={'total_cost': '123.40', 'lines': []})],
                    'audit_events': [dict(id='event', organization_id='audit-only', branch_id='01', actor_id='legacy-user', action='fixture.approved', entity_id='plan', details={'reason': 'Synthetic migration fixture', 'expected_version': 2})],
                    'idempotency_keys': [dict(id='key', organization_id='idempotency-only', actor_id='legacy-user', key='fixture-request', payload_hash='c' * 64, response={'status': 'approved', 'version': 3})],
                }
                for name, rows in fixtures.items():
                    connection.execute(Base.metadata.tables[name].insert(), rows)
        self.assertNotIn('organizations', inspect(self.engine).get_table_names())

    def test_fresh_database_applies_current_versions_without_inventing_a_tenant(self):
        self.assertEqual(migrate(self.engine), VERSIONS)
        self.assertEqual(self.versions(), list(VERSIONS))
        self.assertEqual(self.organizations(), [])
        self.assertEqual(set(inspect(self.engine).get_table_names()),
                         set(LEGACY_TABLE_NAMES) | set(IMPORT_TABLE_NAMES) | set(SOURCE_TABLE_NAMES) | {'organizations', 'schema_migrations'})

    def test_0001_table_allowlist_excludes_new_models(self):
        self.legacy_schema(populated=False)
        self.assertEqual(self.versions(), ['0001'])
        self.assertNotIn('organizations', LEGACY_TABLE_NAMES)
        self.assertEqual(set(inspect(self.engine).get_table_names()), set(LEGACY_TABLE_NAMES) | {'schema_migrations'})

    def test_backfill_includes_every_scoped_table_and_preserves_all_old_rows(self):
        self.legacy_schema()
        before = self.legacy_snapshot()
        self.assertTrue(all(before[name] for name in LEGACY_TABLE_NAMES))
        self.assertEqual(migrate(self.engine), VERSIONS[1:])
        self.assertEqual(self.legacy_snapshot(), before)
        self.assertEqual(self.versions(), list(VERSIONS))
        rows = {row['id']: row for row in self.organizations()}
        self.assertEqual(set(rows), {'demo', 'users-only', 'records-only', 'imports-only',
                                    'jobs-only', 'forecasts-only', 'plans-only', 'audit-only', 'idempotency-only'})
        for identifier, row in rows.items():
            self.assertEqual(row['currency'], 'KZT')
            self.assertEqual(row['status'], 'active')
            self.assertEqual(row['data_policy'], 'synthetic_only')
            self.assertEqual(row['provenance'], 'legacy_migration')
            self.assertIsNotNone(datetime.fromisoformat(row['created_at']).tzinfo)
            self.assertEqual(row['name'], 'AsBoljam Demo' if identifier == 'demo' else None)
            self.assertEqual(row['timezone'], 'Asia/Qyzylorda' if identifier == 'demo' else None)

    def test_repeat_preserves_metadata_and_does_not_backfill_future_orphans(self):
        self.legacy_schema()
        migrate(self.engine)
        with self.engine.begin() as connection:
            connection.execute(Organization.__table__.update().where(Organization.id == 'demo').values(
                name='Operator chosen name', timezone='Asia/Almaty', status='suspended', data_policy='unconfigured'))
            connection.execute(Base.metadata.tables['users'].insert(), dict(
                id='future-orphan', organization_id='future-orphan-org', email='orphan@fixture.invalid',
                password_hash='fixture', role='analyst', branch_ids=[], active=True))
        before_orgs, before_legacy = self.organizations(), self.legacy_snapshot()
        self.assertEqual(migrate(self.engine), ())
        self.assertEqual(self.organizations(), before_orgs)
        self.assertEqual(self.legacy_snapshot(), before_legacy)
        self.assertNotIn('future-orphan-org', {row['id'] for row in self.organizations()})

    def test_upgrade_failure_rolls_back_table_backfill_and_version_together(self):
        self.legacy_schema()
        before = self.legacy_snapshot()

        def fail_after_insert(connection):
            connection.execute(Organization.__table__.insert(), dict(id='partial', provenance='fixture'))
            raise RuntimeError('Simulated interrupted backfill')

        with patch('apps.api.migrations._backfill_organizations', side_effect=fail_after_insert):
            with self.assertRaisesRegex(RuntimeError, 'interrupted backfill'):
                migrate(self.engine)
        self.assertEqual(self.versions(), ['0001'])
        self.assertNotIn('organizations', inspect(self.engine).get_table_names())
        self.assertEqual(self.legacy_snapshot(), before)
        self.assertEqual(migrate(self.engine), VERSIONS[1:])

    def test_fresh_failure_rolls_back_even_initial_ddl(self):
        with patch('apps.api.migrations._backfill_organizations', side_effect=RuntimeError('Simulated failure')):
            with self.assertRaises(RuntimeError):
                migrate(self.engine)
        self.assertEqual(inspect(self.engine).get_table_names(), [])
        self.assertEqual(migrate(self.engine), VERSIONS)

    def test_future_version_refused_without_modifying_legacy_database(self):
        self.legacy_schema()
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO schema_migrations (version) VALUES ('9999')"))
        before = self.legacy_snapshot()
        with self.assertRaisesRegex(MigrationError, 'Unsupported or incomplete'):
            migrate(self.engine)
        self.assertEqual(self.versions(), ['0001', '9999'])
        self.assertNotIn('organizations', inspect(self.engine).get_table_names())
        self.assertEqual(self.legacy_snapshot(), before)

    def test_incomplete_history_refused_without_adding_tables(self):
        with self.engine.begin() as connection:
            connection.execute(text('CREATE TABLE schema_migrations (version VARCHAR(32) PRIMARY KEY)'))
            connection.execute(text("INSERT INTO schema_migrations (version) VALUES ('0002')"))
        with self.assertRaises(MigrationError):
            migrate(self.engine)
        self.assertEqual(inspect(self.engine).get_table_names(), ['schema_migrations'])
        self.assertEqual(self.versions(), ['0002'])

    def test_tenant_status_and_data_policy_constraints_are_enforced_by_database(self):
        migrate(self.engine)
        for change in ({'status': 'deleted'}, {'data_policy': 'REAL'}):
            with self.subTest(change=change), self.assertRaises(IntegrityError):
                with self.engine.begin() as connection:
                    connection.execute(Organization.__table__.insert(), dict(id='bad', provenance='fixture', **change))
        with self.engine.begin() as connection:
            connection.execute(Organization.__table__.insert(), dict(id='configured-later', provenance='operator_bootstrap'))
        row, = self.organizations()
        self.assertEqual((row['currency'], row['status'], row['data_policy']), ('KZT', 'active', 'unconfigured'))

    def test_concurrent_migration_runners_apply_upgrade_once(self):
        self.legacy_schema()
        before = self.legacy_snapshot()
        barrier = threading.Barrier(3)

        def start():
            barrier.wait(timeout=10)
            return migrate(self.engine)

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(start) for _ in range(3)]
            outcomes = [future.result(timeout=20) for future in futures]
        self.assertEqual(outcomes.count(VERSIONS[1:]), 1)
        self.assertEqual(outcomes.count(()), 2)
        self.assertEqual(self.versions(), list(VERSIONS))
        self.assertEqual(self.legacy_snapshot(), before)
        self.assertEqual(len(self.organizations()), 9)

    def test_sqlite_preupgrade_backup_restores_original_rows_and_can_upgrade_again(self):
        # This case is intentionally SQLite-specific even during the optional PG suite:
        # PostgreSQL backup uses pg_dump/pg_restore and requires separate evidence.
        original_engine = self.engine
        sqlite_path = Path(self.temp.name) / 'backup-source.sqlite'
        sqlite_engine = make_engine('sqlite:///' + sqlite_path.as_posix())
        restored_engine = None
        try:
            self.engine = sqlite_engine
            self.legacy_schema()
            before = self.legacy_snapshot()
            backup_path = Path(self.temp.name) / 'preupgrade.sqlite'
            backup = copy_database(sqlite_path, backup_path)
            self.assertEqual(backup['integrity_check'], 'ok')
            self.assertEqual(backup['foreign_key_check'], 'ok')
            self.assertEqual(migrate(sqlite_engine), VERSIONS[1:])
            self.assertEqual(self.legacy_snapshot(), before)
            self.assertEqual(self.versions(), list(VERSIONS))

            restore_path = Path(self.temp.name) / 'restored.sqlite'
            restored = copy_database(backup_path, restore_path, 'restore')
            self.assertEqual(restored['table_rows'], backup['table_rows'])
            self.assertEqual(restored['integrity_check'], 'ok')
            restored_engine = make_engine('sqlite:///' + restore_path.as_posix())
            self.engine = restored_engine
            self.assertEqual(self.versions(), ['0001'])
            self.assertNotIn('organizations', inspect(restored_engine).get_table_names())
            self.assertEqual(self.legacy_snapshot(), before)
            self.assertEqual(migrate(restored_engine), VERSIONS[1:])
            self.assertEqual(self.legacy_snapshot(), before)
            self.assertEqual(len(self.organizations()), 9)
        finally:
            self.engine = original_engine
            if restored_engine is not None:
                restored_engine.dispose()
            sqlite_engine.dispose()


if __name__ == '__main__':
    unittest.main()
