"""Closing a business day: drafts keep unknowns, closing records sales once and atomically."""
from datetime import date
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from apps.api import day_close
from apps.api.db import Audit, DayClosure, Record, RecordRevision, User
from apps.api.importing import rows_for
from apps.api.lineage import capture_lineage, input_freshness
from apps.api.main import create_app
from scripts import seed_demo

PASSWORD = 'Day-close-fixture-2026!'
ORIGIN = {'Origin': 'http://localhost:3000'}
DAY = '2026-01-01'


class DayCloseTests(unittest.TestCase):
    def setUp(self):
        Path('.cache').mkdir(exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir='.cache', prefix='day-close-tests-')
        self.addCleanup(temp.cleanup)
        environment = patch.dict(os.environ, {'ASBOLJAM_ENV': 'local'})
        environment.start();self.addCleanup(environment.stop)
        self.app = create_app('sqlite:///' + (Path(temp.name).resolve() / 'day-close.sqlite').as_posix())
        self.addCleanup(self.app.state.engine.dispose)
        seed_demo.seed(self.app.state.sessions, PASSWORD, dataset='kz')
        with self.app.state.sessions() as db:
            for email, role, branches in (('manager@day.test', 'manager', ['1']), ('analyst@day.test', 'analyst', ['1']),
                                          ('store@day.test', 'warehouse', ['1'])):
                db.add(User(id=email, organization_id='demo', email=email, password_hash=seed_demo.password_hash(PASSWORD),
                            role=role, branch_ids=branches))
            db.commit()
            self.menu = sorted(rows_for(db, 'demo', 'meals'), key=lambda row: row['meal_id'])

    def client(self, email='manager@day.test'):
        client = TestClient(self.app);self.addCleanup(client.close)
        login = client.post('/api/v1/session/login', json={'email': email, 'password': PASSWORD}, headers=ORIGIN)
        self.assertEqual(login.status_code, 200, login.text)
        client.headers.update({**ORIGIN, 'X-CSRF-Token': login.json()['csrf_token']})
        return client

    def send(self, client, method, path, body, key=None):
        return client.request(method, path, json=body, headers={'Idempotency-Key': key or uuid.uuid4().hex})

    def full_lines(self, units=lambda index: 10 + index, skip=('12',)):
        lines = []
        for index, meal in enumerate(self.menu):
            if meal['meal_id'] in skip:
                lines.append({'meal_id': meal['meal_id'], 'state': 'not_offered'})
            else:
                lines.append({'meal_id': meal['meal_id'], 'state': 'sold', 'units_sold': units(index), 'available_portions': units(index) + 5,
                              'stockout_flag': 0, 'promo': 0, 'price_kzt': meal['base_price_kzt']})
        return lines

    def sales(self, day=DAY):
        with self.app.state.sessions() as db:
            return {row['meal_id']: row for row in rows_for(db, 'demo', 'daily_sales', '1') if row['date'] == day}

    def draft(self, client, lines, version=0, is_open=1, day=DAY, key=None):
        return self.send(client, 'PUT', '/api/v1/day-close', {'branch_id': '1', 'business_date': day, 'expected_version': version,
                                                             'is_open': is_open, 'lines': lines}, key)

    def test_draft_keeps_unknown_values_and_zero_apart_with_versions_and_replays(self):
        manager = self.client()
        opened = manager.get('/api/v1/day-close', params={'branch_id': '1'}).json()
        # The synthetic scenario day, never the computer's date.
        self.assertEqual((opened['business_date'], opened['status'], opened['version'], opened['data_origin']), (DAY, 'none', 0, 'SYNTHETIC'))
        self.assertEqual(opened['completeness']['counts']['unmarked'], len(self.menu))
        self.assertIsNotNone(opened['meals'][0]['reference']['previous_day_units_sold'])
        self.assertIsNone(opened['meals'][0]['entry'])
        lines = [{'meal_id': '1', 'state': 'sold', 'units_sold': 0, 'available_portions': 4, 'stockout_flag': 0, 'promo': 0, 'price_kzt': '2600'},
                 {'meal_id': '2', 'state': 'sold', 'units_sold': 5}]
        key = uuid.uuid4().hex
        saved = self.draft(manager, lines, key=key)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual((saved.json()['status'], saved.json()['version']), ('draft', 1))
        entries = {meal['meal_id']: meal['entry'] for meal in saved.json()['meals']}
        self.assertEqual(entries['1']['units_sold'], 0)
        self.assertIsNone(entries['2']['available_portions'])
        missing = {item['meal_id']: item['fields'] for item in saved.json()['completeness']['missing']}
        self.assertEqual(missing['2'], ['available_portions', 'stockout_flag', 'promo', 'price_kzt'])
        self.assertEqual(self.draft(manager, lines, key=key).json(), saved.json())
        self.assertEqual(self.draft(manager, lines[:1], key=key).json()['detail']['code'], 'IDEMPOTENCY_CONFLICT')
        stale = self.draft(manager, lines)
        self.assertEqual((stale.status_code, stale.json()['detail']['code']), (409, 'STALE_VERSION'))
        self.assertEqual(self.draft(manager, lines, version=1).json()['version'], 2)
        self.assertEqual(self.sales(), {})

    def test_an_incomplete_day_is_refused_and_writes_nothing(self):
        manager = self.client()
        version = self.draft(manager, self.full_lines()[:5]).json()['version']
        refused = self.send(manager, 'POST', '/api/v1/day-close/close', {'branch_id': '1', 'business_date': DAY, 'expected_version': version})
        self.assertEqual((refused.status_code, refused.json()['detail']['code']), (422, 'DAY_INCOMPLETE'))
        self.assertEqual(len(refused.json()['detail']['details']['unmarked']), len(self.menu) - 5)
        self.assertEqual(self.sales(), {})
        unknown = self.draft(manager, self.full_lines(), version=version, is_open=None).json()
        self.assertFalse(unknown['completeness']['is_open_known'])

    def test_a_complete_day_closes_once_and_records_exactly_the_entered_sales(self):
        manager = self.client()
        version = self.draft(manager, self.full_lines()).json()['version']
        key = uuid.uuid4().hex
        body = {'branch_id': '1', 'business_date': DAY, 'expected_version': version}
        closed = self.send(manager, 'POST', '/api/v1/day-close/close', body, key)
        self.assertEqual(closed.status_code, 200, closed.text)
        self.assertEqual((closed.json()['status'], closed.json()['version'], closed.json()['closed_by']), ('closed', 2, 'manager@day.test'))
        self.assertEqual(closed.json()['recorded_counts'], {'inserted': 11, 'updated': 0, 'unchanged': 0})
        stored = self.sales()
        self.assertNotIn('12', stored)  # not offered: no sales row, not a zero
        self.assertEqual((stored['1']['units_sold'], stored['1']['available_portions'], stored['1']['data_origin']), (10, 15, 'SYNTHETIC'))
        self.assertEqual(self.send(manager, 'POST', '/api/v1/day-close/close', body, key).json(), closed.json())
        self.assertEqual(len(self.sales()), 11)
        again = self.send(manager, 'POST', '/api/v1/day-close/close', body)
        self.assertEqual((again.status_code, again.json()['detail']['code']), (409, 'STALE_VERSION'))
        edit = self.draft(manager, self.full_lines(), version=2)
        self.assertEqual((edit.status_code, edit.json()['detail']['code']), (409, 'DAY_CLOSED'))
        with self.app.state.sessions() as db:
            actions = [row.action for row in db.scalars(select(Audit).where(Audit.branch_id == '1').order_by(Audit.created_at))]
        self.assertEqual(actions.count('day_close.closed'), 1)
        self.assertEqual(actions.count('import.committed'), 1)

    def test_a_failure_inside_closing_leaves_the_day_open_and_records_nothing(self):
        manager = self.client()
        version = self.draft(manager, self.full_lines()).json()['version']
        real = day_close.commit_import
        def broken(*args, **kwargs):
            real(*args, **kwargs)
            raise RuntimeError('Controlled failure after the sales were staged')
        with patch('apps.api.day_close.commit_import', side_effect=broken), self.assertRaises(RuntimeError):
            self.send(manager, 'POST', '/api/v1/day-close/close', {'branch_id': '1', 'business_date': DAY, 'expected_version': version})
        self.assertEqual(self.sales(), {})
        with self.app.state.sessions() as db:
            closure = db.get(DayClosure, ('demo', '1', DAY))
            self.assertEqual((closure.status, closure.version), ('draft', version))

    def test_a_closed_establishment_records_confirmed_zero_rows(self):
        manager = self.client()
        version = self.draft(manager, [], is_open=0).json()['version']
        closed = self.send(manager, 'POST', '/api/v1/day-close/close', {'branch_id': '1', 'business_date': DAY, 'expected_version': version})
        self.assertEqual(closed.status_code, 200, closed.text)
        stored = self.sales()
        self.assertEqual(len(stored), len(self.menu))
        self.assertTrue(all(row['is_open'] == 0 and row['units_sold'] == 0 and row['available_portions'] == 0 for row in stored.values()))
        self.assertEqual(stored['1']['price_kzt'], self.menu[0]['base_price_kzt'])

    def test_different_stored_values_conflict_until_a_reason_corrects_them(self):
        past = '2025-12-31'
        recorded = self.sales(past)
        with self.app.state.sessions() as db:
            lineage = capture_lineage(db, 'demo', [{'kind': 'daily_sales', 'rows': rows_for(db, 'demo', 'daily_sales', '1'),
                                                   'branch_id': '1', 'date_lte': past}])
        lines = [{'meal_id': meal_id, 'state': 'sold', **{field: row[field] for field in day_close.SALE_FIELDS}}
                 for meal_id, row in recorded.items()]
        changed = next(line for line in lines if line['units_sold'] < line['available_portions'])
        changed['units_sold'] += 1
        manager = self.client()
        version = self.draft(manager, lines, day=past).json()['version']
        body = {'branch_id': '1', 'business_date': past, 'expected_version': version}
        conflict = self.send(manager, 'POST', '/api/v1/day-close/close', body)
        self.assertEqual((conflict.status_code, conflict.json()['detail']['code']), (409, 'DAY_CONFLICT'))
        self.assertEqual([item['meal_id'] for item in conflict.json()['detail']['details']], [changed['meal_id']])
        self.assertEqual(self.sales(past), recorded)
        corrected = self.send(manager, 'POST', '/api/v1/day-close/close', {**body, 'correction_reason': 'Кассадан қайта санадық'})
        self.assertEqual(corrected.status_code, 200, corrected.text)
        self.assertEqual(corrected.json()['recorded_counts'], {'inserted': 0, 'updated': 1, 'unchanged': len(recorded) - 1})
        self.assertEqual(self.sales(past)[changed['meal_id']]['units_sold'], changed['units_sold'])
        with self.app.state.sessions() as db:
            revision = db.scalar(select(RecordRevision).where(RecordRevision.kind == 'daily_sales', RecordRevision.reason.is_not(None)))
            self.assertEqual((revision.reason, revision.actor_id), ('Кассадан қайта санадық', 'manager@day.test'))
            # A corrected past fact makes calculations that read it stale.
            self.assertEqual(input_freshness(db, 'demo', lineage), 'changed')

    def test_identical_facts_do_not_double_and_the_forecast_day_keeps_older_calculations_fresh(self):
        past = '2025-12-31'
        recorded = self.sales(past)
        lines = [{'meal_id': meal_id, 'state': 'sold', **{field: row[field] for field in day_close.SALE_FIELDS}} for meal_id, row in recorded.items()]
        manager = self.client()
        version = self.draft(manager, lines, day=past).json()['version']
        closed = self.send(manager, 'POST', '/api/v1/day-close/close', {'branch_id': '1', 'business_date': past, 'expected_version': version})
        self.assertEqual(closed.json()['recorded_counts'], {'inserted': 0, 'updated': 0, 'unchanged': len(recorded)})
        self.assertEqual(self.sales(past), recorded)
        with self.app.state.sessions() as db:
            lineage = capture_lineage(db, 'demo', [{'kind': 'daily_sales', 'rows': rows_for(db, 'demo', 'daily_sales', '1'),
                                                   'branch_id': '1', 'date_lte': past}])
        version = self.draft(manager, self.full_lines()).json()['version']
        self.send(manager, 'POST', '/api/v1/day-close/close', {'branch_id': '1', 'business_date': DAY, 'expected_version': version})
        with self.app.state.sessions() as db:
            self.assertEqual(input_freshness(db, 'demo', lineage), 'unchanged')
            self.assertEqual(db.scalar(select(func.count()).select_from(Record).where(Record.kind == 'daily_sales', Record.branch_id == '1',
                                                                                     Record.natural_key.like('["2025-12-31",%'))), len(recorded))

    def test_reopening_needs_a_reason_and_a_later_change_is_a_recorded_correction(self):
        manager = self.client()
        version = self.draft(manager, self.full_lines()).json()['version']
        closed = self.send(manager, 'POST', '/api/v1/day-close/close', {'branch_id': '1', 'business_date': DAY, 'expected_version': version}).json()
        short = self.send(manager, 'POST', '/api/v1/day-close/reopen', {'branch_id': '1', 'business_date': DAY, 'expected_version': closed['version'], 'reason': 'x'})
        self.assertEqual(short.status_code, 422)
        reopened = self.send(manager, 'POST', '/api/v1/day-close/reopen', {'branch_id': '1', 'business_date': DAY,
                                                                          'expected_version': closed['version'], 'reason': 'Бешбармақ қате енгізілді'}).json()
        self.assertEqual((reopened['status'], reopened['version'], reopened['reason']), ('draft', 3, 'Бешбармақ қате енгізілді'))
        self.assertEqual(len(self.sales()), 11)  # reopening alone changes no recorded sales
        lines = self.full_lines(units=lambda index: 9 if index == 0 else 10 + index)
        version = self.draft(manager, lines, version=3).json()['version']
        body = {'branch_id': '1', 'business_date': DAY, 'expected_version': version}
        self.assertEqual(self.send(manager, 'POST', '/api/v1/day-close/close', body).json()['detail']['code'], 'DAY_CONFLICT')
        again = self.send(manager, 'POST', '/api/v1/day-close/close', {**body, 'correction_reason': 'Бешбармақ: 9 порция'})
        self.assertEqual(again.json()['recorded_counts'], {'inserted': 0, 'updated': 1, 'unchanged': 10})
        self.assertEqual(self.sales()['1']['units_sold'], 9)
        with self.app.state.sessions() as db:
            reasons = [row.details.get('reason') for row in db.scalars(select(Audit).where(Audit.action == 'day_close.reopened'))]
            revisions = db.scalars(select(RecordRevision).where(RecordRevision.natural_key == '["2026-01-01","1","1"]')
                                   .order_by(RecordRevision.revision)).all()
        self.assertEqual(reasons, ['Бешбармақ қате енгізілді'])
        self.assertEqual([(row.revision, row.reason) for row in revisions], [(1, None), (2, 'Бешбармақ: 9 порция')])

    def test_roles_branches_and_organizations_are_enforced(self):
        lines = self.full_lines()
        analyst = self.client('analyst@day.test')
        self.assertEqual(analyst.get('/api/v1/day-close', params={'branch_id': '1'}).status_code, 200)
        self.assertEqual(self.draft(analyst, lines).status_code, 403)
        self.assertEqual(self.client('store@day.test').get('/api/v1/day-close', params={'branch_id': '1'}).status_code, 403)
        manager = self.client()
        self.assertEqual(self.send(manager, 'PUT', '/api/v1/day-close', {'branch_id': '2', 'business_date': DAY, 'expected_version': 0,
                                                                         'is_open': 1, 'lines': []}).status_code, 403)
        self.draft(manager, lines)
        stranger = TestClient(self.app);self.addCleanup(stranger.close)
        registered = stranger.post('/api/v1/register', headers=ORIGIN, json={'establishment_name': 'Бөтен кафе', 'establishment_type': 'cafe',
                                   'city_code': 'almaty', 'email': 'owner@other.test', 'password': PASSWORD, 'accept_test_mode': True})
        stranger.headers.update({**ORIGIN, 'X-CSRF-Token': registered.json()['csrf_token']})
        own = stranger.get('/api/v1/day-close', params={'branch_id': '1'}).json()
        self.assertEqual((own['status'], own['meals']), ('none', []))  # another organization's draft stays invisible

    def test_lines_and_dates_are_validated_before_anything_is_saved(self):
        manager = self.client()
        cases = ([{'meal_id': 'missing', 'state': 'sold'}], [{'meal_id': '1', 'state': 'not_offered', 'units_sold': 3}],
                 [{'meal_id': '1', 'state': 'sold', 'stockout_time': '13:30'}], [{'meal_id': '1', 'state': 'sold', 'price_kzt': '-5'}],
                 [{'meal_id': '1', 'state': 'sold', 'stockout_flag': 1, 'stockout_time': '25:00'}])
        for lines in cases:
            response = self.draft(manager, lines)
            self.assertEqual((response.status_code, response.json()['detail']['code']), (422, 'DAY_LINES_INVALID'), lines)
        self.assertEqual(self.draft(manager, [{'meal_id': '1', 'units_sold': 1.5}]).status_code, 422)
        future = self.draft(manager, [], day='2026-01-02')
        self.assertEqual(future.json()['detail']['code'], 'BUSINESS_DATE_IN_FUTURE')
        with self.app.state.sessions() as db:
            self.assertIsNone(db.get(DayClosure, ('demo', '1', DAY)))

    def test_a_real_day_closes_only_after_it_has_ended(self):
        context = {'data_origin': 'REAL', 'timezone': 'Asia/Almaty'}
        with patch('apps.api.day_close.policy_context', return_value=context), \
                patch('apps.api.day_close.business_clock', return_value=(None, date(2026, 3, 10))):
            policy = day_close.day_policy(None, 'org')
            self.assertEqual((policy['editable_until'], policy['closable_until'], policy['default']),
                             (date(2026, 3, 10), date(2026, 3, 9), date(2026, 3, 9)))
            self.assertEqual(day_close.day_policy(None, 'org', {'2026-03-09'})['default'], date(2026, 3, 10))


if __name__ == '__main__':
    unittest.main()
