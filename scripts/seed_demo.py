"""Explicit seed CLI. Nine CSV files only; never traverse research_only."""
import argparse
import csv
import os
import re
import secrets
import sys
import uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import func,select
from apps.api.db import ROOT,Organization,Record,User,make_engine,migrate,sessions
from apps.api.importing import SCHEMAS,insert_rows,parse_csv,validate_rows
from apps.api.security import password_hash

# kz: Kazakhstan product demo, the CLI default. raw: supplied diploma research data,
# the default of seed() so tests and browser fixtures keep their documented rows.
DATASETS={'kz':ROOT/'data'/'kz','raw':ROOT/'data'/'raw'}
# Kinds a dataset may omit. They are also added to an existing demo that holds the same dataset.
OPTIONAL_KINDS=('day_factors',)

def seed(factory,password,email='admin@asboljam.local',organization_id='demo',dataset='raw'):
    if os.environ.get('ASBOLJAM_ENV','local').strip().lower() != 'local':
        raise ValueError('Demo seed is allowed only in local mode.')
    stored=stored_dataset(factory,organization_id)
    with factory() as db:
        organization=db.get(Organization,organization_id)
        if organization is None:
            organization=Organization(id=organization_id,name='AsBoljam Demo' if organization_id=='demo' else None,
                timezone='Asia/Qyzylorda',currency='KZT',status='active',data_policy='synthetic_only',provenance='demo_seed')
            db.add(organization);db.flush()
        elif organization.status!='active' or organization.data_policy!='synthetic_only':
            raise ValueError('Demo seed requires an active synthetic-only organization.')
        existing=db.scalar(select(func.count()).select_from(Record).where(Record.organization_id==organization_id))
        for kind in SCHEMAS:
            source=DATASETS[dataset]/(kind+'.csv')
            if kind in OPTIONAL_KINDS:
                if not source.exists() or (existing and stored!=dataset) or db.scalar(select(func.count()).select_from(Record)
                        .where(Record.organization_id==organization_id,Record.kind==kind)):
                    continue
            elif existing:
                continue
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

def branch_account_email(branch_id):
    """Demo sign-in of one establishment: branch-<id>@asboljam.local."""
    return 'branch-'+(re.sub(r'[^a-z0-9-]+','-',str(branch_id).lower()).strip('-') or 'unnamed')+'@asboljam.local'

def seed_branch_accounts(factory,password,organization_id='demo'):
    """One manager per branch, scoped to that branch only: each establishment signs in to its
    own cabinet instead of choosing a branch. Existing accounts and passwords stay unchanged."""
    if os.environ.get('ASBOLJAM_ENV','local').strip().lower() != 'local':
        raise ValueError('Demo seed is allowed only in local mode.')
    created=[]
    with factory() as db:
        branches=[(str(r.data['branch_id']),r.data.get('branch_name')) for r in db.scalars(select(Record).where(
            Record.organization_id==organization_id,Record.kind=='branches'))]
        for branch_id,branch_name in sorted(branches):
            email=branch_account_email(branch_id)
            user=db.scalar(select(User).where(User.email==email))
            if user is None:
                db.add(User(id=uuid.uuid4().hex,organization_id=organization_id,email=email,password_hash=password_hash(password),
                    role='manager',branch_ids=[branch_id]))
                created.append((email,branch_name))
            elif user.organization_id!=organization_id or list(user.branch_ids or [])!=[branch_id]:
                raise ValueError(f'{email} already exists with a different organization or branch scope')
        db.commit()
    return created

def stored_dataset(factory,organization_id='demo'):
    """Name the shipped dataset whose branches the organization already holds."""
    with factory() as db:
        stored={r.data.get('branch_id'):r.data.get('branch_name') for r in db.scalars(select(Record).where(
            Record.organization_id==organization_id,Record.kind=='branches'))}
    if not stored:
        return None
    for name,directory in DATASETS.items():
        with (directory/'branches.csv').open(encoding='utf-8-sig',newline='') as handle:
            if stored=={row['branch_id']:row['branch_name'] for row in csv.DictReader(handle)}:
                return name
    return 'custom'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--email',default='admin@asboljam.local')
    parser.add_argument('--no-branch-accounts',action='store_true',help='Do not create one manager sign-in per branch.')
    parser.add_argument('--dataset',default=os.environ.get('DEMO_DATASET') or 'kz',
        help='kz: Kazakhstan demo (default); raw: supplied research dataset. Also read from DEMO_DATASET.')
    args=parser.parse_args()
    if args.dataset not in DATASETS:
        parser.error('--dataset/DEMO_DATASET must be one of: '+', '.join(sorted(DATASETS)))
    from apps.api.config import load_settings
    settings=load_settings()
    if settings.environment!='local':
        raise SystemExit('Demo seed is allowed only in local mode.')
    engine=make_engine(settings.database_url);migrate(engine);factory=sessions(engine)
    stored=stored_dataset(factory)
    provided=os.environ.get('DEMO_PASSWORD')
    password=provided or secrets.token_urlsafe(18)
    def factor_rows():
        with factory() as db:
            return db.scalar(select(func.count()).select_from(Record).where(Record.organization_id=='demo',Record.kind=='day_factors'))
    factors_before=factor_rows()
    created=seed(factory,password,args.email,dataset=args.dataset)
    if factor_rows()>factors_before:
        print(f'Day factors imported: {factor_rows()} rows (known-in-advance calendar, culture, school, weather, opening).')
    if created:
        print(f'Demo admin created: {args.email}')
        if provided: print('Password read from DEMO_PASSWORD (not printed).')
        else: print(f'Generated one-time display password: {password}')
    else:
        print('Demo data/user already exist. Existing password was preserved.')
    if not args.no_branch_accounts:
        accounts=seed_branch_accounts(factory,password)
        for email,branch_name in accounts:
            print(f'Establishment sign-in created: {email} ({branch_name or "—"}), manager of this branch only.')
        if accounts and not provided and not created:
            print(f'Generated one-time display password for the new establishment sign-ins: {password}')
        if accounts and not provided and created:
            print('Establishment sign-ins use the same one-time password as the demo admin above.')
        if accounts and provided:
            print('Establishment sign-ins use the password from DEMO_PASSWORD (not printed).')
    if stored and stored!=args.dataset:
        print(f'Notice: this database already holds the {stored} demo dataset; it was left unchanged. '
              f'Use a new DATABASE_URL to load the {args.dataset} dataset.')
    print(f'Demo dataset: {stored or args.dataset}. SYNTHETIC scenario 2026-01-01; 9 operational CSV types. Oracle excluded.')
if __name__=='__main__':
    main()
