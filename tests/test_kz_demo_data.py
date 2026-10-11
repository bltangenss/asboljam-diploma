"""Kazakhstan SYNTHETIC demo dataset: reproducible, importable and faithful to the RK calendar."""
import contextlib
import csv
from datetime import date
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import func, select

from apps.api import engine
from apps.api.db import Record, make_engine, migrate, sessions
from scripts import generate_kz_demo, seed_demo

ROOT = Path(__file__).resolve().parents[1]
KZ = ROOT / 'data' / 'kz'
OPERATIONAL = ('branches', 'meals', 'ingredients', 'recipes', 'suppliers', 'supplier_offers',
               'calendar', 'daily_sales', 'inventory_lots')
PASSWORD = 'Synthetic-kz-fixture-2026!'
# Official RK days off 2024-2025 (holidays and transferred days off), kept separate from
# the generator so a change there cannot silently redefine the published calendar.
OFFICIAL_DAYS_OFF = {
    '2024-01-01', '2024-01-02', '2024-01-07', '2024-03-08', '2024-03-21', '2024-03-22', '2024-03-23',
    '2024-03-25', '2024-05-01', '2024-05-07', '2024-05-08', '2024-05-09', '2024-06-16', '2024-07-06',
    '2024-07-08', '2024-08-30', '2024-10-25', '2024-12-16',
    '2025-01-01', '2025-01-02', '2025-01-03', '2025-01-07', '2025-03-08', '2025-03-10', '2025-03-21',
    '2025-03-22', '2025-03-23', '2025-03-24', '2025-03-25', '2025-05-01', '2025-05-07', '2025-05-09',
    '2025-06-06', '2025-07-06', '2025-07-07', '2025-08-30', '2025-09-01', '2025-10-25', '2025-10-27',
    '2025-12-16',
}
WORKING_WEEKENDS = {'2024-05-04', '2025-01-05'}


def rows(name, directory=KZ):
    with (directory / name).open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


class KazakhstanDemoDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.generated = Path(cls.temp.name) / 'kz'
        generate_kz_demo.generate(cls.generated, Path(cls.temp.name) / 'oracle.csv')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_generator_reproduces_the_committed_files_exactly(self):
        committed = sorted(path.name for path in KZ.iterdir() if path.suffix in {'.csv', '.json'})
        self.assertEqual(committed, sorted(path.name for path in self.generated.iterdir()))
        for name in committed:
            with self.subTest(file=name):
                self.assertEqual((KZ / name).read_bytes(), (self.generated / name).read_bytes())

    def test_dates_identifiers_units_and_origin_follow_the_demo_contract(self):
        sales = rows('daily_sales.csv')
        days = {row['date'] for row in sales}
        self.assertEqual((min(days), max(days), len(days)), ('2024-01-01', '2025-12-31', 731))
        meals = {row['meal_id'] for row in rows('meals.csv')}
        branches = {row['branch_id'] for row in rows('branches.csv')}
        # A complete daily grid: a missing day would be refused, never read as zero.
        self.assertEqual(len({(row['date'], row['branch_id'], row['meal_id']) for row in sales}),
                         len(days) * len(meals) * len(branches))
        self.assertEqual(len(sales), len(days) * len(meals) * len(branches))
        for row in sales:
            self.assertLessEqual(int(row['units_sold']), int(row['available_portions']))
            if row['is_open'] == '0':
                self.assertEqual((row['units_sold'], row['available_portions'], row['promo']), ('0', '0', '0'))
        ingredients = {row['ingredient_id']: row for row in rows('ingredients.csv')}
        self.assertEqual({row['unit'] for row in ingredients.values()}, {'kg', 'L'})
        lots = rows('inventory_lots.csv')
        self.assertEqual({row['snapshot_date'] for row in lots}, {'2026-01-01'})
        self.assertTrue(all(row['unit'] == ingredients[row['ingredient_id']]['unit'] for row in lots))
        self.assertTrue(any(row['expiry_date'] < '2026-01-01' for row in lots), 'demo shows an expired lot')
        recipes = rows('recipes.csv')
        self.assertEqual({row['meal_id'] for row in recipes}, meals)
        self.assertLessEqual({row['ingredient_id'] for row in recipes}, set(ingredients))
        offers = rows('supplier_offers.csv')
        self.assertEqual({row['ingredient_id'] for row in offers if row['lead_time_days'] == '0'}, set(ingredients))
        self.assertTrue(any(row['lead_time_days'] != '0' for row in offers), 'demo shows a lead-time exclusion')
        for name in OPERATIONAL:
            with self.subTest(file=name):
                content = rows(name + '.csv')
                self.assertEqual({row['data_origin'] for row in content}, {'SYNTHETIC'})
                self.assertFalse({'latent_demand_ORACLE_ONLY', 'demand_multiplier', 'base_daily_demand'}
                                 & set(content[0]))

    def test_calendar_marks_exactly_the_official_rk_days_off(self):
        calendar = rows('calendar.csv')
        for branch in sorted({row['branch_id'] for row in calendar}):
            with self.subTest(branch=branch):
                self.assertEqual({row['date'] for row in calendar
                                  if row['branch_id'] == branch and row['synthetic_event'] == '1'}, OFFICIAL_DAYS_OFF)
        self.assertTrue(all(date.fromisoformat(row['date']).weekday() == int(row['weekday']) for row in calendar))
        reference = rows('reference_rk_days_off.csv')
        self.assertEqual({row['date'] for row in reference if row['kind'] != 'working_day'}, OFFICIAL_DAYS_OFF)
        self.assertEqual({row['date'] for row in reference if row['kind'] == 'working_day'}, WORKING_WEEKENDS)
        self.assertTrue(all(row['basis'] and row['name_kk'] and row['name_ru'] for row in reference))

    def test_observed_sales_are_latent_demand_censored_by_prepared_portions(self):
        latent = {(row['date'], row['branch_id'], row['meal_id']): int(row['latent_demand_ORACLE_ONLY'])
                  for row in rows('oracle.csv', Path(self.temp.name))}
        stockouts = 0
        for row in rows('daily_sales.csv'):
            demand, available = latent[(row['date'], row['branch_id'], row['meal_id'])], int(row['available_portions'])
            self.assertEqual(int(row['units_sold']), min(demand, available))
            self.assertEqual(row['stockout_flag'] == '1', demand > available)
            stockouts += demand > available
        self.assertGreater(stockouts, 0)

    def test_seed_imports_every_file_and_supports_forecast_and_procurement(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'ASBOLJAM_ENV': 'local'}):
            database = make_engine('sqlite:///' + (Path(directory) / 'kz.sqlite').as_posix())
            try:
                migrate(database)
                factory = sessions(database)
                self.assertIsNone(seed_demo.stored_dataset(factory))
                self.assertTrue(seed_demo.seed(factory, PASSWORD, dataset='kz'))
                self.assertEqual(seed_demo.stored_dataset(factory), 'kz')
                with factory() as db:
                    counts = dict(db.execute(select(Record.kind, func.count()).where(Record.organization_id == 'demo')
                                             .group_by(Record.kind)).all())
                    stored = {kind: [record.data for record in db.scalars(select(Record).where(
                        Record.organization_id == 'demo', Record.kind == kind))] for kind in OPERATIONAL}
            finally:
                database.dispose()
        self.assertEqual(counts, {kind: len(rows(kind + '.csv')) for kind in OPERATIONAL})
        forecast = engine.forecast(stored['daily_sales'], '1', '2025-12-31', 'hist_gradient_boosting')
        self.assertEqual(forecast['target_date'], '2026-01-01')
        self.assertEqual(len(forecast['predictions']), len(stored['meals']))
        plan = engine.procurement(forecast, stored['ingredients'], stored['recipes'], stored['inventory_lots'],
                                  stored['supplier_offers'], stored['suppliers'], '1', '2026-01-01', '150000')
        self.assertTrue(plan['constraints_valid'])
        self.assertEqual((plan['solver_status'], plan['shortage_count']), ('optimal', 0))
        self.assertEqual(plan['expired_lot_ids'], ['B1-I13-X1'])
        self.assertIn('lead_time', {item['reason'] for item in plan['excluded_offers']})

    def test_seed_cli_rejects_an_unknown_dataset_before_opening_a_database(self):
        with patch.dict(os.environ, {'DEMO_DATASET': 'unknown'}), patch('sys.argv', ['seed_demo.py']), \
                patch.object(seed_demo, 'make_engine') as make, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                seed_demo.main()
        self.assertEqual(raised.exception.code, 2)
        make.assert_not_called()


if __name__ == '__main__':
    unittest.main()
