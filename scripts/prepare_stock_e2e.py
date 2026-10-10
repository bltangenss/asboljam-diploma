"""Create a NEW ignored SQLite and artificial SYNTHETIC browser stock fixture.

Never opens the application's configured/default database. Prints no credentials.
The immutable demo sales cutoff stays 2025-12-31; operational journal movements
and a separately counted next-day fixture do not extend forecast sales history.
"""
import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import secrets
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apps.api.db import make_engine, migrate, sessions, User
from apps.api.importing import insert_rows, validate_rows
from apps.api.tenants import bootstrap_tenant


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, help='New SQLite path strictly under .cache')
    args = parser.parse_args()
    path = Path(args.database).resolve()
    if not path.is_relative_to((ROOT / '.cache').resolve()) or path.suffix != '.sqlite' or path.exists():
        raise SystemExit('Require a new .sqlite file under this workspace .cache; existing stores are never changed.')
    path.parent.mkdir(parents=True, exist_ok=True)
    # Reserve the filename exclusively before SQLite opens it.
    with path.open('x'):
        pass
    engine = make_engine('sqlite:///' + path.as_posix()); migrate(engine)
    factory = sessions(engine)
    organization_id = 'stock-browser-' + uuid.uuid4().hex[:12]
    email, password = organization_id + '@fixture.invalid', secrets.token_urlsafe(24)
    branch, meal, ingredient, lot = 'stock-test-branch', 'stock-test-meal', 'stock-test-ingredient', 'stock-test-lot'
    cutoff = date(2025, 12, 31)
    data = {
        'branches': [dict(branch_id=branch, branch_name='SYNTHETIC stock browser fixture')],
        'meals': [dict(meal_id=meal, meal_name='Artificial stock meal', base_price_kzt='1500')],
        'ingredients': [dict(ingredient_id=ingredient, ingredient_name='Artificial stock ingredient', unit='kg', reference_cost_kzt='1000', shelf_life_days=7, yield_factor='0.8', storage_capacity='100')],
        'recipes': [dict(meal_id=meal, ingredient_id=ingredient, net_qty_per_portion='0.08', recipe_version='legacy_fixture')],
        'suppliers': [dict(supplier_id='stock-test-supplier', supplier_name='Artificial supplier', lead_time_days=0)],
        'supplier_offers': [dict(supplier_id='stock-test-supplier', ingredient_id=ingredient, pack_qty='1', unit_cost_kzt='1000', min_packs=1, max_packs=100, lead_time_days=0)],
        'calendar': [dict(date='2026-01-01', branch_id=branch, weekday=3, temperature_forecast_c='10', synthetic_event=0, is_open=1)],
        'daily_sales': [dict(date=(cutoff-timedelta(days=83-index)).isoformat(), branch_id=branch, meal_id=meal, units_sold=20+index%7, available_portions=50, stockout_flag=0, is_open=1, promo=0, price_kzt='1500') for index in range(84)],
        'inventory_lots': [dict(branch_id=branch, ingredient_id=ingredient, lot_id=lot, snapshot_date=day, expiry_date='2026-01-06', on_hand_qty=qty, unit='kg') for day, qty in [('2026-01-01','10'),('2026-01-02','12')]],
    }
    data = {kind:[dict(row, data_origin='SYNTHETIC') for row in rows] for kind,rows in data.items()}
    with factory.begin() as db:
        created = bootstrap_tenant(db, organization_id=organization_id, name='ARTIFICIAL SYNTHETIC stock browser fixture',
            timezone='Asia/Qyzylorda', data_policy='synthetic_only', email=email, password=password,
            operator_id='stock_browser_fixture', reason='Isolated artificial browser verification, not business evidence')
        for kind, rows in data.items():
            errors = validate_rows(db, organization_id, kind, rows)
            if errors:
                raise ValueError(f'Artificial fixture validation failed for {kind}: {errors}')
            insert_rows(db, organization_id, kind, rows); db.flush()
        db.get(User, created['admin_user_id']).branch_ids = [branch]
    engine.dispose()
    output = ROOT / '.cache' / 'stock-e2e-login.json'
    output.write_text(json.dumps(dict(database=str(path), email=email, password=password, organization_id=organization_id,
        branch_id=branch, meal_id=meal, ingredient_id=ingredient, lot_id=lot), ensure_ascii=False), encoding='utf-8')
    print('New isolated SYNTHETIC stock fixture prepared; credentials remain in ignored .cache/stock-e2e-login.json.')


if __name__ == '__main__':
    main()
