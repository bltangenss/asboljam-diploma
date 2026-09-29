"""Operator source registration on empty isolated tenants; no enterprise data.

The purpose test_fixture is an explicit protocol exercise, not a real pilot.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import time
import unittest

from sqlalchemy import delete, select

from apps.api import tenants
from apps.api.db import (Audit, AuthSession, Base, Forecast, Idempotency, ImportBatch, ImportEvidence,
                         ImportReceipt, Job, Organization, OrganizationSource, Plan, Record,
                         RecordRevision, RefreshToken, User, make_engine, migrate, sessions)
from database_fixture import isolated_database_url


class RealSourceTests(unittest.TestCase):
    def setUp(self):
        Path('.cache').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='real-source-', dir='.cache')
        self.addCleanup(self.temp.cleanup)
        self.engine = make_engine(isolated_database_url(
            'sqlite:///' + (Path(self.temp.name).resolve() / 'test.sqlite').as_posix()))
        self.addCleanup(self.engine.dispose)
        migrate(self.engine)
        self.factory = sessions(self.engine)
        with self.factory() as db:
            for org, token, refresh in (('A', 'a', 'b'), ('B', 'c', 'd')):
                db.add(Organization(id=org, name=org + ' empty fixture', timezone='Asia/Qyzylorda',
                    data_policy='unconfigured', provenance='operator_bootstrap'))
                db.add(User(id=org + '-owner', organization_id=org, email=org.lower() + '@fixture.invalid',
                    password_hash='non-authenticating-fixture', role='admin', branch_ids=[], active=True))
                db.add(AuthSession(id=org + '-session', user_id=org + '-owner', token_hash=token * 64,
                    csrf_token='fixture', expires_at=time.time() + 3600, kind='web'))
                db.add(RefreshToken(token_hash=refresh * 64, user_id=org + '-owner', family_id=org,
                    expires_at=time.time() + 3600))
                db.add(Audit(id=org + '-created', organization_id=org, actor_id='operator:fixture',
                    action='tenant.created', entity_id=org, details={'fixture': True}))
            db.commit()

    def metadata(self, org='A', **overrides):
        result = dict(organization_id=org, source_id='fixture-pos', mapping_version='canonical-v1',
            branch_id='001', authorization_reference='fixture-reference-01', purpose='test_fixture',
            operator_id='fixture-owner', reason='Configure an isolated generated protocol fixture')
        result.update(overrides)
        return result

    def snapshot(self):
        with self.engine.connect() as connection:
            return {name: [dict(row._mapping) for row in connection.execute(
                select(table).order_by(*table.primary_key.columns))] for name, table in Base.metadata.tables.items()}

    def configure(self, **values):
        with self.factory() as db:
            result = tenants.configure_real_source(db, **self.metadata(**values))
            db.commit()
            return result

    def assert_denied_without_changes(self, code, **values):
        before = self.snapshot()
        with self.assertRaises(tenants.TenantError) as error:
            self.configure(**values)
        self.assertEqual(error.exception.code, code)
        self.assertEqual(self.snapshot(), before)

    def blockers(self, org='A'):
        return [
            Record(organization_id=org, kind='branches', natural_key='["1"]', branch_id='1', data={'fixture': True}),
            ImportBatch(id='old-preview', organization_id=org, actor_id=org + '-owner', kind='daily_sales',
                        rows=[], errors=[{'code': 'INVALID_VALUE'}], status='preview'),
            Job(id='old-job', organization_id=org, actor_id=org + '-owner', branch_id='1', kind='forecast',
                status='failed', payload={}, snapshot={}),
            Forecast(id='old-result', organization_id=org, branch_id='1', result={}),
            Plan(id='old-plan', organization_id=org, branch_id='1', forecast_id='old-result', status='approved', result={}),
            Idempotency(id='old-key', organization_id=org, actor_id=org + '-owner', key='old', payload_hash='a' * 64, response={}),
            ImportEvidence(batch_id='old-evidence', organization_id=org, actor_id=org + '-owner', kind='daily_sales',
                           source={}, summary={}, expected_state={}),
            RecordRevision(id='old-revision', organization_id=org, kind='daily_sales', natural_key='["1"]',
                           revision=1, after_data={}, after_sha256='a' * 64, batch_id='old', actor_id=org + '-owner'),
            ImportReceipt(id='old-receipt', organization_id=org, actor_id=org + '-owner', key='old',
                          payload_hash='a' * 64, batch_id='old', response={}),
            Audit(id='old-audit', organization_id=org, actor_id=org + '-owner', action='plan.approved',
                  entity_id='deleted-old-plan', details={'fixture': True}),
        ]

    def test_preflight_is_read_only_and_never_invents_operational_data(self):
        before = self.snapshot()
        with self.factory() as db:
            result = tenants.preflight_configure_real_source(db, **self.metadata())
            self.assertEqual(result['actor_id'], 'operator:fixture-owner')
        self.assertEqual(self.snapshot(), before)

    def test_activation_records_declared_source_and_revokes_only_selected_tenant_sessions(self):
        result = self.configure()
        self.assertEqual(result['organization']['data_policy'], 'real_only')
        self.assertTrue(result['reauth_required'])
        with self.factory() as db:
            source = db.get(OrganizationSource, 'A')
            self.assertEqual((source.source_id, source.mapping_version, source.branch_id, source.version),
                             ('fixture-pos', 'canonical-v1', '001', 1))
            self.assertEqual((source.authorization_reference, source.purpose, source.actor_id),
                             ('fixture-reference-01', 'test_fixture', 'operator:fixture-owner'))
            self.assertTrue(db.get(AuthSession, 'A-session').revoked)
            self.assertTrue(db.get(RefreshToken, 'b' * 64).revoked)
            self.assertFalse(db.get(AuthSession, 'B-session').revoked)
            self.assertFalse(db.get(RefreshToken, 'd' * 64).revoked)
            self.assertEqual(db.get(Organization, 'B').data_policy, 'unconfigured')
            self.assertEqual(db.get(User, 'A-owner').branch_ids, [])
            self.assertFalse(list(db.scalars(select(Record))))
            events = list(db.scalars(select(Audit).where(Audit.action == 'tenant.real_source_configured')))
            self.assertEqual(len(events), 1)
            self.assertNotIn('authorization_reference', events[0].details)
            self.assertEqual(events[0].details['purpose'], 'test_fixture')
        self.assert_denied_without_changes('SOURCE_ALREADY_CONFIGURED', source_id='another-pos')

    def test_invalid_metadata_cannot_activate_or_echo_supplied_values(self):
        cases = [({'source_id': 'path/to/source'}, 'SOURCE_METADATA_INVALID'),
                 ({'mapping_version': 'v' * 65}, 'SOURCE_METADATA_INVALID'),
                 ({'authorization_reference': 'person@example.invalid'}, 'SOURCE_METADATA_INVALID'),
                 ({'authorization_reference': 'C:\\private\\agreement.pdf'}, 'SOURCE_METADATA_INVALID'),
                 ({'authorization_reference': 'a' * 129}, 'SOURCE_METADATA_INVALID'),
                 ({'authorization_reference': 'private free text'}, 'SOURCE_METADATA_INVALID'),
                 ({'branch_id': 'a b'}, 'SOURCE_BRANCH_INVALID'),
                 ({'purpose': 'verified'}, 'SOURCE_PURPOSE_INVALID'),
                 ({'operator_id': 'person@example.invalid'}, 'OPERATOR_INVALID'),
                 ({'reason': ' '}, 'REASON_REQUIRED')]
        for values, code in cases:
            with self.subTest(values=values):
                self.assert_denied_without_changes(code, **values)

    def test_unknown_or_invalid_tenant_metadata_requires_operator_reconciliation(self):
        for values in ({'name': None}, {'name': ' '}, {'timezone': None},
                       {'timezone': 'Invalid/Fixture'}, {'currency': 'USD'}):
            with self.subTest(values=values):
                with self.factory() as db:
                    organization = db.get(Organization, 'A')
                    organization.name, organization.timezone, organization.currency = 'A fixture', 'Asia/Qyzylorda', 'KZT'
                    for key, value in values.items():
                        setattr(organization, key, value)
                    db.commit()
                self.assert_denied_without_changes('TENANT_METADATA_REQUIRED')

    def test_existing_operational_history_and_all_sidecars_block_activation(self):
        for blocker in self.blockers():
            model = type(blocker)
            with self.subTest(model=model.__name__):
                with self.factory() as db:
                    db.add(blocker)
                    db.commit()
                self.assert_denied_without_changes('TENANT_NOT_EMPTY')
                with self.factory() as db:
                    if model is Audit:
                        db.execute(delete(Audit).where(Audit.id == 'old-audit'))
                    else:
                        db.execute(delete(model).where(model.organization_id == 'A'))
                    db.commit()

    def test_source_registration_and_nonempty_other_tenant_remain_isolated(self):
        with self.factory() as db:
            db.add_all(self.blockers('B'))
            db.commit()
        before = self.snapshot()
        self.configure()
        after = self.snapshot()
        for name in before:
            before_b = [row for row in before[name] if row.get('organization_id') == 'B']
            after_b = [row for row in after[name] if row.get('organization_id') == 'B']
            self.assertEqual(after_b, before_b, name)

    def test_synthetic_real_or_suspended_organization_cannot_be_reconfigured(self):
        for policy, status, code in [('synthetic_only', 'active', 'DATA_POLICY_CONFLICT'),
                                     ('real_only', 'active', 'DATA_POLICY_CONFLICT'),
                                     ('unconfigured', 'suspended', 'TENANT_NOT_ACTIVE')]:
            with self.subTest(policy=policy, status=status):
                with self.factory() as db:
                    organization = db.get(Organization, 'A')
                    organization.data_policy, organization.status = policy, status
                    db.commit()
                self.assert_denied_without_changes(code)

    def test_source_policy_revocation_and_audit_roll_back_together(self):
        before = self.snapshot()
        with self.assertRaisesRegex(RuntimeError, 'Controlled caller failure'):
            with self.factory() as db:
                tenants.configure_real_source(db, **self.metadata())
                raise RuntimeError('Controlled caller failure before commit')
        self.assertEqual(self.snapshot(), before)

    def test_parallel_activation_selects_one_immutable_source(self):
        barrier = threading.Barrier(2)

        def run(index):
            with self.factory() as db:
                tenants.preflight_configure_real_source(db, **self.metadata(source_id=f'source-{index}'))
            barrier.wait(timeout=10)
            try:
                self.configure(source_id=f'source-{index}')
                return 'configured'
            except tenants.TenantError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, index) for index in range(2)]
            results = [future.result(timeout=25) for future in futures]
        self.assertCountEqual(results, ['configured', 'SOURCE_ALREADY_CONFIGURED'])
        with self.factory() as db:
            self.assertEqual(len(list(db.scalars(select(OrganizationSource)))), 1)
            self.assertEqual(len(list(db.scalars(select(Audit).where(Audit.action == 'tenant.real_source_configured')))), 1)

    def test_bootstrap_refuses_orphan_sidecars_and_registered_source(self):
        source = OrganizationSource(organization_id='orphan', source_id='fixture', mapping_version='v1',
            branch_id='1', authorization_reference='fixture-ref', purpose='test_fixture', actor_id='operator:fixture')
        candidates = [row for row in self.blockers('orphan') if isinstance(row, (ImportEvidence, RecordRevision, ImportReceipt))]
        for blocker in candidates + [source]:
            with self.subTest(model=type(blocker).__name__):
                with self.factory() as db:
                    db.add(blocker)
                    db.commit()
                before = self.snapshot()
                with self.factory() as db, self.assertRaises(tenants.TenantError) as error:
                    tenants.preflight_bootstrap(db, organization_id='orphan', name='Orphan fixture',
                        timezone='Asia/Qyzylorda', email='orphan@fixture.invalid',
                        operator_id='fixture', reason='Verify no orphan takeover')
                self.assertEqual(error.exception.code, 'ORGANIZATION_ORPHANED')
                self.assertEqual(self.snapshot(), before)
                with self.factory() as db:
                    db.execute(delete(type(blocker)).where(type(blocker).organization_id == 'orphan'))
                    db.commit()


if __name__ == '__main__':
    unittest.main()
