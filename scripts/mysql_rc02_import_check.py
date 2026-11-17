"""RC-02 import API regression on an EMPTY, THROWAWAY, loopback MySQL 8 only.

Never run on a VPS/shared database or pinfo_db. Requires the explicit fixture
acknowledgement; no database is dropped. Migrations run only after the empty
schema guard. Only synthetic rc02_sample data is used. Output contains counts,
checks and driver version, never credentials, tokens or customer records.
"""
import json
import os
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
sys.path.insert(0,str(ROOT/'scripts/tests'))


def main():
    from sqlalchemy import create_engine, inspect, make_url, select, func, text
    from sqlalchemy.orm import Session
    if os.environ.get('RC02_FIXTURE_ACK')!='isolated-release-candidate-02':
        raise SystemExit('Refusing: RC02_FIXTURE_ACK must explicitly identify the isolated fixture.')
    url=make_url(os.environ['APP_DATABASE_URL'])
    if url.get_backend_name()!='mysql' or url.host not in {'127.0.0.1','localhost','::1'} or url.database!='adatdusito_dev':
        raise SystemExit('Refusing: only an empty loopback MySQL adatdusito_dev fixture is accepted.')
    engine=create_engine(url,pool_pre_ping=True,connect_args={'connect_timeout':3})
    with engine.connect() as conn:
        if inspect(conn).get_table_names():
            raise SystemExit('Refusing: the target schema is not empty.')
        version=conn.scalar(text('SELECT VERSION()'))
        assert version.startswith('8.0.'),'MySQL 8.0 is required'
    # No external reference configuration is inherited by this isolated probe.
    # Any accidental source connection can only fail on a closed loopback port.
    os.environ['REFERENCE_DATABASE_URL']='mysql+pymysql://blocked:blocked@127.0.0.1:1/pinfo_db'
    from alembic import command
    from alembic.config import Config
    cfg=Config(str(ROOT/'backend/alembic.ini'))
    cfg.set_main_option('script_location',str(ROOT/'backend/migrations'))
    command.upgrade(cfg,'head')
    from app.main import app
    from app import api, security, import_api
    from app.import_models import SupplierProduct, ImportRun, ImportChunk
    from app.models import User, Tenant, Membership, Audit
    from app.import_engine import advance
    from fastapi.testclient import TestClient
    from rc02_sample import synthetic_feed
    password='RC02-synthetic-login-only!'
    with Session(engine) as db:
        for uid,email in [(1,'admin'),(2,'other'),(3,'reader')]:
            db.add(User(id=uid,email=f'{email}@example.invalid',name=f'RC02 {email}',
                        password_hash=security.hash_password(password),active=True))
        db.add_all([Tenant(id=1,name='RC02 demo'),Tenant(id=2,name='RC02 other')]);db.flush()
        db.add_all([Membership(tenant_id=1,user_id=1,role='tenant_admin'),
                    Membership(tenant_id=2,user_id=2,role='tenant_admin'),
                    Membership(tenant_id=1,user_id=3,role='reviewer')]);db.commit()
    def database():
        with Session(engine) as db:yield db
    def worker(id):
        with Session(engine) as db:advance(db,id)
    class Guard:
        def check(self):pass
        def failure(self):pass
        def success(self):pass
    checks=[]
    def ok(name):checks.append(name);print('OK '+name,flush=True)
    def response(result,status):
        assert result.status_code==status,f'Expected HTTP {status}; got {result.status_code}'
        return result.json() if result.content else None
    prior=dict(app.dependency_overrides)
    app.dependency_overrides[security.database]=database
    try:
        with ExitStack() as stack:
            # Login throttling is tested by the security suite. Tenant, CSRF,
            # Origin, approval and FK checks stay real in this isolated API test.
            stack.enter_context(patch.object(api,'limit_login',lambda *a,**k:None))
            stack.enter_context(patch.object(api,'login_guard',lambda *a,**k:Guard()))
            stack.enter_context(patch.object(security,'limit_failures',lambda *a,**k:None))
            stack.enter_context(patch.object(import_api,'enqueue',worker))
            stack.enter_context(patch.dict(os.environ,{'APP_ORIGIN':'https://testserver'}))
            client=stack.enter_context(TestClient(app,base_url='https://testserver'))
            def login(name):
                result=response(client.post('/api/v1/auth/login',json={'email':name+'@example.invalid','password':password}),200)
                client.headers['X-CSRF-Token']=result['csrf_token']
            login('admin')
            supplier=response(client.post('/api/v1/imports/suppliers',json={'name':'RC02 synthetic supplier'}),200)['id']
            def upload():
                return response(client.post('/api/v1/imports/runs',data={'supplier_id':str(supplier)},
                    files={'file':('rc02-synthetic.csv',synthetic_feed())}),200)['id']
            first=upload()
            run=response(client.get(f'/api/v1/imports/runs/{first}'),200)
            assert tuple(run['analysis'][k] for k in ['physical_rows','data_rows','empty_rows'])==(4948,3,4945)
            assert len(run['analysis']['headers'])==27
            # TEMPLATE-01: generated artifacts participate in real FK cascade deletion.
            from app import template_engine as te
            from app.template_models import ImportTemplate, TemplateChunk
            with Session(engine) as db:
                item=te.create_snapshot(db,db.get(ImportRun,first))
                template_id=item.id
                te.build(db,template_id)
                assert db.get(ImportTemplate,template_id).state=='ready_for_enrichment'
            artifact=client.get(f'/api/v1/imports/runs/{first}/templates/{template_id}/xlsx')
            assert artifact.status_code==200 and artifact.content.startswith(b'PK')
            ok('template_0012_mysql_generation_and_download_without_ai')
            plan=response(client.get(f'/api/v1/imports/runs/{first}/deletion'),200)
            assert plan['deletable'] and plan['deletes']['source_file_chunks']>0
            response(client.delete(f'/api/v1/imports/runs/{first}'),200)
            response(client.get(f'/api/v1/imports/runs/{first}'),404)
            response(client.delete(f'/api/v1/imports/runs/{first}'),404)
            second=upload()
            assert second>first,'MySQL must not reuse the deleted import identity'
            assert first not in {r['id'] for r in response(client.get('/api/v1/imports/runs'),200)}
            ok('counts_27_4948_3_4945_and_permanent_delete_reupload_identity')
            with Session(engine) as db:
                assert db.get(ImportTemplate,template_id) is None
                assert not db.scalar(select(TemplateChunk).where(TemplateChunk.template_id==template_id))
                assert db.get(ImportRun,first) is None
                assert db.scalar(select(func.count()).select_from(ImportChunk).where(ImportChunk.run_id==first))==0
            ok('mysql_foreign_keys_allow_safe_chunk_and_run_deletion')
            mapping={'0':'sku','1':'name','2':'gtin','3':'stock','4':'purchase_price','5':'list_price','6':'currency'}
            preview=response(client.post(f'/api/v1/imports/runs/{second}/preview',json={'mapping':mapping,'limit':10}),200)
            assert len(preview['items'])==3 and not preview['has_more']
            assert preview['items'][0]['interpreted']['gtin']['value'] is None
            assert preview['items'][0]['interpreted']['stock']['value']=='-35132'
            approve={'name':'RC02 synthetic','mapping':mapping,'identity_field':'sku','tax_basis':'nettó','currency':'HUF'}
            response(client.post(f'/api/v1/imports/runs/{second}/approve',json=approve),422)
            response(client.post(f'/api/v1/imports/runs/{second}/approve',json={**approve,'financial_approved':True}),200)
            done=response(client.get(f'/api/v1/imports/runs/{second}'),200)
            assert done['state']=='completed' and done['counters']=={'ready':3,'empty':4945}
            response(client.delete(f'/api/v1/imports/runs/{second}'),409)
            with Session(engine) as db:
                rows=list(db.scalars(select(SupplierProduct)))
                assert len(rows)==3
                data={r.data['sku']:r.data for r in rows}
                assert data['RC02-001']['purchase_price']=='405.51'
                assert data['RC02-001']['list_price']=='589.7637795'
                assert data['RC02-001']['stock']=='-35132' and not data['RC02-001'].get('gtin')
                assert data['RC02-003']['gtin']=='5999000000017'
                assert db.scalar(select(func.count()).select_from(Audit).where(Audit.action=='import.delete'))==1
            ok('financial_approval_precision_negative_stock_gtin_and_processed_delete_guard')
            original=client.get(f'/api/v1/imports/runs/{second}/file')
            assert original.status_code==200 and original.content==synthetic_feed()
            rows=response(client.get(f'/api/v1/imports/runs/{second}/rows'),200)
            assert rows['total']==3
            assert rows['items'][0]['normalized']['provenance']['gtin']['raw']=='8,71999E+12'
            ok('original_file_bytes_and_scientific_identifier_provenance_preserved')
            # Unapproved import for permission/isolation tests.
            third=upload()
            saved=client.headers.pop('X-CSRF-Token')
            response(client.delete(f'/api/v1/imports/runs/{third}'),403)
            client.headers['X-CSRF-Token']=saved
            response(client.delete(f'/api/v1/imports/runs/{third}',headers={'Origin':'https://foreign.invalid'}),403)
            login('reader');response(client.delete(f'/api/v1/imports/runs/{third}'),403)
            login('other');response(client.get(f'/api/v1/imports/runs/{third}/deletion'),404)
            response(client.delete(f'/api/v1/imports/runs/{third}'),404)
            login('admin');assert response(client.get(f'/api/v1/imports/runs/{third}'),200)['id']==third
            response(client.post('/api/v1/auth/logout'),204)
            response(client.delete(f'/api/v1/imports/runs/{third}'),401)
            ok('real_tenant_permission_csrf_origin_and_auth_guards')
            with engine.connect() as conn:assert conn.scalar(text('SELECT version_num FROM alembic_version'))=='0012'
            ok('schema_at_0012_with_rc02_guards_preserved')
    finally:
        app.dependency_overrides.clear();app.dependency_overrides.update(prior);engine.dispose()
    print(json.dumps({'mysql':version,'checks':len(checks),'failed':0,'fixture':'synthetic_27_columns_3_products_4945_empty','reference_access':False}))

if __name__=='__main__':main()
