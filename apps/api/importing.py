"""Strict, allowlisted CSV parser. Generator fields are discarded at the boundary."""
import csv
import io
import json
import os
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from sqlalchemy import select
from .db import Record

PLAIN_NEGATIVE_NUMBER = re.compile(r'-\d+(\.\d+)?([eE][-+]?\d+)?')
SCHEMAS = {
    'branches': 'branch_id branch_name data_origin',
    'meals': 'meal_id meal_name base_price_kzt data_origin',
    'ingredients': 'ingredient_id ingredient_name unit reference_cost_kzt shelf_life_days yield_factor storage_capacity data_origin',
    'recipes': 'meal_id ingredient_id net_qty_per_portion recipe_version data_origin',
    'suppliers': 'supplier_id supplier_name lead_time_days data_origin',
    'supplier_offers': 'supplier_id ingredient_id pack_qty unit_cost_kzt min_packs max_packs lead_time_days data_origin',
    'calendar': 'date branch_id weekday temperature_forecast_c synthetic_event is_open data_origin',
    'daily_sales': 'date branch_id meal_id units_sold available_portions stockout_flag is_open promo price_kzt data_origin',
    'inventory_lots': 'branch_id ingredient_id lot_id snapshot_date expiry_date on_hand_qty unit data_origin',
}
KEYS = {
    'branches': ['branch_id'], 'meals': ['meal_id'], 'ingredients': ['ingredient_id'],
    'recipes': ['meal_id', 'ingredient_id', 'recipe_version'], 'suppliers': ['supplier_id'],
    'supplier_offers': ['supplier_id', 'ingredient_id'], 'calendar': ['date', 'branch_id'],
    'daily_sales': ['date', 'branch_id', 'meal_id'], 'inventory_lots': ['branch_id', 'ingredient_id', 'lot_id', 'snapshot_date'],
}
IGNORED = {'branches': {'demand_multiplier'}, 'meals': {'base_daily_demand'}}
INT_FIELDS = set('shelf_life_days lead_time_days min_packs max_packs weekday synthetic_event is_open units_sold available_portions stockout_flag promo'.split())
DECIMAL_FIELDS = set('base_price_kzt reference_cost_kzt yield_factor storage_capacity net_qty_per_portion pack_qty unit_cost_kzt temperature_forecast_c price_kzt on_hand_qty'.split())
FLAGS = {'synthetic_event','is_open','stockout_flag','promo'}
FK = {'branch_id': 'branches', 'meal_id': 'meals', 'ingredient_id': 'ingredients', 'supplier_id': 'suppliers'}
MAX_BYTES = int(os.environ.get('IMPORT_MAX_BYTES', 20 * 1024 * 1024))
MAX_ROWS = int(os.environ.get('IMPORT_MAX_ROWS', 250000))

def natural_key(kind, row):
    return json.dumps([str(row[x]) for x in KEYS[kind]], separators=(',', ':'))

def rows_for(db, org, kind, branch=None):
    # The data column only: same filter/index as before, without ORM identity overhead.
    query = select(Record.data).where(Record.organization_id == org, Record.kind == kind)
    if branch is not None:
        query = query.where(Record.branch_id == str(branch))
    return list(db.scalars(query))

def validate_rows(db, org, kind, rows, allowed_branches=None, *, allow_existing=False, report=None):
    """Return reference/scope errors; optional metadata distinguishes an unchecked tail."""
    errors = []
    report = report if report is not None else {}
    report.update(rows_checked=0, complete=False, stop_reason=None, errors_truncated=False)
    existing = set(db.scalars(select(Record.natural_key).where(Record.organization_id == org, Record.kind == kind)))
    references = {field: {r[field] for r in rows_for(db, org, target)} for field, target in FK.items()}
    ingredients = {r['ingredient_id']: r for r in rows_for(db, org, 'ingredients')}
    # Read once: one query per row made large recipe previews hold the connection for minutes.
    active_versions = {r['recipe_version'] for r in rows_for(db, org, 'recipes')} if kind == 'recipes' else set()
    seen = set()
    for index, row in enumerate(rows, 2):
        report['rows_checked'] += 1
        def err(field, code, message):
            errors.append({'row_number': index, 'field': field, 'code': code, 'message': message})
        key = natural_key(kind, row)
        if key in seen or (key in existing and not allow_existing):
            err(','.join(KEYS[kind]), 'DUPLICATE_KEY', 'Қайталанған кілт: импорт қабылданбайды.')
        seen.add(key)
        branch = row.get('branch_id')
        if allowed_branches is not None and branch is not None and branch not in allowed_branches:
            err('branch_id', 'BRANCH_FORBIDDEN', 'Бөлімшеге рұқсат жоқ.')
        for field, target in FK.items():
            if field in row and kind != target and row[field] not in references[field]:
                err(field, 'UNKNOWN_REFERENCE', 'Анықтамалық идентификатор табылмады.')
        if kind == 'inventory_lots' and row['ingredient_id'] in ingredients:
            if row['unit'] != ingredients[row['ingredient_id']]['unit']:
                err('unit', 'UNIT_MISMATCH', 'Ингредиент өлшем бірлігі сәйкес емес.')
        if kind == 'recipes':
            if active_versions and row['recipe_version'] not in active_versions:
                err('recipe_version', 'RECIPE_VERSION_CONFLICT', 'MVP бір белсенді рецепт нұсқасын қолдайды.')
        if len(errors) >= 500 and report['rows_checked'] < len(rows):
            report.update(stop_reason='error_limit', errors_truncated=True)
            break
    else:
        report['complete'] = True
    if kind == 'recipes' and len({r['recipe_version'] for r in rows}) > 1:
        errors.append({'row_number': 1, 'field': 'recipe_version', 'code': 'RECIPE_VERSION_CONFLICT', 'message': 'Бір файлда бір рецепт нұсқасы қажет.'})
    return errors

def parse_csv(kind, text, report=None, *, expected_origin='SYNTHETIC'):
    errors, rows = [], []
    report = report if report is not None else {}
    report.update(rows_seen=0, rows_checked=0, scan_complete=False, stop_reason=None, errors_truncated=False)
    if expected_origin not in {'SYNTHETIC', 'REAL'}:
        raise ValueError('Explicit supported origin is required')
    def err(index, field, code, message):
        errors.append({'row_number': index, 'field': field, 'code': code, 'message': message})
    if kind not in SCHEMAS:
        report['stop_reason'] = 'unsupported_kind'
        return [], [{'row_number': 1, 'field': 'kind', 'code': 'UNSUPPORTED_KIND', 'message': 'Рұқсат етілмеген файл түрі.'}]
    if len(text.encode('utf-8')) > MAX_BYTES:
        report['stop_reason'] = 'file_size_limit'
        return [], [{'row_number': 1, 'field': 'file', 'code': 'FILE_TOO_LARGE', 'message': 'Файл өлшемі шектен асты.'}]
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')), strict=True)
    required = set(SCHEMAS[kind].split())
    try:
        fields = reader.fieldnames or []
        ignored = IGNORED.get(kind, set()) if expected_origin == 'SYNTHETIC' else set()
        if len(fields) != len(set(fields)) or set(fields) - required - ignored or required - set(fields):
            report['stop_reason'] = 'invalid_header'
            return [], [{'row_number': 1, 'field': 'header', 'code': 'INVALID_COLUMNS', 'message': 'CSV бағандары схемаға сәйкес емес.', 'expected': SCHEMAS[kind].split()}]
        for index, raw in enumerate(reader, 2):
            report['rows_seen'] = index - 1
            if index > MAX_ROWS + 1:
                report['stop_reason'] = 'row_limit'
                err(index, 'file', 'TOO_MANY_ROWS', 'Жол саны шектен асты.'); break
            report['rows_checked'] += 1
            start_errors = len(errors)
            row = {}
            if None in raw:
                err(index, 'row', 'EXTRA_COLUMNS', 'Артық бағандар бар.')
                if len(errors) >= 500:
                    report.update(stop_reason='error_limit', errors_truncated=True)
                    break
                continue
            for field in required:
                value = (raw.get(field) or '').strip()
                if not value:
                    err(index, field, 'MISSING_VALUE', 'Міндетті мән жоқ.'); continue
                try:
                    if field in INT_FIELDS:
                        if not re.fullmatch(r'\d+', value):
                            raise ValueError()
                        value = int(value)
                        if value > 1000000000:
                            raise ValueError()
                        if field in FLAGS and value not in (0, 1):
                            raise ValueError()
                        if field == 'weekday' and not 0 <= value <= 6:
                            raise ValueError()
                    elif field in DECIMAL_FIELDS:
                        number = Decimal(value)
                        if not number.is_finite() or (number < 0 and field != 'temperature_forecast_c') or abs(number) > Decimal('1000000000000'):
                            raise ValueError()
                        # At most nine decimal places, as in stock quantities: an exponent such as
                        # 1E-999999999 would otherwise expand to a billion digits in calculations.
                        if number != number.quantize(Decimal('0.000000001')):
                            raise ValueError()
                        if field in {'yield_factor','pack_qty','net_qty_per_portion'} and number <= 0:
                            raise ValueError()
                        if field == 'yield_factor' and number > 1:
                            raise ValueError()
                        value = str(number)
                    elif field in {'date','snapshot_date','expiry_date'}:
                        if date.fromisoformat(value).isoformat() != value:
                            raise ValueError()
                    elif field.endswith('_id'):
                        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value):
                            raise ValueError()
                    elif field == 'unit' and value not in {'kg','L'}:
                        raise ValueError()
                    elif field == 'data_origin' and value != expected_origin:
                        raise ValueError()
                    elif len(value) > 255:
                        raise ValueError()
                    row[field] = value
                except (ValueError, InvalidOperation):
                    err(index, field, 'INVALID_VALUE', 'Мәннің түрі немесе ауқымы жарамсыз.')
            if len(errors) == start_errors:
                if kind == 'daily_sales':
                    if row['units_sold'] > row['available_portions']:
                        err(index, 'units_sold', 'SALES_EXCEED_AVAILABLE', 'Сатылым қолжетімді порциядан көп.')
                    if not row['is_open'] and row['units_sold']:
                        err(index, 'is_open', 'CLOSED_WITH_SALES', 'Жабық күнде сатылым бар.')
                if kind == 'supplier_offers' and row['min_packs'] > row['max_packs']:
                    err(index, 'min_packs', 'MOQ_EXCEEDS_MAX', 'Ең аз қаптама ең көп мәннен артық.')
                if kind == 'calendar' and date.fromisoformat(row['date']).weekday() != row['weekday']:
                    err(index, 'weekday', 'WEEKDAY_MISMATCH', 'Апта күні көрсетілген күнге сәйкес емес.')
                if kind == 'calendar' and expected_origin == 'REAL' and row['synthetic_event'] != 0:
                    err(index, 'synthetic_event', 'SYNTHETIC_FIELD_FORBIDDEN', 'REAL күнтізбесінде жасанды оқиға белгісіне рұқсат жоқ.')
                if len(natural_key(kind, row)) > 255:
                    err(index, 'key', 'KEY_TOO_LONG', 'Құрама кілт сақтау шегінен асты.')
                if len(errors) == start_errors:
                    rows.append(row)
            if len(errors) >= 500:
                report.update(stop_reason='error_limit', errors_truncated=True)
                break
        else:
            report['scan_complete'] = True
    except csv.Error:
        report['stop_reason'] = 'invalid_csv'
        err(max(1, reader.line_num), 'file', 'INVALID_CSV', 'CSV құрылымы жарамсыз.')
    if not rows and not errors:
        err(2, 'file', 'EMPTY_FILE', 'CSV бос.')
    return rows, errors

def insert_rows(db, org, kind, rows):
    db.add_all([Record(organization_id=org, kind=kind, natural_key=natural_key(kind,r), branch_id=r.get('branch_id'), data=r) for r in rows])

def safe_csv(rows):
    output = io.StringIO(newline='')
    if not rows:
        return '\ufeff'
    fields = list(dict.fromkeys(k for r in rows for k in r if not isinstance(r[k], (dict,list))))
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        clean = {}
        for key in fields:
            value = row.get(key, '')
            # A plain negative decimal (winter temperature, stock decrease) is data, not a formula.
            if (isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n'))
                    and not PLAIN_NEGATIVE_NUMBER.fullmatch(value)):
                value = "'" + value
            clean[key] = value
        writer.writerow(clean)
    return '\ufeff' + output.getvalue()
