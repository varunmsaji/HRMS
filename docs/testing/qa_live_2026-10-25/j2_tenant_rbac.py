import sys; sys.path.insert(0,sys.argv[1]); from qa import *
reset_rl()
A=verified('TA'); B=verified('TB'); c=A['c']
def mkemp(a,first,key=None,**kw):
    return a['c'].post('/employees',headers=H(a,**{'Idempotency-Key':key or str(uuid.uuid4())}),json=dict(first_name=first,last_name='Test',**kw))
# --- employee CRUD
r=mkemp(A,'Asha',personal_email='asha@example.com'); T('EMP-01','create employee -> 201 with generated code',r.status_code==201 and r.json()['data']['employee_code'].startswith('EMP-'),r.text[:200])
e1=r.json()['data']; 
k=str(uuid.uuid4()); r1=mkemp(A,'Idem',key=k); r2=mkemp(A,'Idem',key=k)
T('EMP-02','replayed Idempotency-Key returns same employee, no duplicate',r1.status_code==201 and r2.status_code in(200,201) and r1.json()['data']['id']==r2.json()['data']['id'],(r1.status_code,r2.status_code))
r3=mkemp(A,'Different',key=k); T('EMP-03','same Idempotency-Key with different body rejected (409/422)',r3.status_code in(409,422),r3.status_code)
T('EMP-04','missing first_name -> 422 field error',c.post('/employees',headers=H(A,**{'Idempotency-Key':str(uuid.uuid4())}),json=dict(last_name='x')).status_code==422)
T('EMP-05','invalid email -> 422',mkemp(A,'Bad',personal_email='not-an-email').status_code==422)
T('EMP-06','future/garbage date_of_birth -> 422',mkemp(A,'Bad',date_of_birth='31-31-2000').status_code==422)
for i in range(6): mkemp(A,f'Bulk{i}')
r=c.get('/employees?page=1&per_page=3',headers=H(A)); j=r.json()
T('EMP-07','pagination honours per_page and reports total',len(j['data'])==3 and j['pagination']['total']>=8,j.get('pagination'))
ids=set(); 
for p in (1,2,3):
    ids|={x['id'] for x in c.get(f'/employees?page={p}&per_page=3',headers=H(A)).json()['data']}
T('EMP-08','pages 1-3 are disjoint (no dup/skip) and cover 8 employees',len(ids)==8,len(ids))
T('EMP-09','per_page above max / page=0 handled (422 or clamped, never 500)',c.get('/employees?per_page=100000',headers=H(A)).status_code in(200,422) and c.get('/employees?page=0',headers=H(A)).status_code in(200,422))
r=c.get(f"/employees/{e1['id']}",headers=H(A)); et=r.headers.get('etag'); ver=r.json()['data'].get('version')
T('EMP-10','GET employee returns ETag/version for optimistic concurrency',et is not None or ver is not None,(et,ver))
ifm=et or str(ver)
r=c.patch(f"/employees/{e1['id']}",headers=H(A,**{'If-Match':ifm}),json=dict(first_name='Asha2')); T('EMP-11','PATCH with correct If-Match updates',r.status_code==200 and r.json()['data']['first_name']=='Asha2',(r.status_code,r.text[:150]))
r=c.patch(f"/employees/{e1['id']}",headers=H(A,**{'If-Match':ifm}),json=dict(first_name='Stale')); T('EMP-12','PATCH with STALE If-Match rejected (409/412), data unchanged',r.status_code in(409,412) and c.get(f"/employees/{e1['id']}",headers=H(A)).json()['data']['first_name']=='Asha2',r.status_code)
r=c.patch(f"/employees/{e1['id']}",headers=H(A),json=dict(first_name='NoHdr')); T('EMP-13','PATCH without If-Match rejected (428/400/409/412/422)',r.status_code in(400,409,412,422,428),r.status_code)
# --- tenant isolation (API)
T('TEN-01','B cannot GET A employee by id (404, not 403/200)',B['c'].get(f"/employees/{e1['id']}",headers=H(B)).status_code==404)
r=B['c'].patch(f"/employees/{e1['id']}",headers=H(B,**{'If-Match':'1'}),json=dict(first_name='Hacked')); T('TEN-02','B cannot PATCH A employee',r.status_code in(404,403,412),r.status_code)
r=B['c'].delete(f"/employees/{e1['id']}",headers=H(B,**{'If-Match':'1'})); T('TEN-03','B cannot DELETE A employee',r.status_code in(404,403,412),r.status_code)
T('TEN-04','A employee unchanged after B attempts',c.get(f"/employees/{e1['id']}",headers=H(A)).json()['data']['first_name']=='Asha2')
T('TEN-05','B list contains none of A employees',not ({x['id'] for x in B['c'].get('/employees?per_page=100',headers=H(B)).json()['data']}&ids))
r=c.get('/employees',headers={'Authorization':'Bearer '+A['tok'],'X-Company-Id':B['cid']}); T('TEN-06','A token + B X-Company-Id header -> denied',r.status_code in(401,403,404),r.status_code)
r=c.get('/employees',headers={'Authorization':'Bearer '+A['tok'],'X-Company-Id':str(uuid.uuid4())}); T('TEN-07','A token + random company id -> denied',r.status_code in(401,403,404),r.status_code)
r=c.get('/employees',headers={'Authorization':'Bearer '+A['tok']}); T('TEN-08','missing X-Company-Id handled safely (never another tenant data)',r.status_code in(200,400,403,422) and (r.status_code!=200 or all(x['company_id']==A['cid'] for x in r.json()['data'])),r.status_code)
T('TEN-09','A reading B company profile via /auth/companies/{id} denied',c.get(f"/auth/companies/{B['cid']}",headers=H(A)).status_code in(403,404))
# every org resource list is tenant-scoped
leaks=[]
for res in ['branches','departments','designations','grades','legal-entities','shifts','holiday-calendars','work-calendars','leave-types','leave-policies','attendance-policies']:
    ra=c.post(f'/{res}',headers=H(A),json={}) if False else None
for res in ['branches','departments','designations','grades','legal-entities','shifts','leave-types','leave-policies','attendance-policies','payroll/pay-runs','users']:
    ra=A['c'].get(f'/{res}',headers=H(A)); rb=B['c'].get(f'/{res}',headers=H(B))
    if ra.status_code!=200 or rb.status_code!=200: leaks.append((res,ra.status_code,rb.status_code)); continue
    ia={x.get('id') or x.get('user_id') for x in ra.json()['data']} if isinstance(ra.json()['data'],list) else set()
    ib={x.get('id') or x.get('user_id') for x in rb.json()['data']} if isinstance(rb.json()['data'],list) else set()
    if ia&ib: leaks.append((res,'OVERLAP'))
T('TEN-10','11 list endpoints return 200 for both tenants with no overlapping rows',not leaks,leaks)
# --- RBAC
E=invited(A,'EMPLOYEE','emp'); 
T('RBAC-01','EMPLOYEE role: cannot create employees',E['c'].post('/employees',headers=H(E,**{'Idempotency-Key':str(uuid.uuid4())}),json=dict(first_name='X',last_name='Y')).status_code==403)
r=E['c'].get('/employees?per_page=100',headers=H(E)); T('RBAC-02','EMPLOYEE role: employee list is not the whole directory',r.status_code in(403,200) and (r.status_code==403 or len(r.json()['data'])<=1),(r.status_code,len(r.json().get('data',[])) if r.status_code==200 else ''))
T('RBAC-03','EMPLOYEE role: cannot read another employee record',E['c'].get(f"/employees/{e1['id']}",headers=H(E)).status_code in(403,404))
T('RBAC-04','EMPLOYEE role: cannot PATCH employee',E['c'].patch(f"/employees/{e1['id']}",headers=H(E,**{'If-Match':'1'}),json=dict(first_name='x')).status_code in(403,404))
T('RBAC-05','EMPLOYEE role: cannot invite users',E['c'].post('/users/invite',headers=H(E),json=dict(email='z%s@example.com'%uuid.uuid4().hex[:5],role_code='COMPANY_ADMIN')).status_code==403)
me=E['c'].get('/auth/me',headers=H(E)).json()['data']['user']
T('RBAC-06','EMPLOYEE role: cannot self-escalate roles',E['c'].patch(f"/users/{me['id']}/roles",headers=H(E),json=dict(role_codes=['COMPANY_ADMIN'])).status_code==403)
for path,tid in [('/payroll/pay-runs','RBAC-07'),('/users','RBAC-08'),('/employee-imports/'+str(uuid.uuid4()),'RBAC-09'),('/payroll/salary-structures','RBAC-10'),('/onboarding-cases','RBAC-11')]:
    r=E['c'].get(path,headers=H(E)); T(tid,f'EMPLOYEE role: GET {path} denied',r.status_code==403,r.status_code)
T('RBAC-12','EMPLOYEE role: cannot create leave type / org structure',all(E['c'].post(p,headers=H(E),json={'name':'x','code':'x'}).status_code in(403,) for p in ['/leave-types','/branches','/departments']))
T('RBAC-13','EMPLOYEE role: cannot update company profile',E['c'].patch('/companies/current',headers=H(E),json=dict(name='Pwn')).status_code==403)
T('RBAC-14','platform console routes closed to tenant admin',all(A['c'].get(p,headers=H(A)).status_code in(401,403,404) for p in ['/platform/companies','/platform/logs','/platform/emails']),[A['c'].get(p,headers=H(A)).status_code for p in ['/platform/companies','/platform/logs','/platform/emails']])
R=invited(A,'HR_ADMIN','hr')
T('RBAC-15','HR_ADMIN can create employees',R['c'].post('/employees',headers=H(R,**{'Idempotency-Key':str(uuid.uuid4())}),json=dict(first_name='ByHR',last_name='X')).status_code==201)
T('RBAC-16','HR_ADMIN cannot grant COMPANY_ADMIN (no privilege escalation)',R['c'].patch(f"/users/{me['id']}/roles",headers=H(R),json=dict(role_codes=['COMPANY_ADMIN'])).status_code in(403,422,409),R['c'].patch(f"/users/{me['id']}/roles",headers=H(R),json=dict(role_codes=['COMPANY_ADMIN'])).status_code)
# audit trail
save('j2.json')
# --- DB-level (hrms_app = the non-superuser runtime role, RLS enforced)
import psycopg
def app(): return psycopg.connect('postgresql://hrms_app:hrms_app_dev_password@localhost:5433/hrms_qa_e2e',autocommit=False)
with app() as cx:
    cu=cx.cursor()
    cu.execute("select count(*) from employee"); n0=cu.fetchone()[0]
    T('RLS-01','hrms_app with no tenant context sees 0 employee rows',n0==0,n0)
    cu.execute("select set_config('app.current_company_id',%s,true)",(A['cid'],)) if False else None
    cu.execute("select current_setting('app.current_company_id',true)")
with app() as cx:
    cu=cx.cursor()
    cu.execute("select prosrc from pg_proc limit 0")
    # discover the GUC the app uses
    g='app.company_id'
    cu.execute("select set_config(%s,%s,true)",(g,A['cid'])); cu.execute("select count(*),count(distinct company_id),min(company_id::text) from employee"); n,d,m=cu.fetchone()
    T('RLS-02','with tenant A context, only tenant A employee rows visible',n>=9 and d==1 and m==A['cid'],(n,d))
    cu.execute("select count(*) from employee where company_id=%s",(B['cid'],)); T('RLS-03','tenant A context cannot read tenant B rows even by explicit WHERE',cu.fetchone()[0]==0)
    try:
        cu.execute("insert into branch(id,company_id,code,name) values (gen_random_uuid(),%s,'X','x')",(B['cid'],)); ok=False
    except Exception as ex: ok=True; cx.rollback()
    T('RLS-04','tenant A context cannot INSERT a row for tenant B (WITH CHECK)',ok)
with app() as cx:
    cu=cx.cursor()
    cu.execute("select set_config(%s,%s,true)",(g,A['cid']))
    try: cu.execute("update employee set first_name='pwn' where company_id=%s",(B['cid'],)); n=cu.rowcount
    except Exception: n=0; cx.rollback()
    T('RLS-05','tenant A context cannot UPDATE tenant B rows (0 rows affected)',n==0,n)
    try: cu.execute("select count(*) from audit_log"); T('RLS-06','audit_log readable by runtime role',True)
    except Exception as ex: cx.rollback(); T('RLS-06','audit_log readable by runtime role',False,ex)
with app() as cx:
    cu=cx.cursor(); cu.execute("select set_config(%s,%s,true)",(g,A['cid']))
    try:
        cu.execute("delete from audit_log"); T('RLS-07','audit_log is append-only for the runtime role (DELETE blocked)',cu.rowcount==0,cu.rowcount)
    except Exception as ex: cx.rollback(); T('RLS-07','audit_log is append-only for the runtime role (DELETE blocked)',True)
# audit events for the mutations performed
with app() as cx:
    cu=cx.cursor(); cu.execute("select set_config(%s,%s,true)",(g,A['cid']))
    cu.execute("select action,count(*) from audit_log group by 1 order by 2 desc limit 12"); rows=cu.fetchall()
    T('AUD-01','audit_log has entries for the tenant mutations (employee create/update, role/invite)',len(rows)>0 and any('EMPLOYEE' in (r[0] or '').upper() for r in rows),rows[:8])
save('j2.json')
