import httpx,json,uuid,os,re
B='http://127.0.0.1:18000/v1'
PW='Qa-Pass-123456!'
RES=[]
def T(tid,desc,ok,detail=''):
    RES.append((tid,desc,'PASS' if ok else 'FAIL',str(detail)[:300]))
    print(('PASS' if ok else 'FAIL'),tid,desc,'' if ok else '| '+str(detail)[:300])
def mk(): return httpx.Client(base_url=B,timeout=30)
def reg(tag):
    c=mk(); e=f"qa-{tag}-{uuid.uuid4().hex[:6]}@example.com"
    r=c.post('/companies/register',json=dict(name=f'QA {tag} {uuid.uuid4().hex[:4]}',admin_first_name='Qa',admin_last_name=tag,admin_email=e,admin_password=PW))
    d=r.json()['data']
    return dict(email=e,tok=d['access_token'],cid=d['company_id'],c=c,cookies=dict(r.cookies))
def H(a,**kw):
    h={'Authorization':'Bearer '+a['tok'],'X-Company-Id':a['cid']}; h.update(kw); return h
import time,hmac,hashlib,base64
LOG=os.path.join(os.path.dirname(__file__),'api.log')
def mail_token(email,subject,tries=10):
    for _ in range(tries):
        t=open(LOG,errors='ignore').read()
        parts=t.split('--- [dev email, not sent] ')
        for p in reversed(parts):
            if p.startswith(f'to={email.lower()} ') or p.startswith(f'to={email} '):
                if subject in p.split('\n')[0]:
                    m=re.search(r'https?://[^\s]+/([A-Za-z0-9_\-]{20,})\s',p)
                    if m: return m.group(1),p
        time.sleep(0.5)
    return None,None
def verified(tag):
    a=reg(tag); tok,_=mail_token(a['email'],'Verify')
    r=a['c'].post('/auth/email/verify',json=dict(token=tok)); assert r.status_code in(200,204),r.text
    r=a['c'].post('/auth/login',json=dict(email=a['email'],password=PW)); assert r.status_code==200,r.text
    a['tok']=r.json()['data']['access_token']; return a
def b64(d): return base64.urlsafe_b64encode(d).rstrip(b'=').decode()
def forge(payload,secret='qa-access-secret-min-16-chars',alg='HS256'):
    h=b64(json.dumps({'alg':alg,'typ':'JWT'}).encode()); p=b64(json.dumps(payload).encode())
    if alg=='none': return f'{h}.{p}.'
    s=b64(hmac.new(secret.encode(),f'{h}.{p}'.encode(),hashlib.sha256).digest()); return f'{h}.{p}.{s}'
def save(name):
    json.dump(RES,open(os.path.join(os.path.dirname(__file__),name),'w'),indent=1)
import subprocess
def reset_rl():
    subprocess.run("redis-cli -p 6380 -n 2 --scan --pattern 'ratelimit:*' | xargs -r redis-cli -p 6380 -n 2 del >/dev/null",shell=True)
def invited(adm,role,tag):
    email=f"qa-{tag}-{uuid.uuid4().hex[:6]}@example.com"
    r=adm['c'].post('/users/invite',headers=H(adm),json=dict(email=email,role_code=role)); assert r.status_code in(200,201),r.text
    tok,_=mail_token(email,'nvit'); assert tok,'no invite mail'
    c=mk(); r=c.post(f'/public/account-invites/{tok}/accept',json=dict(password=PW,first_name='Inv',last_name=tag)); assert r.status_code in(200,201,204),r.text
    r=c.post('/auth/login',json=dict(email=email,password=PW))
    if r.status_code==403:
        t2,_=mail_token(email,'Verify',tries=2)
        if t2: c.post('/auth/email/verify',json=dict(token=t2)); r=c.post('/auth/login',json=dict(email=email,password=PW))
    assert r.status_code==200,r.text
    d=r.json()['data']; return dict(email=email,tok=d['access_token'],cid=adm['cid'],c=c)
def post(a,path,body=None,**hd):
    return a['c'].post(path,headers=H(a,**hd),json=body if body is not None else {})
def must(r,code=(200,201),what=''):
    assert r.status_code in code,(what,r.status_code,r.text[:300]); return r.json().get('data')
def org_setup(A,chain='AUTO',bal='20.00',lt_code='EL'):
    e=must(post(A,'/employees',dict(first_name='Priya',last_name='Emp',personal_email=f'emp-{uuid.uuid4().hex[:6]}@example.com'),**{'Idempotency-Key':str(uuid.uuid4())}),what='emp')
    le=must(post(A,'/legal-entities',dict(name='QA Legal Entity')),what='le')
    must(post(A,f"/employees/{e['id']}/employments",dict(legal_entity_id=le['id'],joining_date='2024-01-01')),what='employment')
    lt=must(post(A,'/leave-types',dict(code=lt_code,name='Earned Leave')),what='lt')
    wop=must(post(A,'/weekly-off-patterns',dict(name='Sun Off',pattern_kind='FIXED_WEEKDAYS',rules=[dict(weekday=6,off_fraction='1.00')])),what='wop')
    wc=must(post(A,'/work-calendars',dict(name='Cal',weekly_off_pattern_id=wop['id'])),what='wc')
    must(post(A,'/policy-assignments',dict(policy_kind='WORK_CALENDAR',policy_id=wc['id'],scope_type='COMPANY',effective_from='2024-01-01')),what='cal-assign')
    pol=must(post(A,'/leave-policies',dict(name='Std',leave_type_id=lt['id'])),what='pol')
    v=must(post(A,f"/leave-policies/{pol['id']}/versions",dict(effective_from='2024-01-01',approval_chain=chain,half_day_allowed=True,sandwich_rule_enabled=True,reason_required=False)),what='ver')
    must(post(A,f"/leave-policies/{pol['id']}/versions/{v['id']}/publish",{},**{'If-Match':'1'}),what='publish')
    must(post(A,'/policy-assignments',dict(policy_kind='LEAVE_POLICY',policy_id=pol['id'],leave_type_id=lt['id'],scope_type='COMPANY',effective_from='2024-01-01')),what='pol-assign')
    must(post(A,'/leave-ledger/adjustments',dict(employee_id=e['id'],leave_type_id=lt['id'],amount=bal,effective_date='2026-01-01',reason='QA opening'),**{'Idempotency-Key':str(uuid.uuid4())}),what='balance')
    return dict(emp=e,le=le,lt=lt,pol=pol)
def bal(A,eid):
    r=A['c'].get('/leave-balances',headers=H(A),params=dict(employee_id=eid)); return r.json()['data'][0]['balance']
def emp_user(A,eid):
    em=A['c'].get(f'/employees/{eid}',headers=H(A)).json()['data']['personal_email']
    r=post(A,f'/employees/{eid}/invite',{}); assert r.status_code in(200,201),r.text
    tok,_=mail_token(em,'nvit'); EC=mk()
    r=EC.post(f'/public/account-invites/{tok}/accept',json=dict(password=PW,first_name='Priya',last_name='Emp')); assert r.status_code in(200,201,204),r.text
    r=EC.post('/auth/login',json=dict(email=em,password=PW))
    if r.status_code==403:
        t2,_=mail_token(em,'Verify',tries=2)
        if t2: EC.post('/auth/email/verify',json=dict(token=t2)); r=EC.post('/auth/login',json=dict(email=em,password=PW))
    assert r.status_code==200,r.text
    return dict(email=em,tok=r.json()['data']['access_token'],cid=A['cid'],c=EC)
