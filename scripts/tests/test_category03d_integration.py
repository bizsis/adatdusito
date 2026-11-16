"""Integration invariants across the exact CATEGORY-03D backend inputs."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]


def test_worker_only_startup_registers_all_existing_product_tasks():
    # Fresh process: API imports must not accidentally hide a worker-only registration bug.
    code='''from app.worker import celery
celery.loader.import_default_modules()
expected={"infra.ping","supplier.import","products.reapply_category_map","products.parameter_run","products.operation"}
assert expected <= set(celery.tasks), expected - set(celery.tasks)
assert celery.tasks["products.operation"].run.__module__ == "app.bulk_operations"
'''
    r=subprocess.run([sys.executable,'-c',code],cwd=ROOT,env={**os.environ,'PYTHONPATH':str(ROOT/'backend')},capture_output=True,text=True)
    assert r.returncode==0,r.stderr


def test_donor_audit_is_included_in_bulk_approval_schema_fingerprint():
    from app import bulk_operations as bo,product_parameters as pp,product_catalog as pc
    base=ROOT/'backend/reference_data'
    review=json.loads((base/'donor_review.json').read_text())
    assert {(r['node_id'],r['emag_category_id'],r['state']) for r in review['entries']}=={
        ('web-item-114-3492',385,'pending_review'),('web-item-114-3820',58,'pending_review'),('web-item-83-4339',63,'pending_review')}
    digest=hashlib.sha256(pp.RULE_VERSION.encode())
    for name in ['reviewed_parameter_bindings.json','donor_review.json']:digest.update((base/name).read_bytes())
    assert bo.schema_fingerprint()==digest.hexdigest()
    nodes=pc.internal_categories();assert len(nodes)==457
    assert len({n['path_ids'][0] for n in nodes.values()})==13
