"""Prepare an empty TEST-purpose source for the real-contract browser workflow.

Generated CSVs and credentials stay in ignored .cache. No enterprise data is used.
"""
import json
from pathlib import Path
import secrets
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apps.api.db import make_engine, migrate, sessions
from apps.api.tenants import bootstrap_tenant, configure_real_source
from scripts.pilot_fixture import BRANCH, SOURCE, csv_text, dataset

engine=make_engine();migrate(engine);factory=sessions(engine)
organization_id='real-contract-test-'+uuid.uuid4().hex[:12]
email=organization_id+'@fixture.invalid'
password=secrets.token_urlsafe(24)
with factory() as db:
    bootstrap_tenant(db,organization_id=organization_id,name='ARTIFICIAL contract fixture — not a business',
        timezone='Asia/Almaty',data_policy='unconfigured',email=email,password=password,
        operator_id='browser_fixture',reason='Artificial REAL-schema test fixture only')
    configure_real_source(db,organization_id=organization_id,**SOURCE,branch_id=BRANCH,
        authorization_reference='generated-fixture-not-enterprise-consent',purpose='test_fixture',
        operator_id='browser_fixture',reason='Exercise technical schema; no business or savings claimed')
    db.commit()
output=Path('.cache/real-e2e-login.json');output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps(dict(email=email,password=password,organization_id=organization_id,
    branch_id=BRANCH,origin='2026-03-31',target_date='2026-04-01',source=SOURCE,
    csvs={kind:csv_text(kind,rows) for kind,rows in dataset().items()}),ensure_ascii=False),encoding='utf-8')
engine.dispose()
print('Empty TEST-purpose source prepared; generated CSVs and credentials stored in ignored .cache/real-e2e-login.json')
