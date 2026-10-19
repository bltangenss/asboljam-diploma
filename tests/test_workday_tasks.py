"""Workday tasks are current conditions, not duplicate events or hidden approvals."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from apps.api.db import DayClosure, NotificationReceipt, Organization, Plan, Record, make_engine
from apps.api.importing import insert_rows, natural_key
from apps.api.migrations import migrate
from apps.api.workday_tasks import workday_tasks


class WorkdayTaskTests(unittest.TestCase):
    def setUp(self):
        Path('.cache').mkdir(exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir='.cache', prefix='workday-task-')
        self.addCleanup(temp.cleanup)
        self.engine = make_engine('sqlite:///' + (Path(temp.name).resolve() / 'tasks.sqlite').as_posix())
        self.addCleanup(self.engine.dispose)
        migrate(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.user = SimpleNamespace(id='manager', organization_id='A', branch_ids=['1'], role='manager')
        with self.sessions.begin() as db:
            db.add(Organization(id='A', name='Бауырдак', timezone='Asia/Qyzylorda', currency='KZT',
                                status='active', data_policy='synthetic_only', provenance='fixture'))
            insert_rows(db, 'A', 'branches', [{'branch_id': '1', 'branch_name': 'Бауырдак', 'data_origin': 'SYNTHETIC'}])
            insert_rows(db, 'A', 'meals', [{'meal_id': '1', 'meal_name': 'Плов', 'base_price_kzt': '1200', 'data_origin': 'SYNTHETIC'}])

    def read(self, user=None):
        with self.sessions() as db:
            return workday_tasks(db, user or self.user, '1')

    def closed(self, *, opened=1, entered_price='1200.00'):
        line = dict(meal_id='1', state='sold', units_sold=0, available_portions=0,
                    stockout_flag=0, promo=0, price_kzt=entered_price)
        with self.sessions.begin() as db:
            db.add(DayClosure(organization_id='A', branch_id='1', business_date='2026-01-01', status='closed',
                version=2, is_open=opened, lines=[line], data_origin='SYNTHETIC', created_by='manager', updated_by='manager'))
            insert_rows(db, 'A', 'daily_sales', [dict(date='2026-01-01', branch_id='1', meal_id='1',
                units_sold=0, available_portions=0, stockout_flag=0, promo=0, price_kzt='1200', is_open=opened, data_origin='SYNTHETIC')])

    def test_get_does_not_write_and_refresh_has_stable_keys_on_fixed_demo_day(self):
        first, second = self.read(), self.read()
        self.assertEqual(first, second)
        self.assertEqual(first['business_date'], '2026-01-01')
        self.assertTrue(all(row['expires_at'] is None for row in first['items']))
        self.assertEqual(len({row['id'] for row in first['items']}), len(first['items']))
        self.assertEqual(first['readiness']['sales']['status'], 'unconfirmed')
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(NotificationReceipt)), 0)

    def test_equal_decimal_strings_do_not_reopen_an_explicit_zero(self):
        self.closed()
        result = self.read()
        self.assertEqual(result['readiness']['closure']['status'], 'closed')
        self.assertEqual(result['readiness']['sales']['status'], 'complete')
        self.assertNotIn('DAY_NEEDS_CLOSE', {row['code'] for row in result['items']})

    def test_new_menu_price_does_not_change_closed_day_zero_sales(self):
        self.closed(opened=0)
        with self.sessions.begin() as db:
            record = db.scalar(select(Record).where(Record.kind == 'meals'))
            record.data = {**record.data, 'base_price_kzt': '1500'}
        self.assertEqual(self.read()['readiness']['closure']['status'], 'closed')

    def test_external_fact_correction_returns_a_new_unviewed_warning(self):
        self.closed()
        with self.sessions.begin() as db:
            record = db.scalar(select(Record).where(Record.kind == 'daily_sales'))
            record.data = {**record.data, 'units_sold': 1, 'available_portions': 1}
        result = self.read()
        self.assertEqual(result['readiness']['closure']['status'], 'changed')
        self.assertTrue(any(row['code'] == 'DAY_NEEDS_CLOSE' for row in result['items']))

    def test_new_approved_variant_does_not_hide_earlier_pending_purchase(self):
        with self.sessions.begin() as db:
            for identity, state in [('first', 'ready'), ('second', 'ready'), ('third', 'approved')]:
                db.add(Plan(id=identity, organization_id='A', branch_id='1', forecast_id='fixture', version=1,
                    status=state, result={'target_date': '2026-01-01', 'shortage_count': 1}, created_at='2026-10-19T10:00:00Z'))
        tasks = self.read()['items']
        self.assertEqual({row['details']['plan_id'] for row in tasks if row['code'] == 'PROCUREMENT_NEEDS_DECISION'}, {'first', 'second'})
        self.assertEqual(len([row for row in tasks if row['code'] == 'PROCUREMENT_SHORTAGE']), 3)

    def test_view_receipt_is_personal_and_disappears_when_condition_resolves(self):
        task = next(row for row in self.read()['items'] if row['code'] == 'DAY_NEEDS_CLOSE')
        with self.sessions.begin() as db:
            db.add(NotificationReceipt(id='receipt', organization_id='A', branch_id='1', user_id='manager', notification_key=task['id']))
        self.assertTrue(next(row for row in self.read()['items'] if row['id'] == task['id'])['viewed'])
        other = SimpleNamespace(**{**vars(self.user), 'id': 'other'})
        self.assertFalse(next(row for row in self.read(other)['items'] if row['id'] == task['id'])['viewed'])
        self.closed()
        self.assertNotIn(task['id'], {row['id'] for row in self.read()['items']})

    def test_missing_inventory_and_recipes_are_unknown_not_zero_or_ready(self):
        result = self.read()['readiness']
        self.assertEqual(result['recipes']['status'], 'incomplete')
        self.assertEqual(result['inventory']['status'], 'incomplete')
        self.assertEqual(result['history']['missing_meal_ids'], ['1'])
