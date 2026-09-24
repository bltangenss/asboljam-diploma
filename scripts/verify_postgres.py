"""Verify the isolated Docker PostgreSQL deployment without printing credentials.

The script creates a fresh asboljam_test_<suffix> database for the API suite.
It preserves existing containers, volumes and databases. Invoke after compose up.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]

def load_env(path):
    result={}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if line.strip() and not line.lstrip().startswith('#') and '=' in line:
            key,value=line.split('=',1)
            result[key.strip()]=value.strip().strip('"').strip("'")
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',type=Path,default=ROOT/'.env.docker.local')
    args=parser.parse_args()
    config=load_env(args.env_file)
    if not config.get('POSTGRES_PASSWORD') or not config.get('DEMO_PASSWORD'):
        raise SystemExit('POSTGRES_PASSWORD and DEMO_PASSWORD must be configured privately.')
    environment={**os.environ,**config}
    compose=['docker','compose','--env-file',str(args.env_file),'-f',str(ROOT/'docker-compose.yml'),'-f',str(ROOT/'infra/compose.verify.yml'),'-p','asboljam-verification']
    started=time.monotonic()
    report={'timestamp':datetime.now(timezone.utc).isoformat(),'project':'asboljam-verification','checks':[],'status':'running'}
    def safe(text):
        for key in ['POSTGRES_PASSWORD','DEMO_PASSWORD']:
            text=text.replace(config[key],'[REDACTED]')
        text=re.sub(r'(postgresql(?:\+psycopg)?://[^:]+:)[^@]+@',r'\1[REDACTED]@',text)
        return text
    def run(arguments,timeout=180):
        result=subprocess.run(arguments,cwd=ROOT,env=environment,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
        if result.returncode:
            raise RuntimeError(safe(result.stdout+result.stderr)[-12000:])
        return safe(result.stdout+result.stderr).strip()
    try:
        version=run(compose+['exec','-T','postgres','psql','-U','asboljam','-d','asboljam','-At','-c','SELECT version();'])
        assert 'PostgreSQL 17.' in version
        report['postgres_version']=version
        print('PASS: PostgreSQL server connected.')
        seed_output=run(compose+['exec','-T','-e','DEMO_PASSWORD','api','python','scripts/seed_demo.py'])
        report['checks'].append({'check':'explicit_seed','status':'passed'})
        print('PASS: explicit nine-file seed completed; credentials withheld.')
        dialect=run(compose+['exec','-T','api','python','-c','from apps.api.db import make_engine; print(make_engine().dialect.name)'])
        assert dialect=='postgresql',dialect
        report['api_database_dialect']=dialect
        counts=run(compose+['exec','-T','postgres','psql','-U','asboljam','-d','asboljam','-At','-F',',','-c','SELECT kind,count(*) FROM operational_records GROUP BY kind ORDER BY kind;'])
        report['operational_row_counts']={line.split(',')[0]:int(line.split(',')[1]) for line in counts.splitlines() if ',' in line}
        assert len(report['operational_row_counts'])==9
        assert report['operational_row_counts']['daily_sales']>=26316
        report['checks'].append({'check':'postgresql_dialect_and_seed_counts','status':'passed'})
        print('PASS: API uses PostgreSQL; all nine operational types persisted.')
        database='asboljam_test_'+uuid.uuid4().hex[:12]
        run(compose+['exec','-T','postgres','createdb','-U','asboljam',database])
        environment['ASBOLJAM_TEST_DATABASE_URL']='postgresql+psycopg://asboljam:'+config['POSTGRES_PASSWORD']+'@postgres:5432/'+database
        test_output=run(compose+['run','--rm','--no-deps','-e','ASBOLJAM_TEST_DATABASE_URL','-e','ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000','--volume',str(ROOT)+':/workspace:ro','--workdir','/workspace','api','python','-X','utf8','-m','unittest','discover','-s','tests','-p','test_api.py','-v'],timeout=300)
        report['api_test_database']=database
        report['api_test_output']=test_output
        match=re.search(r'Ran (\d+) tests in ([0-9.]+)s',test_output)
        report['api_test_count']=int(match.group(1)) if match else None
        report['api_test_elapsed_seconds']=float(match.group(2)) if match else None
        report['api_test_command']='python -X utf8 -m unittest discover -s tests -p test_api.py -v (ASBOLJAM_TEST_DATABASE_URL=fresh PostgreSQL database)'
        report['docker_server_version']=run(['docker','version','--format','{{.Server.Version}}'])
        version_code="import sys,json,importlib.metadata as m; print(json.dumps({'python':sys.version.split()[0],**{n:m.version(n) for n in ['fastapi','sqlalchemy','psycopg','numpy','scipy','scikit-learn']}}))"
        report['runtime_versions']=json.loads(run(compose+['exec','-T','api','python','-c',version_code]))
        services=[json.loads(line) for line in run(compose+['ps','--format','json']).splitlines() if line.startswith('{')]
        report['services']=[{**{key:r.get(key) for key in ['Service','State','Health','Image','Publishers']},'image_id':(re.search(r'com.docker.compose.image=([^,]+)',r.get('Labels','')).group(1) if re.search(r'com.docker.compose.image=([^,]+)',r.get('Labels','')) else None)} for r in services]
        report['checks'].append({'check':'full_api_suite_on_postgresql','status':'passed'})
        print('PASS: full API suite on a fresh isolated PostgreSQL database.')
        report['status']='passed'
    except Exception as exc:
        report['status']='failed'
        report['error']=safe(str(exc))
        print('FAIL: PostgreSQL verification. See sanitized report.',file=sys.stderr)
    report['elapsed_seconds']=round(time.monotonic()-started,3)
    output=ROOT/'artifacts/verification/postgres.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Report: artifacts/verification/postgres.json')
    return 0 if report['status']=='passed' else 1
if __name__=='__main__':
    raise SystemExit(main())
