import sys; sys.path.insert(0,sys.argv[1]); from qa import *
import datetime as dt, concurrent.futures as cf
reset_rl(); A=verified('AT'); S=org_setup(A); eid=S['emp']['id']; E=emp_user(A,eid); B=verified('AT2')
def me(direction='IN',key=None,**kw): return E['c'].post('/attendance/punches/me',headers=H(E),json=dict(direction=direction,reference='WEB',idempotency_key=key or str(uuid.uuid4()),**kw))
k=str(uuid.uuid4()); r=me('IN',k); p=r.json()['data'] if r.status_code==201 else {}
now=dt.datetime.now(dt.timezone.utc); pt=dt.datetime.fromisoformat(p['punch_time'].replace('Z','+00:00')) if p else now
T('ATT-01','self punch IN -> 201, bound to caller employee, server timestamp (within 30s of now)',r.status_code==201 and p['employee_id']==eid and abs((pt-now).total_seconds())<30,(r.status_code))
r2=me('IN',k); T('ATT-02','replayed idempotency_key returns the same punch (no duplicate)',r2.status_code in(200,201) and r2.json()['data']['id']==p.get('id'))
n=lambda: len(E['c'].get('/attendance/punches',headers=H(E),params=dict(employee_id=eid)).json()['data'])
T('ATT-03','punch history shows exactly one punch after replay',n()==1,n())
r3=me('IN'); print('INFO ATT-04 second IN w/ new key inside duplicate window ->',r3.status_code,r3.text[:160].replace('\n',' '),'| history now',n())
r=me('IN',client_ts='2020-01-01T00:00:00Z'); T('ATT-05','client-supplied timestamp on /me is not honoured (422 or ignored)',r.status_code==422 or (r.status_code==201 and r.json()['data']['punch_time'][:4]!='2020'),(r.status_code,r.text[:120]))
T('ATT-06','invalid direction -> 422',me('SIDEWAYS').status_code==422)
r=E['c'].post('/attendance/punches',headers=H(E),json=dict(employee_id=eid,punch_time=dt.datetime.now(dt.timezone.utc).isoformat(),direction='OUT',reference='MANUAL')); T('ATT-07','employee cannot use on-behalf punch endpoint (403)',r.status_code==403,r.status_code)
bt=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(hours=9)).isoformat()
r=A['c'].post('/attendance/punches',headers=H(A),json=dict(employee_id=eid,punch_time=bt,direction='IN',reference='MANUAL-HR')); T('ATT-08','admin on-behalf backdated punch accepted',r.status_code==201,r.text[:200])
ft=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=3)).isoformat()
r=A['c'].post('/attendance/punches',headers=H(A),json=dict(employee_id=eid,punch_time=ft,direction='IN',reference='FUTURE')); T('ATT-09','future-dated on-behalf punch rejected (422/409)',r.status_code in(409,422),(r.status_code,r.text[:120]))
r=A['c'].post('/attendance/punches',headers=H(A),json=dict(employee_id=str(uuid.uuid4()),punch_time=bt,direction='IN',reference='X')); T('ATT-10','on-behalf punch for unknown employee -> 404/422',r.status_code in(404,422),r.status_code)
r=B['c'].post('/attendance/punches',headers=H(B),json=dict(employee_id=eid,punch_time=bt,direction='IN',reference='X')); T('ATT-11','tenant B admin cannot punch for tenant A employee',r.status_code in(404,422,403),r.status_code)
r=B['c'].get('/attendance/punches',headers=H(B),params=dict(employee_id=eid)); T('ATT-12','tenant B cannot read tenant A punch history',r.status_code in(403,404) or (r.status_code==200 and r.json()['data']==[]),r.status_code)
# concurrency: 10 parallel same idempotency key -> 1 row
k2=str(uuid.uuid4())
with cf.ThreadPoolExecutor(10) as ex: rs=list(ex.map(lambda _: me('OUT',k2),range(10)))
ids={r.json()['data']['id'] for r in rs if r.status_code in(200,201)}
T('ATT-13','10 parallel requests with the same idempotency key create exactly one punch',len(ids)==1 and all(r.status_code in(200,201) for r in rs),([r.status_code for r in rs],len(ids)))
import psycopg
with psycopg.connect('postgresql://hrms_app:hrms_app_dev_password@localhost:5433/hrms_qa_e2e') as cx:
    cu=cx.cursor(); cu.execute("select set_config('app.company_id',%s,true)",(A['cid'],))
    cu.execute("select count(*),count(distinct idempotency_key) from punch where employee_id=%s and idempotency_key=%s",(eid,k2)); a,b=cu.fetchone()
    T('ATT-14','DB invariant: one punch row per idempotency key',a==1,(a,b))
    try: cu.execute("update punch set direction='IN'"); T('ATT-15','punch table append-only for runtime role',False)
    except Exception: cx.rollback(); T('ATT-15','punch table append-only for runtime role (UPDATE denied)',True)
# daily calculation & views
r=A['c'].post('/attendance/days/calculate',headers=H(A),params=dict(employee_id=eid)); print('INFO calc ->',r.status_code,r.text[:260].replace('\n',' '))
r=A['c'].get('/attendance/days',headers=H(A),params=dict(employee_id=eid)); print('INFO days ->',r.status_code,r.text[:200])
r=E['c'].post('/regularizations',headers=H(E),json=dict(date='2026-10-20')); print('INFO regularization probe ->',r.status_code,r.text[:300])
save('j4.json')
