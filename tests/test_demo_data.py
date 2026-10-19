"""Demo data loads into an empty synthetic cabinet, rebuilt for its city; never twice."""
import csv
from datetime import date
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from apps.api import factor_builder
from apps.api.data_policy import workspace_context
from apps.api.db import Audit, BranchProfile, Organization, Record, User, make_engine, migrate, sessions
from apps.api.demo_data import DemoDataError, demo_source_branch, load_demo_data, register_demo_routes
from apps.api.importing import SCHEMAS, insert_rows, rows_for
from apps.api.main import create_app
from scripts import seed_demo

ROOT = Path(__file__).resolve().parents[1]
ORG = 'org-test'
ORIGIN = {'Origin': 'http://localhost:3000'}


def demo(kind, branch=None):
    with (ROOT / 'data' / 'kz' / f'{kind}.csv').open(encoding='utf-8-sig', newline='') as handle:
        return [row for row in csv.DictReader(handle) if branch is None or row.get('branch_id') == branch]


class DemoDataTests(unittest.TestCase):
    def setUp(self):
        Path('.cache').mkdir(exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir='.cache', prefix='demo-data-tests-')
        self.addCleanup(temp.cleanup)
        engine = make_engine('sqlite:///' + (Path(temp.name) / 'demo.sqlite').as_posix())
        self.addCleanup(engine.dispose)
        migrate(engine)
        self.factory = sessions(engine)

    def organization(self, db, *, data_policy='synthetic_only', city_code='almaty', establishment_type='cafe', profile=True):
        db.add(Organization(id=ORG, name='Тест', timezone='Asia/Almaty', currency='KZT', status='active',
                            data_policy=data_policy, provenance='self_registration'))
        db.flush()
        insert_rows(db, ORG, 'branches', [{'branch_id': '1', 'branch_name': 'Тест кафе', 'data_origin': 'SYNTHETIC'}])
        if profile:
            db.add(BranchProfile(organization_id=ORG, branch_id='1', city_code=city_code,
                                 establishment_type=establishment_type, updated_by='test'))
        db.flush()

    def records(self, db):
        return db.scalar(select(func.count()).select_from(Record).where(Record.organization_id == ORG))

    def test_cafe_in_almaty_loads_every_kind_from_demo_branch_2_into_branch_1(self):
        with self.factory() as db:
            self.organization(db)
            result = load_demo_data(db, ORG, '1')
            db.commit()
            self.assertEqual(result['source_branch'], '2')
            self.assertEqual(result['city_code'], 'almaty')
            self.assertEqual(set(result['rows']), set(SCHEMAS) - {'branches'})
            for kind in result['rows']:
                with self.subTest(kind=kind):
                    scoped = 'branch_id' in SCHEMAS[kind].split()
                    expected = len(demo(kind, '2' if scoped else None))
                    stored = list(db.scalars(select(Record).where(Record.organization_id == ORG, Record.kind == kind)))
                    self.assertEqual(result['rows'][kind], expected)
                    self.assertEqual(len(stored), expected)
                    self.assertTrue(all(row.data['data_origin'] == 'SYNTHETIC' for row in stored))
                    if scoped:
                        self.assertTrue(all(row.branch_id == '1' and row.data['branch_id'] == '1' for row in stored))
                    else:
                        self.assertTrue(all(row.branch_id is None for row in stored))
            self.assertEqual(len(rows_for(db, ORG, 'branches')), 1)

    def test_sunset_and_calendar_factors_follow_the_cabinet_city(self):
        with self.factory() as db:
            self.organization(db)
            load_demo_data(db, ORG, '1')
            db.commit()
            stored = {(row['date'], row['factor']): row['value'] for row in rows_for(db, ORG, 'day_factors', '1')}
        built = {(day.isoformat(), code): str(value) for day, code, value in
                 factor_builder.calendar_rows('almaty', date(2024, 1, 1), date(2026, 1, 1))}
        source = {(row['date'], row['factor']): row['value'] for row in demo('day_factors', '2')}
        self.assertEqual(stored[('2025-06-21', 'sunset_minutes')], built[('2025-06-21', 'sunset_minutes')])
        self.assertNotEqual(stored[('2025-06-21', 'sunset_minutes')], source[('2025-06-21', 'sunset_minutes')])
        self.assertEqual({key: value for key, value in stored.items() if key[1] in factor_builder.CALENDAR_CODES}, built)
        carried = {key: value for key, value in stored.items() if key[1] not in factor_builder.CALENDAR_CODES}
        self.assertEqual(carried, {key: value for key, value in source.items() if key[1] not in factor_builder.CALENDAR_CODES})
        self.assertEqual({key[1] for key in carried}, {'temperature_forecast_c', 'heat_alert', 'payday', 'is_open'})
        self.assertEqual(stored[('2025-06-21', 'temperature_forecast_c')], '33.1')

    def test_workspace_dates_match_the_fixed_demo_scenario(self):
        with self.factory() as db:
            self.organization(db)
            result = load_demo_data(db, ORG, '1')
            db.commit()
            context = workspace_context(db, ORG, '1')
        self.assertEqual((context['history_start'], context['history_end'], context['target_date']),
                         ('2024-01-01', '2025-12-31', '2026-01-01'))
        self.assertIn('2026-01-01', context['inventory_dates'])
        self.assertEqual((result['history_start'], result['history_end'], result['target_date']),
                         ('2024-01-01', '2025-12-31', '2026-01-01'))

    def test_second_load_is_refused_and_changes_nothing(self):
        with self.factory() as db:
            self.organization(db)
            load_demo_data(db, ORG, '1')
            db.commit()
            before = self.records(db)
            with self.assertRaises(DemoDataError) as caught:
                load_demo_data(db, ORG, '1')
            db.rollback()
            self.assertEqual((caught.exception.code, caught.exception.status), ('DEMO_DATA_NOT_EMPTY', 409))
            self.assertEqual(self.records(db), before)

    def test_real_only_organization_is_refused(self):
        with self.factory() as db:
            self.organization(db, data_policy='real_only')
            with self.assertRaises(DemoDataError) as caught:
                load_demo_data(db, ORG, '1')
            self.assertEqual((caught.exception.code, caught.exception.status), ('DEMO_DATA_SYNTHETIC_ONLY', 403))
            self.assertEqual(self.records(db), 1)

    def test_branch_needs_a_profile_with_a_known_city_and_must_exist(self):
        with self.factory() as db:
            self.organization(db, profile=False)
            with self.assertRaises(DemoDataError) as caught:
                load_demo_data(db, ORG, '1')
            self.assertEqual((caught.exception.code, caught.exception.status), ('BRANCH_CITY_REQUIRED', 422))
            with self.assertRaises(DemoDataError) as caught:
                load_demo_data(db, ORG, '9')
            self.assertEqual((caught.exception.code, caught.exception.status), ('BRANCH_NOT_FOUND', 404))
            db.add(BranchProfile(organization_id=ORG, branch_id='1', city_code='atlantis', updated_by='test'))
            db.flush()
            with self.assertRaises(DemoDataError) as caught:
                load_demo_data(db, ORG, '1')
            self.assertEqual(caught.exception.code, 'BRANCH_CITY_REQUIRED')
            self.assertEqual(self.records(db), 1)

    def test_source_branch_follows_establishment_type(self):
        self.assertEqual(demo_source_branch('restaurant'), '3')
        self.assertEqual(demo_source_branch('toikhana'), '3')
        self.assertEqual(demo_source_branch('cafe'), '2')
        self.assertEqual(demo_source_branch('canteen'), '1')
        self.assertEqual(demo_source_branch(None), '1')
        self.assertEqual(demo_source_branch('unknown'), '1')

    def test_route_registers_on_an_app(self):
        app = FastAPI()
        stub = lambda *args, **kwargs: None
        register_demo_routes(app, current=stub, get_db=stub, roles=stub, branch_access=stub, fail=stub, audit=stub)
        self.assertIn(('/api/v1/demo-data', {'POST'}), [(route.path, route.methods) for route in app.routes])


class DemoDataHttpTests(unittest.TestCase):
    """A self-registered cabinet loads the demo once and is ready for a forecast."""
    def setUp(self):
        Path('.cache').mkdir(exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir='.cache', prefix='demo-data-http-')
        self.addCleanup(temp.cleanup)
        environment = patch.dict(os.environ, {'ASBOLJAM_ENV': 'local'})
        environment.start();self.addCleanup(environment.stop)
        self.app = create_app('sqlite:///' + (Path(temp.name).resolve() / 'demo-http.sqlite').as_posix())
        self.addCleanup(self.app.state.engine.dispose)

    def test_registered_cabinet_loads_the_demo_once(self):
        client = TestClient(self.app);self.addCleanup(client.close)
        registered = client.post('/api/v1/register', headers=ORIGIN, json={
            'establishment_name': 'Астана тойханасы', 'establishment_type': 'toikhana', 'city_code': 'astana',
            'email': 'owner@toikhana.test', 'password': 'Demo-data-fixture-2026!', 'accept_test_mode': True})
        self.assertEqual(registered.status_code, 200, registered.text)
        client.headers.update({**ORIGIN, 'X-CSRF-Token': registered.json()['csrf_token']})
        self.assertEqual(client.post('/api/v1/demo-data', json={'branch_id': '1', 'extra': 1}).status_code, 422)
        loaded = client.post('/api/v1/demo-data', json={'branch_id': '1'})
        self.assertEqual(loaded.status_code, 200, loaded.text)
        self.assertEqual((loaded.json()['source_branch'], loaded.json()['city_code']), ('3', 'astana'))
        context = client.get('/api/v1/settings', params={'branch_id': '1'}).json()['data_context']
        self.assertEqual((context['history_start'], context['history_end'], context['target_date']), ('2024-01-01', '2025-12-31', '2026-01-01'))
        self.assertIn('2026-01-01', context['inventory_dates'])
        again = client.post('/api/v1/demo-data', json={'branch_id': '1'})
        self.assertEqual((again.status_code, again.json()['detail']['code']), (409, 'DEMO_DATA_NOT_EMPTY'))
        with self.app.state.sessions() as db:
            organization = db.scalar(select(Organization.id).where(Organization.provenance == 'self_registration'))
            events = [row.action for row in db.scalars(select(Audit).where(Audit.organization_id == organization))]
        self.assertEqual(events.count('demo_data.loaded'), 1)

    def test_only_an_admin_of_a_synthetic_cabinet_may_load(self):
        seed_demo.seed(self.app.state.sessions, 'Demo-data-fixture-2026!', dataset='kz')
        with self.app.state.sessions() as db:
            db.add(User(id='manager-demo', organization_id='demo', email='manager@demo.test',
                        password_hash=seed_demo.password_hash('Demo-data-fixture-2026!'), role='manager', branch_ids=['1']))
            db.commit()
        client = TestClient(self.app);self.addCleanup(client.close)
        for email, status, code in (('manager@demo.test', 403, None), ('admin@asboljam.local', 409, 'DEMO_DATA_NOT_EMPTY')):
            login = client.post('/api/v1/session/login', json={'email': email, 'password': 'Demo-data-fixture-2026!'}, headers=ORIGIN)
            client.headers.update({**ORIGIN, 'X-CSRF-Token': login.json()['csrf_token']})
            response = client.post('/api/v1/demo-data', json={'branch_id': '1'})
            self.assertEqual(response.status_code, status, response.text)
            if code:
                self.assertEqual(response.json()['detail']['code'], code)


if __name__ == '__main__':
    unittest.main()
