"""Check candidate Git files for credential formats and known local secret values.
Prints paths and categories only, never matching secret text. Not a complete security audit.
"""
import argparse,json,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--staged',action='store_true');args=parser.parse_args()
 command=['git','diff','--cached','--name-only','--diff-filter=ACMR','-z'] if args.staged else ['git','ls-files','--cached','--others','--exclude-standard','-z']
 names=subprocess.check_output(command,cwd=ROOT).decode().split('\0');names=[n for n in names if n]
 secrets=[]
 for source in ROOT.glob('.env*'):
  if source.name=='.env.example':continue
  for line in source.read_text(encoding='utf-8-sig').splitlines():
   if '=' in line:
    key,value=line.split('=',1)
    if re.search(r'PASSWORD|TOKEN|SECRET|API_KEY',key,re.I) and len(value.strip())>=10:secrets.append((key.strip(),value.strip().encode()))
 credential=ROOT/'.cache/e2e-login.json'
 if credential.exists():
  entry=json.loads(credential.read_text());secrets.append(('E2E_PASSWORD',entry['password'].encode()))
 patterns=[('private-key',rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),('github-token',rb'gh[pousr]_[A-Za-z0-9]{30,}'),('github-fine-grained-token',rb'github_pat_[A-Za-z0-9_]{40,}'),('openai-key',rb'sk-(?:proj-)?[A-Za-z0-9_-]{40,}'),('aws-key',rb'AKIA[0-9A-Z]{16}')]
 findings=[]
 for name in names:
  p=ROOT/name
  if not p.is_file():continue
  if (p.name.startswith('.env') and p.name!='.env.example') or p.suffix in {'.pem','.key','.pfx','.p12','.sqlite','.db'}:findings.append({'file':name,'category':'forbidden-file'})
  data=subprocess.check_output(['git','show',':'+name],cwd=ROOT) if args.staged else p.read_bytes()
  for key,secret in secrets:
   if secret in data:findings.append({'file':name,'category':'known-local-secret:'+key})
  for kind,pattern in patterns:
   if re.search(pattern,data):findings.append({'file':name,'category':kind})
 report={'checked_files':len(names),'scope':'staged' if args.staged else 'git-candidates','findings':findings,'limits':'Known local values and common high-confidence credential formats; not a comprehensive secret audit.'}
 out=ROOT/'artifacts/security-scan.json';out.parent.mkdir(exist_ok=True);out.write_text(json.dumps(report,indent=2),encoding='utf-8')
 print(json.dumps(report,indent=2));return bool(findings)
if __name__=='__main__':raise SystemExit(main())
