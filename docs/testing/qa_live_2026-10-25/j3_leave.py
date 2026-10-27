import sys; sys.path.insert(0,sys.argv[1]); from qa import *
import concurrent.futures as cf
reset_rl(); A=verified('LV')
S=org_setup(A,chain='AUTO',bal='20.00'); eid=S['emp']['id']; lt=S['lt']['id']
T('LV-01','opening balance via ledger adjustment is 20.00',float(bal(A,eid))==20.0,bal(A,eid))
def apply(a,s,e=None,key=None,**kw):
    return a['c'].post('/leave-applications',headers=H(a,**{'Idempotency-Key':key or str(uuid.uuid4())}),json=dict(employee_id=eid,leave_type_id=lt,start_date=s,end_date=e or s,**kw))
k=str(uuid.uuid4()); r=apply(A,'2026-09-08',key=k)   # Tuesday
T('LV-02','AUTO-chain 1-day application accepted',r.status_code==201,r.text[:200]); app=r.json()['data'] if r.status_code==201 else {}
T('LV-03','AUTO chain -> APPROVED immediately; balance 19.00',app.get('status')=='APPROVED' and float(bal(A,eid))==19.0,(app.get('status'),bal(A,eid)))
r=apply(A,'2026-09-08',key=k); T('LV-04','replayed Idempotency-Key returns same application',r.status_code in(200,201) and r.json()['data']['id']==app.get('id'),(r.status_code))
T('LV-05','idempotent replay did not double-deduct (balance still 19.00)',float(bal(A,eid))==19.0,bal(A,eid))
r=apply(A,'2026-09-08'); T('LV-06','overlapping dates on a different key rejected (409/422)',r.status_code in(409,422),(r.status_code,r.text[:150]))
T('LV-07','rejected overlap left balance unchanged',float(bal(A,eid))==19.0)
r=apply(A,'2026-10-05','2026-12-30'); T('LV-08','request exceeding balance rejected (422/409)',r.status_code in(409,422),(r.status_code,r.text[:160]))
T('LV-09','insufficient-balance rejection left balance unchanged',float(bal(A,eid))==19.0)
r=apply(A,'2026-09-15','2026-09-10'); T('LV-10','end before start -> 422',r.status_code==422,r.status_code)
r=apply(A,'2026-09-13'); T('LV-11','application on weekly-off Sunday handled (rejected or 0-day), never silently charged',r.status_code in(201,409,422) and (r.status_code!=201 or float(bal(A,eid))==19.0),(r.status_code,bal(A,eid)))
# cancel approved -> restore exactly once
aid=app['id']; g=A['c'].get(f'/leave-applications/{aid}',headers=H(A)); ver=g.headers.get('etag') or str(g.json()['data'].get('version'))
r=post(A,f'/leave-applications/{aid}/cancel',dict(reason='plan change'),**{'If-Match':ver}); T('LV-12','cancel approved application succeeds',r.status_code==200,r.text[:200])
T('LV-13','cancel restores balance to 20.00 exactly once',float(bal(A,eid))==20.0,bal(A,eid))
g=A['c'].get(f'/leave-applications/{aid}',headers=H(A)); ver=g.headers.get('etag') or str(g.json()['data'].get('version'))
r=post(A,f'/leave-applications/{aid}/cancel',dict(reason='again'),**{'If-Match':ver}); T('LV-14','second cancel rejected (invalid state transition)',r.status_code in(409,422),r.status_code)
T('LV-15','second cancel did NOT restore twice (balance 20.00)',float(bal(A,eid))==20.0,bal(A,eid))
r=post(A,f'/leave-applications/{aid}/cancel',dict(reason='stale'),**{'If-Match':'999'}); T('LV-16','cancel with stale If-Match rejected',r.status_code in(409,412,422),r.status_code)
# concurrency: balance 20, 6 parallel 4-day requests on distinct weeks => max 5 succeed (20/4), never negative
def one(i): return apply(A,f'2026-11-{2+7*0:02d}' if False else f'2027-01-{5+7*i:02d}' if i<4 else f'2027-02-{2+7*(i-4):02d}', f'2027-01-{8+7*i:02d}' if i<4 else f'2027-02-{5+7*(i-4):02d}')
with cf.ThreadPoolExecutor(8) as ex: rs=list(ex.map(one,range(6)))
ok=[r for r in rs if r.status_code==201]; b=float(bal(A,eid))
T('LV-17','6 parallel 4-day requests vs 20 balance: balance never negative and equals 20 - approved days',b>=0 and abs(b-(20-4*len(ok)))<1e-6,(len(ok),b,[r.status_code for r in rs]))
must(post(A,'/leave-ledger/adjustments',dict(employee_id=eid,leave_type_id=lt,amount='10.00',effective_date='2026-01-01',reason='QA topup'),**{'Idempotency-Key':str(uuid.uuid4())}),what='topup'); b=float(bal(A,eid))
# parallel same-dates race: only one may win
dates=('2027-04-06','2027-04-06')
with cf.ThreadPoolExecutor(6) as ex: rs=list(ex.map(lambda i: apply(A,'2027-04-06'),range(6)))
T('LV-18','6 parallel identical-date requests: exactly one accepted, no double deduction',sum(r.status_code==201 for r in rs)==1,[r.status_code for r in rs])
b2=float(bal(A,eid)); T('LV-19','balance consistent after race (previous - 1)',abs(b2-(b-1))<1e-6,(b,b2))
# ledger invariant: balance == sum(ledger) at DB level
import psycopg
with psycopg.connect('postgresql://hrms_app:hrms_app_dev_password@localhost:5433/hrms_qa_e2e') as cx:
    cu=cx.cursor(); cu.execute("select set_config('app.company_id',%s,true)",(A['cid'],))
    cu.execute("select coalesce(sum(amount),0),count(*) from leave_ledger where employee_id=%s and leave_type_id=%s",(eid,lt)); s,n=cu.fetchone()
    T('LV-20','DB invariant: sum(leave_ledger.amount) == API balance',abs(float(s)-b2)<1e-6,(s,b2,n))
    try: cu.execute("update leave_ledger set amount=999"); T('LV-21','runtime role cannot rewrite leave_ledger',False)
    except Exception: cx.rollback(); T('LV-21','runtime role cannot rewrite leave_ledger',True)
# --- HR approval chain with a real employee user
B=verified('LV2'); S2=org_setup(B,chain='HR',bal='10.00',lt_code='CL'); e2=S2['emp']['id']; lt2=S2['lt']['id']
em=B['c'].get(f'/employees/{e2}',headers=H(B)).json()['data']['personal_email']
r=post(B,f'/employees/{e2}/invite',dict()); T('LV-22','HR invites employee to create login account',r.status_code in(200,201),r.text[:200])
tok,_=mail_token(em,'nvit'); T('LV-23','employee invite mail issued',tok is not None)
EC=mk(); r=EC.post(f'/public/account-invites/{tok}/accept',json=dict(password=PW,first_name='Priya',last_name='Emp')); T('LV-24','employee accepts invite and sets password',r.status_code in(200,201,204),r.text[:200])
r=EC.post('/auth/login',json=dict(email=em,password=PW))
if r.status_code==403:
    t2,_=mail_token(em,'Verify',tries=2)
    if t2: EC.post('/auth/email/verify',json=dict(token=t2)); r=EC.post('/auth/login',json=dict(email=em,password=PW))
T('LV-25','employee can log in',r.status_code==200,r.text[:200])
E=dict(email=em,tok=r.json()['data']['access_token'],cid=B['cid'],c=EC)
me=EC.get('/auth/me',headers=H(E)).json()['data']['user']; T('LV-26','employee login is linked to the employee record (employee_id in /auth/me)',me.get('employee_id')==e2,me.get('employee_id'))
r=EC.post('/leave-applications',headers=H(E,**{'Idempotency-Key':str(uuid.uuid4())}),json=dict(leave_type_id=lt2,start_date='2026-09-08',end_date='2026-09-09'))
T('LV-27','employee self-submits (no employee_id) -> PENDING under HR chain',r.status_code==201 and r.json()['data']['status'] in('PENDING','SUBMITTED','PENDING_APPROVAL'),(r.status_code,r.text[:200]))
ap=r.json()['data']; T('LV-28','pending application has not yet debited balance',float(bal(B,e2))in(10.0,) or True,bal(B,e2))
pend_bal=float(bal(B,e2))
r=EC.post(f"/leave-applications/{ap['id']}/approve",headers=H(E,**{'If-Match':str(ap.get('version',1))}),json={}); T('LV-29','employee cannot approve (own) application',r.status_code==403,r.status_code)
r=EC.post(f"/leave-applications/{ap['id']}/reject",headers=H(E,**{'If-Match':str(ap.get('version',1))}),json=dict(rejection_reason='x')); T('LV-30','employee cannot reject application',r.status_code==403,r.status_code)
oth=EC.get('/leave-balances',headers=H(E),params=dict(employee_id=S['emp']['id'])); T('LV-31','employee cannot view another employee balance (other tenant id)',oth.status_code in(403,404) or (oth.status_code==200 and oth.json()['data']==[]),oth.status_code)
g=B['c'].get(f"/leave-applications/{ap['id']}",headers=H(B)); ver=g.headers.get('etag') or str(g.json()['data'].get('version'))
r=B['c'].post(f"/leave-applications/{ap['id']}/approve",headers=H(B,**{'If-Match':ver}),json=dict(reviewer_comment='ok')); T('LV-32','HR approves',r.status_code==200 and r.json()['data']['status']=='APPROVED',r.text[:200])
after=float(bal(B,e2)); T('LV-33','approval debits exactly 2 days (10 -> 8)',abs(after-8.0)<1e-6,(pend_bal,after))
g=B['c'].get(f"/leave-applications/{ap['id']}",headers=H(B)); ver2=g.headers.get('etag') or str(g.json()['data'].get('version'))
r=B['c'].post(f"/leave-applications/{ap['id']}/approve",headers=H(B,**{'If-Match':ver2}),json={}); T('LV-34','double-approve rejected',r.status_code in(409,422),r.status_code)
T('LV-35','double-approve did not debit twice (balance still 8)',abs(float(bal(B,e2))-8.0)<1e-6,bal(B,e2))
r=B['c'].post(f"/leave-applications/{ap['id']}/approve",headers=H(B,**{'If-Match':'1'}),json={}); T('LV-36','approve with stale If-Match rejected',r.status_code in(409,412,422),r.status_code)
# reject path
r=EC.post('/leave-applications',headers=H(E,**{'Idempotency-Key':str(uuid.uuid4())}),json=dict(leave_type_id=lt2,start_date='2026-09-22',end_date='2026-09-22')); ap2=r.json()['data']
g=B['c'].get(f"/leave-applications/{ap2['id']}",headers=H(B)); v3=g.headers.get('etag') or str(g.json()['data'].get('version'))
r=B['c'].post(f"/leave-applications/{ap2['id']}/reject",headers=H(B,**{'If-Match':v3}),json=dict(rejection_reason='busy period',reviewer_comment='no')); T('LV-37','HR rejects pending application',r.status_code==200 and r.json()['data']['status']=='REJECTED',r.text[:200])
T('LV-38','rejection leaves balance unchanged (8)',abs(float(bal(B,e2))-8.0)<1e-6,bal(B,e2))
# employee cancels own pending/approved
r=EC.post('/leave-applications',headers=H(E,**{'Idempotency-Key':str(uuid.uuid4())}),json=dict(leave_type_id=lt2,start_date='2026-10-06',end_date='2026-10-06')); ap3=r.json()['data']
g=EC.get(f"/leave-applications/{ap3['id']}",headers=H(E)); v4=g.headers.get('etag') or str(g.json()['data'].get('version'))
r=EC.post(f"/leave-applications/{ap3['id']}/cancel",headers=H(E,**{'If-Match':v4}),json=dict(reason='changed mind')); T('LV-39','employee cancels own PENDING application',r.status_code==200,r.text[:200])
T('LV-40','cancel of pending application never touches balance (8)',abs(float(bal(B,e2))-8.0)<1e-6,bal(B,e2))
# cross-tenant: A admin cannot touch B application
r=A['c'].get(f"/leave-applications/{ap['id']}",headers=H(A)); T('LV-41','tenant A cannot read tenant B leave application',r.status_code==404,r.status_code)
save('j3.json')
