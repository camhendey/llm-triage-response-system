"""Reproducible checks with actual captured output and environment metadata."""
import importlib.metadata
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/verification'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    checks=[('pytest.txt',['-m','pytest']),('coordinator-browser.txt',['scripts/verify_coordinator.py']),
            ('nicegui-workflows.txt',['scripts/verify_nicegui_workflows.py']),
            ('opentable-browser.txt',['scripts/verify_opentable_import.py']),
            ('nicegui-browser.txt',['scripts/capture_nicegui.py'])]
    results=[]
    for name,args in checks:
        print('Running '+name,flush=True)
        run=subprocess.run([sys.executable,*args],cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        (OUT/name).write_text(run.stdout,encoding='utf-8')
        print(run.stdout[-1500:],flush=True)
        results.append(dict(check=name,exit_code=run.returncode))
        if run.returncode:
            raise SystemExit(run.returncode)
    (OUT/'environment.json').write_text(json.dumps(dict(verified_at=datetime.now(timezone.utc).isoformat(),
        python=sys.version,packages={name:importlib.metadata.version(name) for name in ('nicegui','pydantic','pytest','playwright','pillow')},
        checks=results),indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
