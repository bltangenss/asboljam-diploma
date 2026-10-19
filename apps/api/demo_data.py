"""Load the shipped SYNTHETIC KZ demo into an empty self-registered cabinet.

One source branch of data/kz is chosen by establishment type and renamed to the cabinet's
branch; calendar and solar factors are rebuilt for the cabinet's own city. The cabinet
keeps its own branch row, and nothing is loaded unless every demo file passes the same
parser and reference checks as a user import.
"""
import csv
from datetime import date
import io

from fastapi import Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .cities import city as find_city
from .data_policy import DEMO_TARGET, DataPolicyError, policy_context
from .db import BranchProfile, ROOT, Record
from .factor_builder import FactorBuildError, calendar_rows
from .factors import ORDER
from .importing import SCHEMAS, insert_rows, parse_csv, rows_for, validate_rows

DEMO_DIR = ROOT / 'data' / 'kz'
SOURCE_BRANCH_BY_TYPE = {'canteen': '1', 'other': '1', 'cafe': '2', 'coffee_shop': '2', 'bakery': '2',
                         'fast_food': '2', 'restaurant': '3', 'toikhana': '3'}
SHARED_KINDS = ('meals', 'ingredients', 'recipes', 'suppliers', 'supplier_offers')
BRANCH_KINDS = ('calendar', 'daily_sales', 'inventory_lots')
# Synthetic demo factors that do not depend on the city; the rest come from factor_builder.
CARRIED_FACTORS = frozenset({'temperature_forecast_c', 'heat_alert', 'payday', 'is_open'})


class DemoDataError(ValueError):
    def __init__(self, code, message, status=422):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


class DemoDataInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    branch_id: str = Field(min_length=1, max_length=64)


def demo_source_branch(establishment_type) -> str:
    return SOURCE_BRANCH_BY_TYPE.get(establishment_type, '1')


def read_demo(kind):
    with (DEMO_DIR / f'{kind}.csv').open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def demo_rows(branch_id, city_code, establishment_type):
    """Demo rows per kind as strings, addressed to branch_id and built for city_code."""
    source = demo_source_branch(establishment_type)
    def take(kind, row):
        return {field: branch_id if field == 'branch_id' else row.get(field, '') for field in SCHEMAS[kind].split()}
    rows = {kind: [take(kind, row) for row in read_demo(kind)] for kind in SHARED_KINDS}
    for kind in BRANCH_KINDS:
        rows[kind] = [take(kind, row) for row in read_demo(kind) if row['branch_id'] == source]
    start = min(row['date'] for row in rows['daily_sales'])
    factors = [{'date': day.isoformat(), 'branch_id': branch_id, 'factor': code, 'value': str(value), 'data_origin': 'SYNTHETIC'}
               for day, code, value in calendar_rows(city_code, date.fromisoformat(start), date.fromisoformat(DEMO_TARGET))]
    factors += [take('day_factors', row) for row in read_demo('day_factors')
                if row['branch_id'] == source and row['factor'] in CARRIED_FACTORS]
    rows['day_factors'] = sorted(factors, key=lambda row: (row['date'], ORDER.index(row['factor'])))
    return rows


def csv_text(kind, rows):
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=SCHEMAS[kind].split(), extrasaction='ignore', lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def load_demo_data(db, organization_id, branch_id):
    """Validate and insert the demo into an empty cabinet; the caller commits."""
    try:
        origin = policy_context(db, organization_id)['data_origin']
    except DataPolicyError:
        origin = None
    if origin != 'SYNTHETIC':
        raise DemoDataError('DEMO_DATA_SYNTHETIC_ONLY', 'Демо-деректер тек синтетикалық режимдегі ұйымға жүктеледі.', 403)
    if not any(row['branch_id'] == branch_id for row in rows_for(db, organization_id, 'branches')):
        raise DemoDataError('BRANCH_NOT_FOUND', 'Бөлімше табылмады.', 404)
    profile = db.get(BranchProfile, (organization_id, branch_id))
    place = find_city(profile.city_code) if profile else None
    if place is None:
        raise DemoDataError('BRANCH_CITY_REQUIRED', 'Алдымен бөлімшенің қаласын таңдаңыз.', 422)
    if db.scalar(select(func.count()).select_from(Record).where(Record.organization_id == organization_id, Record.kind != 'branches')):
        raise DemoDataError('DEMO_DATA_NOT_EMPTY', 'Кабинетте деректер бар: демо тек бос кабинетке жүктеледі.', 409)
    try:
        rows = demo_rows(branch_id, place['code'], profile.establishment_type)
    except FactorBuildError as exc:
        raise DemoDataError('DEMO_DATA_INVALID', exc.message, 500) from exc
    counts = {}
    for kind in SCHEMAS:
        if kind == 'branches':
            continue
        parsed, errors = parse_csv(kind, csv_text(kind, rows[kind]))
        errors = errors or validate_rows(db, organization_id, kind, parsed)
        if errors:
            raise DemoDataError('DEMO_DATA_INVALID', f'Демо-деректер тексеруден өтпеді: {kind}.', 500)
        insert_rows(db, organization_id, kind, parsed)
        db.flush()
        counts[kind] = len(parsed)
    days = sorted(row['date'] for row in rows['daily_sales'])
    return {'source_branch': demo_source_branch(profile.establishment_type), 'city_code': place['code'], 'rows': counts,
            'history_start': days[0], 'history_end': days[-1], 'target_date': DEMO_TARGET}


def register_demo_routes(app, *, current, get_db, roles, branch_access, fail, audit):
    @app.post('/api/v1/demo-data')
    def load_demo(data: DemoDataInput, user=Depends(current), db=Depends(get_db)):
        roles(user, 'admin');branch_access(db, user, data.branch_id)
        try:
            result = load_demo_data(db, user.organization_id, data.branch_id)
        except DemoDataError as exc:
            db.rollback()
            fail(exc.code, exc.message, exc.status)
        audit(db, user, 'demo_data.loaded', data.branch_id, data.branch_id,
              {key: result[key] for key in ('source_branch', 'city_code', 'rows')})
        try:
            db.commit()
        except IntegrityError:
            # A concurrent load of the same cabinet won; this one changes nothing.
            db.rollback()
            fail('DEMO_DATA_NOT_EMPTY', 'Кабинетте деректер бар: демо тек бос кабинетке жүктеледі.', 409)
        return result
