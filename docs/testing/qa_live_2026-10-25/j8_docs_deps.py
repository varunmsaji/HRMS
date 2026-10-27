import sys; sys.path.insert(0,sys.argv[1]); import qa; from qa import *
import psycopg
PDF=b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
def docs(cid,eid):
    with psycopg.connect('postgresql://hrms:hrms_dev_password@localhost:5433/hrms_qa_e2e') as cx:
        cu=cx.cursor(); cu.execute("select count(*) from employee_document where employee_id=%s",(eid,)); return cu.fetchone()[0]
def upload(a,eid,data,name='id.pdf',ct='application/pdf',dt='AADHAAR'):
    return a['c'].post(f'/employees/{eid}/documents',headers=H(a),data={'document_type':dt},files={'file':(name,data,ct)})
# ---------- healthy storage (API on 18000)
reset_rl(); A=verified('DC'); e=must(post(A,'/employees',dict(first_name='Doc',last_name='Owner'),**{'Idempotency-Key':str(uuid.uuid4())}),what='emp'); eid=e['id']
r=upload(A,eid,PDF); print('probe doc type response:',r.status_code,r.text[:160])
if r.status_code==422 and 'document_type' in r.text:
    for dt in ('ID_PROOF','PAN','OTHER','RESUME','IDENTITY'):
        r=upload(A,eid,PDF,dt=dt)
        if r.status_code in(200,201): print('valid type',dt); break
T('DOC-01','valid PDF upload succeeds (201) and metadata persisted',r.status_code==201 and docs(A['cid'],eid)==1,(r.status_code,r.text[:140])); d=r.json().get('data',{}) if r.status_code==201 else {}
T('DOC-02','executable bytes named .pdf with pdf content-type rejected (magic-byte sniff)',400<=upload(A,eid,b'MZ\x90\x00\x03'+b'0'*100,'evil.pdf','application/pdf').status_code<500)
T('DOC-03','HTML/script named .pdf rejected',400<=upload(A,eid,b'<script>alert(1)</script>','x.pdf','application/pdf').status_code<500)
T('DOC-04','empty file rejected',400<=upload(A,eid,b'','e.pdf').status_code<500)
r=upload(A,eid,PDF,'../../etc/passwd.pdf'); T('DOC-05','path-traversal filename accepted safely or rejected, never 500',r.status_code in(201,400,422),r.status_code)
T('DOC-06','oversize file (>limit) rejected with 4xx not 500',400<=upload(A,eid,PDF+b'0'*(21*1024*1024)).status_code<500)
E=emp_user(A,must(post(A,'/employees',dict(first_name='Other',last_name='Emp',personal_email=f'o{uuid.uuid4().hex[:5]}@example.com'),**{'Idempotency-Key':str(uuid.uuid4())}),what='e2')['id']) if False else None
Bt=verified('DC2'); T('DOC-07','tenant B cannot upload to tenant A employee',Bt['c'].post(f'/employees/{eid}/documents',headers=H(Bt),data={'document_type':'AADHAAR'},files={'file':('a.pdf',PDF,'application/pdf')}).status_code in(404,403))
T('DOC-08','tenant B cannot list tenant A documents',Bt['c'].get(f'/employees/{eid}/documents',headers=H(Bt)).status_code in(404,403) or Bt['c'].get(f'/employees/{eid}/documents',headers=H(Bt)).json().get('data')==[])
lst=A['c'].get(f'/employees/{eid}/documents',headers=H(A)).json()['data']; url=(lst[0].get('download_url') if lst else None)
if url:
    import httpx as hx; g=hx.get(url); T('DOC-09','presigned download URL serves the exact bytes uploaded',g.status_code==200 and g.content==PDF,g.status_code)
else: T('DOC-09','presigned download URL present',False,lst[:1])
# ---------- storage DOWN (API-B on 18001, private redis alive)
qa.B='http://127.0.0.1:18001/v1'
import httpx
def mkB(): return httpx.Client(base_url='http://127.0.0.1:18001/v1',timeout=40)
c=mkB(); em=f"qa-sb-{uuid.uuid4().hex[:6]}@example.com"
r=c.post('/companies/register',json=dict(name='SB '+uuid.uuid4().hex[:4],admin_first_name='S',admin_last_name='B',admin_email=em,admin_password=PW)); d=r.json()['data']
T('DEP-00','API-B (private redis, dead storage endpoint) registers a company',r.status_code==201,r.text[:100])
qa.LOG=qa.LOG.replace('api.log','apiB.log'); tok,_=qa.mail_token(em,'Verify'); c.post('/auth/email/verify',json=dict(token=tok)); r=c.post('/auth/login',json=dict(email=em,password=PW)); SB=dict(email=em,tok=r.json()['data']['access_token'],cid=d['company_id'],c=c)
e=must(post(SB,'/employees',dict(first_name='NoStore',last_name='X'),**{'Idempotency-Key':str(uuid.uuid4())}),what='emp'); 
r=upload(SB,e['id'],PDF); T('DEP-01','storage unreachable: upload fails with 5xx and stable error envelope (no traceback/secret leak)',500<=r.status_code<600 and 'error' in r.json() and 'Traceback' not in r.text and 'aws' not in r.text.lower() and '19998' not in r.text,(r.status_code,r.text[:200]))
T('DEP-02','storage unreachable: no employee_document row left behind',docs(SB['cid'],e['id'])==0,docs(SB['cid'],e['id']))
print('INFO DEP-01 status/code:',r.status_code,r.json().get('error',{}).get('code'))
# import upload with storage dead
HDR="employee_code,first_name,middle_name,last_name,date_of_birth,gender,blood_group,marital_status,nationality,personal_email,personal_mobile,legal_entity,branch,department,designation,grade,reporting_manager,work_location_type,joining_date,annual_ctc_minor,currency"
r=c.post('/employee-imports',headers=H(SB),files={'file':('e.csv',(HDR+"\n,A,,B,1990-01-01,MALE,,,Indian,ab@example.com,9876500009,X,X,X,X,,,OFFICE,2026-09-15,100,INR\n").encode(),'text/csv')})
with psycopg.connect('postgresql://hrms:hrms_dev_password@localhost:5433/hrms_qa_e2e') as cx:
    cu=cx.cursor(); cu.execute("select count(*) from employee_import_batch where company_id=%s",(SB['cid'],)); nb=cu.fetchone()[0]
T('DEP-03','storage unreachable: import upload fails cleanly (5xx envelope) and creates no batch row',(500<=r.status_code<600 or r.status_code==422) and nb==0,(r.status_code,nb,r.text[:120]))
# ---------- Redis killed
subprocess.run("redis-cli -p 16399 shutdown nosave",shell=True); time.sleep(1)
r=c.get('/../health/ready'.replace('/v1/../','/')) if False else httpx.get('http://127.0.0.1:18001/health/ready',timeout=30)
T('DEP-04','Redis down: /health/ready reports not-ready (503) with redis flagged',r.status_code==503 or (r.json().get('data',{}).get('redis')!='ok'),(r.status_code,r.text[:140]))
r=httpx.get('http://127.0.0.1:18001/health/live',timeout=10); T('DEP-05','Redis down: /health/live still 200 (liveness independent of dependencies)',r.status_code==200,r.status_code)
t0=time.time(); r=c.post('/auth/login',json=dict(email=em,password=PW)); dt_=time.time()-t0
print('INFO DEP-06 login with Redis down ->',r.status_code,r.text[:120].replace('\n',' '),f'{dt_:.1f}s')
T('DEP-06','Redis down: login responds promptly (<15s) with a defined result, no hang/500 traceback',dt_<15 and 'Traceback' not in r.text and r.status_code in(200,401,429,503),(r.status_code,round(dt_,1)))
r=c.get('/employees',headers=H(SB)); print('INFO DEP-07 authenticated read with Redis down ->',r.status_code,r.text[:100])
T('DEP-07','Redis down: authenticated read returns a defined status (200 or 503), never 500 traceback',r.status_code in(200,503) and 'Traceback' not in r.text,r.status_code)
r=c.post('/employee-imports',headers=H(SB),files={'file':('e.csv',b'x','text/csv')}); T('DEP-08','Redis down: import upload returns defined 4xx/5xx envelope',r.status_code>=400 and 'error' in r.json(),(r.status_code,r.text[:100]))
save('j8.json')
