# -*- coding: utf-8 -*-
from __future__ import annotations
import os, subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = [
    ('CRUD', 'acceptance_crud.py'),
    ('comprehensive', 'acceptance_comprehensive.py'),
    ('full_system', 'acceptance_full_system.py'),
    ('api', 'acceptance_api.py'),
    ('sync_and_points', 'acceptance_sync_and_points.py'),
    ('three_issues', 'acceptance_three_issues.py'),
    ('dashboard_buttons', 'acceptance_dashboard_buttons.py'),
    ('admin_runtime_sync', 'acceptance_admin_runtime_sync.py'),
    ('runtime_secrets_fix', 'acceptance_runtime_secrets_fix.py'),
    ('cloud_key_type', 'acceptance_cloud_key_type.py'),
]
def main():
    py = ROOT / 'backend' / 'venv' / 'Scripts' / 'python.exe'
    if not py.is_file(): py = Path(sys.executable)
    print('backend=', os.getenv('ACCEPTANCE_BACKEND','http://127.0.0.1:8001'))
    rows = []
    for label, script in SCRIPTS:
        path = ROOT / 'scripts' / script
        t0 = time.time()
        print('\\n' + '='*60 + '\\n>>> ' + label + '\\n' + '='*60)
        proc = subprocess.run([str(py), str(path)], cwd=str(ROOT), env=os.environ.copy())
        elapsed = time.time() - t0
        tag = 'PASS' if proc.returncode == 0 else 'FAIL'
        print('\\n<<< ' + label + ': ' + tag + ' (' + str(round(elapsed,1)) + 's)')
        rows.append((label, proc.returncode, elapsed))
    passed = sum(1 for _,c,_ in rows if c==0)
    print('\\nSUMMARY', passed, '/', len(rows))
    for label,code,elapsed in rows:
        print(('PASS' if code==0 else 'FAIL'), label, round(elapsed,1))
    return 0 if passed==len(rows) else 1
if __name__ == '__main__':
    raise SystemExit(main())
