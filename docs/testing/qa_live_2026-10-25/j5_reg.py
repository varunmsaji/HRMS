import sys; sys.path.insert(0,sys.argv[1]); from qa import *
import psycopg
reset_rl(); A=verified('RG'); S=org_setup(A); eid=S['emp']['id']; E=emp_user(A,eid)
pol=must(post(A,'/regularization-policies',dict(name='Std Reg')),what='pol')
v=must(post(A,f"/regularization-policies/{pol['id']}/versions",dict(effective_from='2026-01-01',allowed_types=[dict(regularization_type=t) for t in('MISSING_PUNCH','WRONG_PUNCH','FULL_DAY')],approval_chain='HR')),what='ver')
must(post(A,f"/regularization-policies/{pol['id']}/versions/{v['id']}/publish",{},**{'If-Match':'1'}),what='pub')
must(post(A,'/policy-assignments',dict(policy_kind='REGULARIZATION_POLICY',policy_id=pol['id'],scope_type='COMPANY',effective_from='2026-01-01')),what='assign')
body=dict(attendance_date='2026-10-20',request_type='MISSING_PUNCH',reason='forgot to punch',requested_punches=[dict(direction='IN',requested_time='2026-10-20T03:45:00Z'),dict(direction='OUT',requested_time='2026-10-20T12:30:00Z')])
r=E['c'].post('/regularizations',headers=H(E),json=body); T('REG-01','employee submits regularization -> 201 PENDING',r.status_code==201 and r.json()['data']['status'] in('PENDING','SUBMITTED'),r.text[:200]); rq=r.json()['data']
def npun():
    with psycopg.connect('postgresql://hrms_app:hrms_app_dev_password@localhost:5433/hrms_qa_e2e') as cx:
        cu=cx.cursor(); cu.execute("select set_config('app.company_id',%s,true)",(A['cid'],)); cu.execute("select count(*) from punch where employee_id=%s",(eid,)); return cu.fetchone()[0]
T('REG-02','pending request creates no punch rows yet',npun()==0,npun())
r=E['c'].post('/regularizations',headers=H(E),json=dict(body,request_type='NOPE')); T('REG-03','unknown request_type -> 422',r.status_code==422)
r=E['c'].post('/regularizations',headers=H(E),json=dict(attendance_date='2026-10-20',request_type='MISSING_PUNCH')); T('REG-04','request without correction payload -> 422',r.status_code==422)
r=E['c'].post(f"/regularizations/{rq['id']}/approve",headers=H(E,**{'If-Match':str(rq.get('version',1))}),json={}); T('REG-05','employee cannot approve own regularization (403)',r.status_code==403,r.status_code)
g=A['c'].get(f"/regularizations/{rq['id']}",headers=H(A)); ver=g.headers.get('etag') or str(g.json()['data'].get('version'))
r=A['c'].post(f"/regularizations/{rq['id']}/approve",headers=H(A,**{'If-Match':ver}),json={}); T('REG-06','HR approves',r.status_code==200 and r.json()['data']['status']=='APPROVED',r.text[:200])
T('REG-07','approval writes exactly the 2 requested punches',npun()==2,npun())
g=A['c'].get(f"/regularizations/{rq['id']}",headers=H(A)); ver=g.headers.get('etag') or str(g.json()['data'].get('version'))
r=A['c'].post(f"/regularizations/{rq['id']}/approve",headers=H(A,**{'If-Match':ver}),json={}); T('REG-08','second approval rejected',r.status_code in(409,422),r.status_code)
T('REG-09','second approval did not duplicate punches (still 2)',npun()==2,npun())
r=A['c'].post(f"/regularizations/{rq['id']}/reject",headers=H(A,**{'If-Match':ver}),json=dict(rejection_reason='late')); T('REG-10','reject after approve rejected (invalid transition)',r.status_code in(409,422),r.status_code)
# reject path writes nothing
b2=dict(body,attendance_date='2026-10-21',requested_punches=[dict(direction='IN',requested_time='2026-10-21T03:45:00Z'),dict(direction='OUT',requested_time='2026-10-21T12:30:00Z')])
r=E['c'].post('/regularizations',headers=H(E),json=b2); rq2=r.json()['data']
g=A['c'].get(f"/regularizations/{rq2['id']}",headers=H(A)); v2=g.headers.get('etag') or str(g.json()['data'].get('version'))
r=A['c'].post(f"/regularizations/{rq2['id']}/reject",headers=H(A,**{'If-Match':v2}),json=dict(rejection_reason='not valid')); T('REG-11','HR rejects',r.status_code==200 and r.json()['data']['status']=='REJECTED',r.text[:160])
T('REG-12','rejection writes no punches (still 2)',npun()==2,npun())
# future date
r=E['c'].post('/regularizations',headers=H(E),json=dict(body,attendance_date='2030-01-01',requested_punches=[dict(direction='IN',requested_time='2030-01-01T03:45:00Z')])); T('REG-13','future-date regularization rejected',r.status_code in(409,422),(r.status_code,r.text[:120]))
r=E['c'].post('/regularizations',headers=H(E),json=dict(body,employee_id=str(uuid.uuid4()))); T('REG-14','employee cannot submit on behalf of another employee id',r.status_code in(403,404,422),r.status_code)
Bt=verified('RG2'); T('REG-15','tenant B cannot read tenant A regularization',Bt['c'].get(f"/regularizations/{rq['id']}",headers=H(Bt)).status_code==404)
# daily calc picks up regularized punches
r=A['c'].post('/attendance/days/calculate',headers=H(A),params=dict(employee_id=eid,attendance_date='2026-10-20')); print('INFO calc 2026-10-20 ->',r.status_code,r.text[:400])
save('j5.json')
