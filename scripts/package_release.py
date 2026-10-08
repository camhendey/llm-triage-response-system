"""Build a clean, hashed source ZIP; never include local guest databases or secrets."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
EXCLUDED={'.venv','__pycache__','.pytest_cache','.ruff_cache','.git','build','dist','node_modules'}


def included(path):
    rel=path.relative_to(ROOT)
    return (path.is_file() and not path.is_symlink() and not any(p in EXCLUDED or p.endswith('.egg-info') for p in rel.parts)
            and path.name!='.env' and path.suffix.lower() not in ('.pyc','.sqlite','.sqlite3','.db','.zip','.pdf','.docx')
            and not path.name.endswith(('-wal','-shm')) and not str(rel).startswith(('data/coordinator/','data/demo/','data/sessions/')))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('output',type=Path)
    parser.add_argument('--baseline',type=Path)
    args=parser.parse_args()
    if args.output.resolve().is_relative_to(ROOT):
        raise SystemExit('Place the release ZIP outside the source tree.')
    evidence=ROOT/'results/verification'
    environment=json.loads((evidence/'environment.json').read_text())
    assert len(environment['checks'])==5 and all(c['exit_code']==0 for c in environment['checks'])
    assert '198 passed' in (evidence/'pytest.txt').read_text()
    paths=sorted(p for p in ROOT.rglob('*') if included(p))
    if args.baseline:
        with zipfile.ZipFile(args.baseline) as old:
            baseline={n.removeprefix('reservation-workbench/'):sha(old.read(n)) for n in old.namelist() if not n.endswith('/')}
        current={p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for p in paths}
        changes={'baseline':args.baseline.name,'created':[n for n in current if n not in baseline],
                 'modified':[n for n in current if n in baseline and current[n]!=baseline[n]],
                 'excluded_or_removed':[n for n in baseline if n not in current]}
        (evidence/'changed-files.json').write_text(json.dumps(changes,indent=2)+'\n')
    paths=sorted(p for p in ROOT.rglob('*') if included(p) and p.name!='RELEASE_MANIFEST.json')
    hashes={p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for p in paths}
    manifest={'version':'3.0.0','packaged_at':datetime.now(timezone.utc).isoformat(),'verification':environment,
              'automated_tests_passed':198,'external_actions':'none; operator attestations only',
              'human_study':'not_run','live_model_evaluation':'not_run','files':hashes}
    m=ROOT/'RELEASE_MANIFEST.json';m.write_text(json.dumps(manifest,indent=2)+'\n')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(args.output,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for p in [*paths,m]:
            archive.write(p,'reservation-workbench/'+p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(args.output) as archive:
        assert archive.testzip() is None
        for name,expected in hashes.items():
            assert sha(archive.read('reservation-workbench/'+name))==expected
        assert len(archive.namelist())==len(hashes)+1
    print(json.dumps({'output':str(args.output.resolve()),'files':len(hashes)+1,'bytes':args.output.stat().st_size,'sha256':sha(args.output.read_bytes())}))


if __name__=='__main__':
    main()
