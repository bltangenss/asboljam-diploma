"""Record final isolated Compose images, service health and nginx HTTP checks."""
from datetime import datetime,timezone
import json
import os
import re
import subprocess
import urllib.request
from verify_postgres import ROOT,load_env

def main():
    source=ROOT/'.env.docker.local'
    env={**os.environ,**load_env(source)}
    prefix=['docker','compose','--env-file',str(source),'-f',str(ROOT/'docker-compose.yml'),'-f',str(ROOT/'infra/compose.verify.yml'),'-p','asboljam-verification']
    proc=subprocess.run(prefix+['ps','--format','json'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=30,check=True)
    raw=[json.loads(line) for line in proc.stdout.splitlines() if line.startswith('{')]
    report={'timestamp':datetime.now(timezone.utc).isoformat(),'project':'asboljam-verification','services':[],'http_checks':[]}
    for item in raw:
        match=re.search(r'com.docker.compose.image=([^,]+)',item.get('Labels',''))
        report['services'].append({**{key:item.get(key) for key in ['Service','State','Health','Image','Publishers']},'image_id':match.group(1) if match else None})
    for path in ['/', '/dashboard', '/api/v1/health']:
        with urllib.request.urlopen('http://127.0.0.1:3010'+path,timeout=15) as response:
            body=response.read()
            assert response.status==200
            if path.endswith('health'): assert json.loads(body)['status']=='ok'
            else: assert b'<html' in body.lower()
            report['http_checks'].append({'path':path,'status':response.status,'bytes':len(body),'content_type':response.headers.get('Content-Type')})
    assert {row['Service'] for row in report['services']}=={'postgres','api','worker','web'}
    assert all(row['State']=='running' for row in report['services'])
    assert all(row['Health']=='healthy' for row in report['services'] if row['Service'] in {'postgres','api'})
    report['status']='passed'
    target=ROOT/'artifacts/verification/docker-state.json'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS: four Docker services running; PostgreSQL/API healthy; final nginx SPA, fallback and API proxy return200.')
    print('Report: artifacts/verification/docker-state.json')
if __name__=='__main__': main()
