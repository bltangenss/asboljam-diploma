"""0004 upgrade preserves populated0003 stores and never invents source permission.

SQLite by default; all but the named backup case use the optional isolated PG
fixture. The backup case deliberately uses new SQLite files even in a PG run.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from apps.api import migrations
from apps.api.db import (Base, ImportEvidence, ImportReceipt, Organization, OrganizationSource,
                         RecordRevision, make_engine, migrate)
from apps.api.migrations import IMPORT_TABLE_NAMES, LEGACY_TABLE_NAMES, SOURCE_TABLE_NAMES, VERSIONS
from database_fixture import isolated_database_url
from scripts.backup_db import copy_database
import test_tenant_migration as legacy_fixture


class RealSourceMigrationTests(unittest.TestCase):
    def setUp(self):
        Path('.cache').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='real-source-migration-', dir='.cache')
        self.addCleanup(self.temp.cleanup)
        self.engine = make_engine(isolated_database_url(
            'sqlite:///' + (Path(self.temp.name).resolve() / 'test.sqlite').as_posix()))
        self.addCleanup(self.engine.dispose)

    def versions(self):
        with self.engine.connect() as connection:
            return list(connection.execute(text('SELECT version FROM schema_migrations ORDER BY version')).scalars())

    def prepare_v3(self):
        legacy_fixture.TenantMigrationTests.legacy_schema(self)
        with self.engine.begin() as connection:
            migrations._tenant_schema(connection)
            migrations._import_schema(connection)
            connection.execute(text("INSERT INTO schema_migrations (version) VALUES ('0002'), ('0003')"))
            connection.execute(Organization.__table__.insert(), dict(id='empty', name='Known empty fixture',
                timezone='Asia/Qyzylorda', data_policy='unconfigured', provenance='operator_bootstrap'))
            connection.execute(ImportEvidence.__table__.insert(), dict(batch_id='batch', organization_id='imports-only',
                actor_id='legacy-user', kind='daily_sales', source={'provenance': 'received_csv_text'},
                summary={'fixture': True}, expected_state={'unchanged': 1}, received_text_sha256='a' * 64))
            connection.execute(RecordRevision.__table__.insert(), dict(id='revision', organization_id='records-only',
                kind='ingredients', natural_key='0007', revision=1, record_id=77, after_data={'fixture': True},
                after_sha256='b' * 64, batch_id='batch', actor_id='legacy-user', reason='Preserve fixture history'))
            connection.execute(ImportReceipt.__table__.insert(), dict(id='receipt', organization_id='imports-only',
                actor_id='legacy-user', key='preserved', payload_hash='c' * 64, batch_id='batch', response={'saved': True}))
        self.assertEqual(self.versions(), ['0001', '0002', '0003'])
        self.assertTrue(set(SOURCE_TABLE_NAMES).isdisjoint(inspect(self.engine).get_table_names()))

    def snapshot(self):
        with self.engine.connect() as connection:
            return {name: [dict(row._mapping) for row in connection.execute(
                select(Base.metadata.tables[name]).order_by(*Base.metadata.tables[name].primary_key.columns))]
                for name in (*LEGACY_TABLE_NAMES, 'organizations', *IMPORT_TABLE_NAMES)}

    def assert_old_policy_constraint(self):
        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            connection.execute(Organization.__table__.insert(), dict(id='must-reject-real',
                data_policy='real_only', provenance='fixture'))

    def source_values(self, organization_id='empty', **overrides):
        result = dict(organization_id=organization_id, source_id='fixture-pos', mapping_version='canonical-v1',
            branch_id='01', authorization_reference='fixture-reference', purpose='test_fixture', actor_id='operator:fixture')
        result.update(overrides)
        return result

    def test_original_0002_and_0003_still_reject_real_policy(self):
        legacy_fixture.TenantMigrationTests.legacy_schema(self, populated=False)
        with self.engine.begin() as connection:
            migrations._tenant_schema(connection)
            connection.execute(text("INSERT INTO schema_migrations VALUES ('0002')"))
        self.assert_old_policy_constraint()
        with self.engine.begin() as connection:
            migrations._import_schema(connection)
            connection.execute(text("INSERT INTO schema_migrations VALUES ('0003')"))
        self.assert_old_policy_constraint()
        self.assertNotIn('organization_sources', inspect(self.engine).get_table_names())

    def test_fresh_schema_applies_all_versions_without_source_or_tenant(self):
        self.assertEqual(migrate(self.engine), VERSIONS)
        self.assertEqual(self.versions(), list(VERSIONS))
        self.assertEqual(set(inspect(self.engine).get_table_names()),
                         set(Base.metadata.tables) | {'schema_migrations'})
        with self.engine.connect() as connection:
            self.assertEqual(list(connection.execute(select(Organization.__table__))), [])
            self.assertEqual(list(connection.execute(select(OrganizationSource.__table__))), [])

    def test_populated_0003_upgrade_preserves_all_rows_and_leaves_sources_empty(self):
        self.prepare_v3()
        before = self.snapshot()
        self.assertTrue(all(before.values()))
        self.assertEqual(migrate(self.engine), ('0004',))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.versions(), list(VERSIONS))
        with self.engine.connect() as connection:
            self.assertEqual(list(connection.execute(select(OrganizationSource.__table__))), [])
        self.assertEqual(migrate(self.engine), ())
        self.assertEqual(self.snapshot(), before)

    def test_failure_after_rebuild_rolls_back_schema_rows_and_marker(self):
        self.prepare_v3()
        before, apply_source = self.snapshot(), migrations._real_source_schema

        def fail(connection):
            apply_source(connection)
            connection.execute(OrganizationSource.__table__.insert(), self.source_values())
            raise RuntimeError('Controlled failure after source table creation')

        with patch.object(migrations, '_real_source_schema', side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, 'Controlled failure'):
                migrate(self.engine)
        self.assertEqual(self.versions(), ['0001', '0002', '0003'])
        self.assertEqual(self.snapshot(), before)
        self.assertNotIn('organization_sources', inspect(self.engine).get_table_names())
        self.assertNotIn('organizations_v0004', inspect(self.engine).get_table_names())
        self.assert_old_policy_constraint()
        self.assertEqual(migrate(self.engine), ('0004',))

    def test_fresh_failure_in_0004_rolls_back_every_version(self):
        apply_source = migrations._real_source_schema

        def fail(connection):
            apply_source(connection)
            raise RuntimeError('Controlled initial failure')

        with patch.object(migrations, '_real_source_schema', side_effect=fail):
            with self.assertRaises(RuntimeError):
                migrate(self.engine)
        self.assertEqual(inspect(self.engine).get_table_names(), [])
        self.assertEqual(migrate(self.engine), VERSIONS)

    def test_concurrent_0003_upgrades_apply_0004_once(self):
        self.prepare_v3()
        before, barrier = self.snapshot(), threading.Barrier(3)

        def apply():
            barrier.wait(timeout=10)
            return migrate(self.engine)

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(apply) for _ in range(3)]
            results = [future.result(timeout=25) for future in futures]
        self.assertEqual(results.count(('0004',)), 1)
        self.assertEqual(results.count(()), 2)
        self.assertEqual(self.snapshot(), before)

    def test_future_marker_rejects_upgrade_without_any_schema_or_row_change(self):
        self.prepare_v3()
        before = self.snapshot()
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO schema_migrations VALUES ('0005')"))
        tables = inspect(self.engine).get_table_names()
        with self.assertRaises(migrations.MigrationError):
            migrate(self.engine)
        self.assertEqual(inspect(self.engine).get_table_names(), tables)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.versions(), ['0001', '0002', '0003', '0005'])
        self.assert_old_policy_constraint()

    def test_existing_unknown_source_table_is_preserved_and_blocks_upgrade(self):
        self.prepare_v3()
        before = self.snapshot()
        with self.engine.begin() as connection:
            connection.execute(text('CREATE TABLE organization_sources (sentinel TEXT NOT NULL)'))
            connection.execute(text("INSERT INTO organization_sources VALUES ('preserve')"))
        with self.assertRaises(SQLAlchemyError):
            migrate(self.engine)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.versions(), ['0001', '0002', '0003'])
        self.assert_old_policy_constraint()
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text('SELECT sentinel FROM organization_sources')).scalar_one(), 'preserve')

    def test_source_constraints_and_unique_organization_are_database_enforced(self):
        migrate(self.engine)
        with self.engine.begin() as connection:
            connection.execute(Organization.__table__.insert(), dict(id='empty', data_policy='real_only', provenance='fixture'))
            connection.execute(OrganizationSource.__table__.insert(), self.source_values())
        with self.engine.connect() as connection:
            row = connection.execute(select(OrganizationSource.__table__)).mappings().one()
            self.assertEqual(row['version'], 1)
        for values in (self.source_values(source_id='another-source'), self.source_values('bad', purpose='verified'),
                       self.source_values('bad', version=0), self.source_values('bad', version=-1)):
            with self.subTest(values=values), self.assertRaises(IntegrityError), self.engine.begin() as connection:
                connection.execute(OrganizationSource.__table__.insert(), values)

    def test_custom_organization_index_is_never_silently_discarded(self):
        self.prepare_v3()
        before = self.snapshot()
        with self.engine.begin() as connection:
            connection.execute(text('CREATE INDEX custom_organization_name ON organizations (name)'))
        if self.engine.dialect.name == 'sqlite':
            with self.assertRaises(migrations.MigrationError):
                migrate(self.engine)
            self.assertEqual(self.versions(), ['0001', '0002', '0003'])
            self.assertNotIn('organization_sources', inspect(self.engine).get_table_names())
        else:
            self.assertEqual(migrate(self.engine), ('0004',))
        self.assertEqual(self.snapshot(), before)
        self.assertIn('custom_organization_name', {index['name'] for index in inspect(self.engine).get_indexes('organizations')})

    def test_sqlite_backup_of_0003_restores_into_new_path_without_real_activation(self):
        # Explicitly SQLite-specific, including when the suite's other cases opt into PG.
        active_engine = self.engine
        sqlite_engine = make_engine('sqlite:///' + (Path(self.temp.name) / 'backup-source.sqlite').as_posix())
        self.addCleanup(sqlite_engine.dispose)
        try:
            self.engine = sqlite_engine
            self.prepare_v3()
            before = self.snapshot()
            backup = Path(self.temp.name) / 'pre0004.sqlite'
            copy_database(Path(self.temp.name) / 'backup-source.sqlite', backup)
            self.assertEqual(migrate(sqlite_engine), ('0004',))
            restored = Path(self.temp.name) / 'restored0003.sqlite'
            restored_report = copy_database(backup, restored, 'restore')
            self.assertEqual(restored_report['integrity_check'], 'ok')
            self.engine = make_engine('sqlite:///' + restored.as_posix())
            self.addCleanup(self.engine.dispose)
            self.assertEqual(self.versions(), ['0001', '0002', '0003'])
            self.assertEqual(self.snapshot(), before)
            self.assert_old_policy_constraint()
            self.assertEqual(migrate(self.engine), ('0004',))
            self.assertEqual(self.snapshot(), before)
        finally:
            self.engine = active_engine


if __name__ == '__main__':
    unittest.main()
