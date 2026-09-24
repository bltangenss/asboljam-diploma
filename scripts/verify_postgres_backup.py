"""Round-trip a private pg_dump to a newly named DB in our verification project."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid
from verify_postgres import ROOT,load_env

def main():
    env_file=ROOT/'.env.docker.local'
    settings=load_env(env_file)
    env={**os.environ,**settings}
    base=['docker','compose','--env-file',str(env_file),'-f',str(ROOT/'docker-compose.yml'),'-f',str(ROOT/'infra/compose.verify.yml'),'-p','asboljam-verification','exec','-T','postgres']
    report={'timestamp':datetime.now(timezone.utc).isoformat(),'status':'running','project':'asboljam-verification'}
    def call(args,input_data=None):
        proc=subprocess.run(base+args,cwd=ROOT,env=env,input=input_data,capture_output=True,timeout=120)
        if proc.returncode:
            raise RuntimeError('PostgreSQL backup command failed (details omitted to protect dump contents).')
        return proc.stdout
    def scalar(database,sql):
        return call(['psql','-U','asboljam','-d',database,'-At','-c',sql]).decode('utf-8').strip()
    try:
        source='asboljam'
        restored='asboljam_restored_'+uuid.uuid4().hex[:12]
        dump=call(['pg_dump','-U','asboljam','-d',source,'-Fc','--no-owner','--no-acl'])
        backup_dir=ROOT/'backups'
        backup_dir.mkdir(exist_ok=True)
        backup_path=backup_dir/(restored+'.dump')
        with backup_path.open('xb') as stream: stream.write(dump)
        call(['createdb','-U','asboljam',restored])
        call(['pg_restore','-U','asboljam','-d',restored,'--no-owner','--no-acl','--exit-on-error'],dump)
        tables=scalar(source,"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;").splitlines()
        for table in tables:
            if not table.replace('_','').isalnum(): raise RuntimeError('Unexpected table identifier')
        count_query=' UNION ALL '.join("SELECT '"+table+"',count(*) FROM \""+table+"\"" for table in tables)+';'
        def counts(database):
            text=scalar(database,count_query)
            return {line.split('|')[0]:int(line.split('|')[1]) for line in text.splitlines()}
        source_counts=counts(source)
        restored_counts=counts(restored)
        if source_counts!=restored_counts: raise RuntimeError('Restored row counts differ')
        hash_query="SELECT md5(coalesce(string_agg(id || ':' || password_hash, ',' ORDER BY id),'')) FROM users;"
        if scalar(source,hash_query)!=scalar(restored,hash_query): raise RuntimeError('Restored credential hashes differ')
        if scalar(restored,"SELECT version FROM schema_migrations;")!='0001': raise RuntimeError('Restored migration marker differs')
        report.update(status='passed',source_database=source,restored_database=restored,backup_file=str(backup_path.relative_to(ROOT)).replace('\\','/'),backup_bytes=len(dump),backup_sha256=hashlib.sha256(dump).hexdigest(),table_counts=source_counts,table_counts_match=True,password_hashes_match=True,migration_restored=True)
        print('PASS: pg_dump / pg_restore round-trip; every table count and password hash preserved. Hash values withheld.')
    except Exception as exc:
        report.update(status='failed',error=str(exc))
        print('FAIL: PostgreSQL backup verification; see report.')
    path=ROOT/'artifacts/verification/postgres-backup.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Report: artifacts/verification/postgres-backup.json. Private dump is excluded from handoff.')
    return 0 if report['status']=='passed' else 1
if __name__=='__main__':
    raise SystemExit(main())
