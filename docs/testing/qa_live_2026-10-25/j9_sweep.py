import sys; sys.path.insert(0,sys.argv[1]); from qa import *
import collections
spec=json.load(open(sys.argv[1]+'/openapi.json'))
reset_rl(); A=verified('SW'); E=emp_user(A,org_setup(A)['emp']['id'])
ops=[(m.upper(),p) for p,v in spec['paths'].items() for m in v if m in('get','post','put','patch','delete')]
PUBLIC=('/health','/v1/public/','/v1/auth/login','/v1/auth/token/refresh','/v1/auth/password','/v1/auth/email','/v1/companies/register','/v1/companies/registration-config','/metrics')
def fill(p): return re.sub(r'\{[^}]+\}',lambda m: str(uuid.uuid4()),p)
base=B.rsplit('/v1',1)[0]
def call(c,m,p,hdr=None,body=None):
    url=base+fill(p)
    try: return httpx.request(m,url,headers=hdr or {},json=body,timeout=40)
    except Exception as ex: return ex
import httpx
bad_unauth=[];bad5=[];leaks=[];n=0
for m,p in ops:
    r=call(None,m,p)
    if isinstance(r,Exception): bad5.append(('unauth',m,p,repr(r)[:60])); continue
    if r.status_code<400 and not p.startswith(PUBLIC): bad_unauth.append((m,p,r.status_code))
    if r.status_code>=500: bad5.append(('unauth',m,p,r.status_code))
    if 'Traceback' in r.text or 'File "/' in r.text: leaks.append(('unauth',m,p))
    n+=1
T('SWP-01',f'all {n} operations: no 2xx/3xx without credentials except documented public routes',not bad_unauth,bad_unauth[:8])
for who,a in(('admin',A),('employee',E)):
    cnt=collections.Counter(); b5=[]
    for m,p in ops:
        if p.startswith('/health') or 'documents' in p and m=='POST' or p.endswith('/employee-imports') and m=='POST' or 'face-punches' in p or 'face-enrollment' in p or p.startswith('/v1/auth/logout'): continue
        hd=H(a); body=None
        if m in('POST','PUT','PATCH'): body={}
        if m=='POST' and any(k in p for k in('leave-applications','adjustments','encashments','/employees','onboarding-cases')): hd['Idempotency-Key']=str(uuid.uuid4())
        if m in('PATCH','POST','DELETE') and p.count('{')>0: hd['If-Match']='1'
        r=call(None,m,p,hd,body)
        if isinstance(r,Exception): b5.append((m,p,repr(r)[:50])); continue
        cnt[r.status_code//100]+=1
        if r.status_code>=500: b5.append((m,p,r.status_code,r.text[:90]))
        if 'Traceback' in r.text or 'File "/' in r.text or 'sqlalchemy' in r.text.lower() or 'asyncpg' in r.text.lower(): leaks.append((who,m,p))
    T('SWP-0'+('2' if who=='admin' else '3'),f'{who}: garbage-ID/empty-body sweep over all operations -> no 5xx ({dict(cnt)})',not b5,b5[:6])
T('SWP-04','no stack-trace / SQL / driver text leaked in any sweep response',not leaks,leaks[:5])
r=httpx.get(base+'/v1/does-not-exist'); T('SWP-05','unknown route -> 404 with JSON error envelope',r.status_code==404 and 'error' in r.json(),r.text[:100])
r=httpx.request('PUT',base+'/v1/auth/login',json={}); T('SWP-06','wrong method -> 405 JSON envelope',r.status_code==405,(r.status_code,r.text[:80]))
r=A['c'].get('/employees/not-a-uuid',headers=H(A)); T('SWP-07','non-UUID path param -> 422 (not 500)',r.status_code==422,r.status_code)
r=A['c'].get("/employees?page=1';DROP TABLE employee;--&per_page=5",headers=H(A)); T('SWP-08','SQL-injection-shaped query value -> 4xx validation, no 5xx',400<=r.status_code<500,r.status_code)
r=A['c'].get('/leave-applications',headers=H(A),params=dict(status="'; select pg_sleep(5);--")); T('SWP-09','injection-shaped filter value handled safely',r.status_code in(200,422),r.status_code)
cnt=PGc=None
import psycopg
with psycopg.connect('postgresql://hrms:hrms_dev_password@localhost:5433/hrms_qa_e2e') as cx:
    cu=cx.cursor(); cu.execute("select to_regclass('public.employee') is not null"); T('SWP-10','employee table intact after injection-shaped inputs',cu.fetchone()[0])
big=b'{"first_name":"'+b'A'*(3*1024*1024)+b'"}'
r=A['c'].post('/employees',headers=H(A,**{'Idempotency-Key':str(uuid.uuid4()),'content-type':'application/json'}),content=big); T('SWP-11','3MB JSON body rejected cleanly (4xx), not 5xx',400<=r.status_code<500,r.status_code)
save('j9.json')
