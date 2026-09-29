"""ARTIFICIAL contract-test data; never enterprise evidence or measured demand.

Rows deliberately exercise the REAL schema inside a source registered as
test_fixture / usage_mode TEST. Do not relabel the supplied SYNTHETIC dataset.
"""
import csv
from datetime import date, timedelta
import io

from apps.api.importing import SCHEMAS

SOURCE = {'source_id': 'artificial-contract-fixture', 'mapping_version': 'fixture-v1'}
BRANCH = 'test-branch'


def csv_text(kind, rows):
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=SCHEMAS[kind].split(), lineterminator='\n')
    writer.writeheader(); writer.writerows(rows)
    return output.getvalue()


def dataset(origin='2026-03-31'):
    day = date.fromisoformat(origin)
    target = (day + timedelta(days=1)).isoformat()
    data = {
        'branches': [dict(branch_id=BRANCH, branch_name='Artificial contract fixture')],
        'meals': [dict(meal_id='test-meal', meal_name='Artificial fixture meal', base_price_kzt='1500')],
        'ingredients': [dict(ingredient_id='test-ingredient', ingredient_name='Artificial fixture ingredient', unit='kg',
                             reference_cost_kzt='1000', shelf_life_days=7, yield_factor='0.8', storage_capacity='100')],
        'recipes': [dict(meal_id='test-meal', ingredient_id='test-ingredient', net_qty_per_portion='0.12', recipe_version='fixture-v1')],
        'suppliers': [dict(supplier_id='test-supplier', supplier_name='Artificial fixture supplier', lead_time_days=0)],
        'supplier_offers': [dict(supplier_id='test-supplier', ingredient_id='test-ingredient', pack_qty='1', unit_cost_kzt='1000', min_packs=1, max_packs=100, lead_time_days=0)],
        'calendar': [dict(date=target, branch_id=BRANCH, weekday=(day+timedelta(days=1)).weekday(), temperature_forecast_c='10', synthetic_event=0, is_open=1)],
        'daily_sales': [dict(date=(day-timedelta(days=83-index)).isoformat(), branch_id=BRANCH, meal_id='test-meal',
                             units_sold=20+index%7, available_portions=50, stockout_flag=0, is_open=1, promo=0, price_kzt='1500') for index in range(84)],
        'inventory_lots': [dict(branch_id=BRANCH, ingredient_id='test-ingredient', lot_id='test-lot', snapshot_date=target,
                               expiry_date=target, on_hand_qty='1', unit='kg')],
    }
    return {kind: [dict(row, data_origin='REAL') for row in rows] for kind, rows in data.items()}
