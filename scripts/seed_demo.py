"""Explicit seed CLI. Nine CSV files only; never traverse research_only."""
import argparse
import os
import secrets
import sys
import uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import func,select
from apps.api.db import ROOT,Organization,Record,User,make_engine,migrate,sessions
from apps.api.importing import SCHEMAS,insert_rows,parse_csv,validate_rows
from apps.api.security import password_hash

def seed(factory,password,email='admin@asboljam.local',organization_id='demo'):
    if os.environ.get('ASBOLJAM_ENV','local').strip().lower() != 'local':
        raise ValueError('Demo seed is allowed only in local mode.')
    with factory() as db:
        organization=db.get(Organization,organization_id)
        if organization is None:
            organization=Organization(id=organization_id,name='AsBoljam Demo' if organization_id=='demo' else None,
                timezone='Asia/Qyzylorda',currency='KZT',status='active',data_policy='synthetic_only',provenance='demo_seed')
            db.add(organization);db.flush()
        elif organization.status!='active' or organization.data_policy!='synthetic_only':
            raise ValueError('Demo seed requires an active synthetic-only organization.')
        existing=db.scalar(select(func.count()).select_from(Record).where(Record.organization_id==organization_id))
        if not existing:
            for kind in SCHEMAS:
                source=ROOT/'data'/'raw'/(kind+'.csv')
                rows,errors=parse_csv(kind,source.read_text(encoding='utf-8-sig'))
                errors=errors or validate_rows(db,organization_id,kind,rows)
                if errors:
                    raise ValueError(f'{kind}: {errors[:3]}')
                insert_rows(db,organization_id,kind,rows)
                db.flush()
        user=db.scalar(select(User).where(User.email==email.lower()))
        created=False
        if user is None:
            branches=[r.data['branch_id'] for r in db.scalars(select(Record).where(Record.organization_id==organization_id,Record.kind=='branches'))]
            user=User(id=uuid.uuid4().hex,organization_id=organization_id,email=email.lower(),password_hash=password_hash(password),role='admin',branch_ids=branches)
            db.add(user);created=True
        elif user.organization_id!=organization_id:
            raise ValueError('Email belongs to another organization')
        db.commit()
        return created

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--email',default='admin@asboljam.local')
    args=parser.parse_args()
    from apps.api.config import load_settings
    settings=load_settings()
    if settings.environment!='local':
        raise SystemExit('Demo seed is allowed only in local mode.')
    engine=make_engine(settings.database_url);migrate(engine)
    provided=os.environ.get('DEMO_PASSWORD')
    password=provided or secrets.token_urlsafe(18)
    created=seed(sessions(engine),password,args.email)
    if created:
        print(f'Demo admin created: {args.email}')
        if provided: print('Password read from DEMO_PASSWORD (not printed).')
        else: print(f'Generated one-time display password: {password}')
    else:
        print('Demo data/user already exist. Existing password was preserved.')
    print('SYNTHETIC scenario 2026-01-01; 9 operational CSV types. Oracle excluded.')
if __name__=='__main__':
    main()
