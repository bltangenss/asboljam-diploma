"""Create a NEW ignored SQLite and fully artificial browser stock fixture.

Never opens the application's configured/default database. Prints no credentials.
The immutable demo sales cutoff stays 2025-12-31; operational journal movements
and a separately counted next-day fixture do not extend forecast sales history.
An explicit --real-test creates generated REAL/TEST contract records in a new
organization only. It is never a real enterprise dataset or pilot attestation.
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
from apps.api.tenants import bootstrap_tenant, configure_real_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, help='New SQLite path strictly under .cache')
    parser.add_argument('--real-test', action='store_true', help='Generated REAL contract with visible TEST purpose; no enterprise records')
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
    cutoff = date(2026, 9, 1) if args.real_test else date(2025, 12, 31)
    # Two consecutive REAL test origins both need the API's 84-day history.
    history_days = 85 if args.real_test else 84
    baseline = cutoff if args.real_test else cutoff + timedelta(days=1)
    next_count = baseline + timedelta(days=1)
    expiry = baseline + timedelta(days=5)
    data_origin = 'REAL' if args.real_test else 'SYNTHETIC'
    source = dict(source_id='artificial-stock-browser', mapping_version='generated-test-v1') if args.real_test else None
    data = {
        'branches': [dict(branch_id=branch, branch_name=('REAL TEST' if args.real_test else 'SYNTHETIC') + ' artificial stock browser fixture')],
        'meals': [dict(meal_id=meal, meal_name='Artificial stock meal', base_price_kzt='1500')],
        'ingredients': [dict(ingredient_id=ingredient, ingredient_name='Artificial stock ingredient', unit='kg', reference_cost_kzt='1000', shelf_life_days=7, yield_factor='0.8', storage_capacity='100')],
        'recipes': [dict(meal_id=meal, ingredient_id=ingredient, net_qty_per_portion='0.08', recipe_version='legacy_fixture')],
        'suppliers': [dict(supplier_id='stock-test-supplier', supplier_name='Artificial supplier', lead_time_days=0)],
        'supplier_offers': [dict(supplier_id='stock-test-supplier', ingredient_id=ingredient, pack_qty='1', unit_cost_kzt='1000', min_packs=1, max_packs=100, lead_time_days=0)],
        'calendar': [dict(date=day.isoformat(), branch_id=branch, weekday=day.weekday(), temperature_forecast_c='10', synthetic_event=0, is_open=1) for day in ([baseline,next_count] if args.real_test else [baseline])],
        'daily_sales': [dict(date=(cutoff-timedelta(days=history_days-1-index)).isoformat(), branch_id=branch, meal_id=meal, units_sold=20+index%7, available_portions=50, stockout_flag=0, is_open=1, promo=0, price_kzt='1500') for index in range(history_days)],
        'inventory_lots': [dict(branch_id=branch, ingredient_id=ingredient, lot_id=lot, snapshot_date=day.isoformat(), expiry_date=expiry.isoformat(), on_hand_qty=qty, unit='kg') for day, qty in [(baseline,'10'),(next_count,'12')]],
    }
    data = {kind:[dict(row, data_origin=data_origin) for row in rows] for kind,rows in data.items()}
    with factory.begin() as db:
        created = bootstrap_tenant(db, organization_id=organization_id, name='ARTIFICIAL ' + ('REAL TEST' if args.real_test else 'SYNTHETIC') + ' stock browser fixture',
            timezone='Asia/Qyzylorda', data_policy='unconfigured' if args.real_test else 'synthetic_only', email=email, password=password,
            operator_id='stock_browser_fixture', reason='Isolated artificial browser verification, not business evidence')
        if args.real_test:
            configure_real_source(db, organization_id=organization_id, **source, branch_id=branch,
                authorization_reference='generated-test-fixture-only', purpose='test_fixture',
                operator_id='stock_browser_fixture', reason='Generated contract test only; no enterprise authorization or pilot claim')
        for kind, rows in data.items():
            errors = validate_rows(db, organization_id, kind, rows)
            if errors:
                raise ValueError(f'Artificial fixture validation failed for {kind}: {errors}')
            insert_rows(db, organization_id, kind, rows); db.flush()
        db.get(User, created['admin_user_id']).branch_ids = [branch]
    engine.dispose()
    output = ROOT / '.cache' / 'stock-e2e-login.json'
    output.write_text(json.dumps(dict(database=str(path), email=email, password=password, organization_id=organization_id,
        branch_id=branch, meal_id=meal, ingredient_id=ingredient, lot_id=lot, data_origin=data_origin,
        usage_mode='TEST' if args.real_test else 'DEMO', source=source, baseline_date=baseline.isoformat(),
        next_count_date=next_count.isoformat(), forecast_origin=cutoff.isoformat(), expiry_date=expiry.isoformat()), ensure_ascii=False), encoding='utf-8')
    print('New isolated ' + ('REAL/TEST artificial contract' if args.real_test else 'SYNTHETIC') + ' stock fixture prepared; credentials remain in ignored .cache/stock-e2e-login.json.')


if __name__ == '__main__':
    main()
