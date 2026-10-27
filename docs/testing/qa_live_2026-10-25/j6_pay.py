import sys; sys.path.insert(0,sys.argv[1]); from qa import *
reset_rl(); A=verified('PY'); S=org_setup(A); eid=S['emp']['id']; le=S['le']['id']; E=emp_user(A,eid); B=verified('PY2')
r=post(A,'/payroll/pay-runs',dict(legal_entity_id=le,month='2026-09')); T('PAY-01','create DRAFT pay run for a month',r.status_code==201 and r.json()['data']['status']=='DRAFT',r.text[:200]); run=r.json()['data']
r=post(A,'/payroll/pay-runs',dict(legal_entity_id=le,month='2026-09')); T('PAY-02','duplicate pay run for same entity+month -> 409 PAY_RUN_ALREADY_EXISTS',r.status_code==409 and r.json()['error']['code']=='PAY_RUN_ALREADY_EXISTS',r.text[:160])
T('PAY-03','invalid month format -> 422',post(A,'/payroll/pay-runs',dict(legal_entity_id=le,month='September')).status_code==422)
T('PAY-04','unknown legal entity -> 404/422',post(A,'/payroll/pay-runs',dict(legal_entity_id=str(uuid.uuid4()),month='2026-08')).status_code in(404,422))
def v(): g=A['c'].get(f"/payroll/pay-runs/{run['id']}",headers=H(A)); return g.headers.get('etag') or str(g.json()['data'].get('version')),g.json()['data']['status']
for act,tid in[('compute','PAY-05'),('approve','PAY-06'),('finalise','PAY-07'),('mark-paid','PAY-08')]:
    ver,_=v(); r=post(A,f"/payroll/pay-runs/{run['id']}/{act}",{},**{'If-Match':ver}); T(tid,f'DRAFT run cannot {act} (invalid transition 409/422)',r.status_code in(409,422),(r.status_code,r.text[:120]))
ver,_=v(); r=post(A,f"/payroll/pay-runs/{run['id']}/lock-inputs",{},**{'If-Match':ver}); T('PAY-09','lock-inputs without a closed attendance period refused (409/422)',r.status_code in(409,422),(r.status_code,r.text[:140]))
T('PAY-10','refused transitions left run in DRAFT',v()[1]=='DRAFT',v())
ver,_=v(); r=post(A,f"/payroll/pay-runs/{run['id']}/lock-inputs",{},**{'If-Match':'999'}); T('PAY-11','stale If-Match on a transition rejected',r.status_code in(409,412,422),r.status_code)
for p,tid in[('/payroll/pay-runs','PAY-12'),('/payroll/salary-components','PAY-13'),('/payroll/statutory-rates','PAY-14'),('/payroll/settings','PAY-15')]:
    T(tid,f'EMPLOYEE role denied GET {p}',E['c'].get(p,headers=H(E)).status_code==403)
T('PAY-16','EMPLOYEE role cannot create pay run',E['c'].post('/payroll/pay-runs',headers=H(E),json=dict(legal_entity_id=le,month='2026-07')).status_code==403)
T('PAY-17','EMPLOYEE role cannot approve a run',E['c'].post(f"/payroll/pay-runs/{run['id']}/approve",headers=H(E,**{'If-Match':'1'}),json={}).status_code==403)
T('PAY-18','tenant B cannot read tenant A pay run',B['c'].get(f"/payroll/pay-runs/{run['id']}",headers=H(B)).status_code==404)
T('PAY-19','tenant B pay-run list does not contain A run',run['id'] not in [x['id'] for x in B['c'].get('/payroll/pay-runs',headers=H(B)).json()['data']])
r=B['c'].post(f"/payroll/pay-runs/{run['id']}/compute",headers=H(B,**{'If-Match':'1'}),json={}); T('PAY-20','tenant B cannot transition tenant A run',r.status_code in(404,403),r.status_code)
r=B['c'].post('/payroll/pay-runs',headers=H(B),json=dict(legal_entity_id=le,month='2026-06')); T('PAY-21','tenant B cannot create run against tenant A legal entity',r.status_code in(404,422),r.status_code)
r=E['c'].get('/me/payslips',headers=H(E)); T('PAY-22','employee can list own payslips (empty before any finalised run)',r.status_code==200 and r.json()['data']==[],(r.status_code,r.text[:120]))
r=E['c'].get(f"/me/payslips/{run['id']}",headers=H(E)); T('PAY-23','employee fetching payslip of a non-finalised run -> 404',r.status_code==404,r.status_code)
r=A['c'].delete(f"/payroll/pay-runs/{run['id']}",headers=H(A,**{'If-Match':v()[0]})); T('PAY-24','DRAFT run can be deleted by processor',r.status_code in(200,204),(r.status_code,r.text[:100]))
r=post(A,'/payroll/adjustments',dict(source_pay_run_id=str(uuid.uuid4()),employee_id=eid,paid_days_delta=1,reason='x'),**{'Idempotency-Key':str(uuid.uuid4())}); T('PAY-25','adjustment against unknown run -> 404/422',r.status_code in(404,422),r.status_code)
r=A['c'].post('/payroll/adjustments',headers=H(A),json=dict(source_pay_run_id=str(uuid.uuid4()),employee_id=eid,paid_days_delta=1,reason='x')); T('PAY-26','adjustment without Idempotency-Key rejected (400/422)',r.status_code in(400,422),r.status_code)
save('j6.json')
