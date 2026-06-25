# -*- coding: utf-8 -*-
from __future__ import annotations
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEST_GROUP = 'CHAMPIONSHIP RINGS'
TEST_URL = 'https://post.alibaba.com/product/publish.htm?spm=a2747.product_manager.0.0.65f771d2VPmQiz&pubType=similarPost&itemId=1601212500292&behavior=copyNew'

def main():
    from app.core.settings import get_config
    from app.core.task_manager import TaskInfo, TaskStatus
    from app.services.page_scanner.config_bridge import apply_scan_to_config, validate_group_for_publish
    from app.services.page_scanner.scanner import scan_publish_page
    from app.services.upload_service import get_available_products_list, run_upload_task
    started = time.time()
    report = {'steps': []}
    print('='*60); print('STEP 1/3: scan'); print('='*60)
    t0 = time.time()
    scan = scan_publish_page(TEST_URL, probe_buttons=False, wait_seconds=45.0)
    se = round(time.time()-t0, 1)
    if not scan.get('success'):
        print('FAIL scan', se, scan.get('error')); return 1
    wfs = scan.get('workflows') or []
    print('scan ok', se, 'workflows', len(wfs))
    report['steps'].append({'step':'scan','ok':True,'elapsed_s':se,'workflows':len(wfs)})
    print('='*60); print('STEP 2/3: apply'); print('='*60)
    t0 = time.time()
    applied = apply_scan_to_config(group_name=TEST_GROUP, url=TEST_URL, workflows=wfs,
        page_type=scan.get('page_type',''), page_type_label=scan.get('page_type_label',''),
        element_count=scan.get('element_count',0), workflow_count=scan.get('workflow_count',len(wfs)),
        sync_platform=True)
    ae = round(time.time()-t0, 1)
    val = validate_group_for_publish(TEST_GROUP)
    cfg = get_config()
    prof = (cfg.page_scan.profiles_by_group or {}).get(TEST_GROUP)
    fr = len(getattr(prof,'field_requirements',None) or [])
    cf = len(getattr(prof,'compliance_fields',None) or [])
    print('apply', ae, applied.get('success'), 'ready', applied.get('ready_for_publish'))
    print('validate', val.get('success'), 'field_reqs', fr, 'compliance', cf)
    if len(wfs) < 8 or not applied.get('success'):
        print('FAIL apply'); return 1
    report['steps'].append({'step':'apply','ok':True,'elapsed_s':ae,'field_requirements':fr,'compliance_fields':cf})
    avail = get_available_products_list()
    if not avail:
        print('FAIL no products'); return 1
    p = avail[0]
    print('product', p.get('pid'), p.get('category'))
    print('='*60); print('STEP 3/3: publish'); print('='*60)
    t0 = time.time()
    task = TaskInfo('full_acceptance_e2e','e2e')
    task.status = TaskStatus.RUNNING
    run_upload_task(task, mode='batch', max_products=1, scheduled_time=None)
    pe = round(time.time()-t0, 1)
    te = round(time.time()-started, 1)
    ok = '成功发布 0' not in (task.current_step or '')
    print('publish', pe, 'step', task.current_step)
    report['steps'].append({'step':'publish','ok':ok,'elapsed_s':pe,'current_step':task.current_step})
    report['total_elapsed_s'] = te; report['success'] = ok
    out = ROOT/'scripts'/'full_acceptance_e2e_last.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('TOTAL', te, 'PASS' if ok else 'FAIL')
    return 0 if ok else 1

if __name__ == '__main__':
    raise SystemExit(main())
