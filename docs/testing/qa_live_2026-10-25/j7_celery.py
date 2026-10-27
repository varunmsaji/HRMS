import sys,signal; sys.path.insert(0,sys.argv[1]); from qa import *
import psycopg
reset_rl(); A=verified('CW')
le=must(post(A,'/legal-entities',dict(name='QA LE')),what='le'); br=must(post(A,'/branches',dict(legal_entity_id=le['id'],name='QA HQ')),what='br')
dp=must(post(A,'/departments',dict(name='QA Eng',branch_id=br['id'])),what='dp'); ds=must(post(A,'/designations',dict(title='QA Dev',department_id=dp['id'])),what='ds')
HDR="employee_code,first_name,middle_name,last_name,date_of_birth,gender,blood_group,marital_status,nationality,personal_email,personal_mobile,legal_entity,branch,department,designation,grade,reporting_manager,work_location_type,joining_date,annual_ctc_minor,currency"
def csv(tag):
    rows=[f",Ravi{tag},,Kumar,1995-06-12,MALE,,,Indian,ravi{tag}@example.com,9876500001,{le['name']},{br['name']},{dp['name']},{ds['title']},,,OFFICE,2026-09-15,120000000,INR",
          f",Anita{tag},,Desai,1992-03-20,FEMALE,,,Indian,anita{tag}@example.com,9876500002,{le['name']},{br['name']},{dp['name']},{ds['title']},,,HYBRID,2026-09-16,150000000,INR",
          f",Bad{tag},,Rao,1990-01-01,MALE,,,Indian,bad{tag}@example.com,9876500003,{le['name']},NOT-A-BRANCH,{dp['name']},{ds['title']},,,OFFICE,2026-09-17,100000000,INR",
          f",,,,1990-01-01,MALE,,,Indian,noname{tag}@example.com,9876500005,{le['name']},{br['name']},{dp['name']},{ds['title']},,,OFFICE,2026-09-19,100000000,INR"]
    return (HDR+"\n"+"\n".join(rows)+"\n").encode()
def upload(a,data,name='emps.csv',ct='text/csv'):
    return a['c'].post('/employee-imports',headers=H(a),files={'file':(name,data,ct)})
def wait(a,bid,want=('COMPLETED','FAILED','COMPLETED_WITH_ERRORS'),secs=40):
    for _ in range(secs*2):
        b=a['c'].get(f'/employee-imports/{bid}',headers=H(a)).json()['data']
        if b['status'] in want: return b
        time.sleep(0.5)
    return b
cnt=lambda: len([x for x in A['c'].get('/employees?per_page=100',headers=H(A)).json()['data']])
n0=cnt()
r=upload(A,csv('a')); T('JOB-01','CSV upload accepted -> batch created (202/201)',r.status_code in(201,202),r.text[:200]); bid=r.json()['data']['id']
b=wait(A,bid); T('JOB-02','REAL Celery worker picked up employee_import.process_batch and finished the batch',b['status'] in('COMPLETED','COMPLETED_WITH_ERRORS'),(b['status'],b['total_rows'],b['success_count'],b['error_count']))
T('JOB-03','row accounting: 4 rows, 2 succeeded, 2 failed',(b['total_rows'],b['success_count'],b['error_count'])==(4,2,2),(b['total_rows'],b['success_count'],b['error_count']))
T('JOB-04','exactly 2 employees created (failed rows left no partial employees)',cnt()-n0==2,cnt()-n0)
er=A['c'].get(f'/employee-imports/{bid}/errors',headers=H(A)).json()['data']; T('JOB-05','row errors visible with row number + stable error code',len(er)==2 and all(e['error_code'] and e['row_number'] for e in er),[(e['row_number'],e['error_code']) for e in er])
Bt=verified('CW2'); T('JOB-06','tenant B cannot read tenant A import batch / errors',Bt['c'].get(f'/employee-imports/{bid}',headers=H(Bt)).status_code==404 and Bt['c'].get(f'/employee-imports/{bid}/errors',headers=H(Bt)).status_code==404)
T('JOB-07','non-CSV / wrong content rejected (4xx)',400<=upload(A,b'\x89PNG\r\n\x1a\n'+b'0'*50,'x.csv','text/csv').status_code<500)
T('JOB-08','missing required header rejected (4xx)',400<=upload(A,b'a,b,c\n1,2,3\n').status_code<500)
# worker down -> job waits in broker, recovers on restart
def worker_pids():
    out=[]
    for d in os.listdir('/proc'):
        if d.isdigit():
            try: cl=open(f'/proc/{d}/cmdline','rb').read().decode().replace('\0',' ')
            except Exception: continue
            if 'celery -A entrypoints.worker worker' in cl and 'qa-worker@' in cl and 'bash' not in cl.split(' ')[0]: out.append(int(d))
    return out
pids=worker_pids()
for p in pids:
    try: os.kill(p,9)
    except ProcessLookupError: pass
time.sleep(2)
n1=cnt(); r=upload(A,csv('b')); bid2=r.json()['data']['id']; time.sleep(5)
b=A['c'].get(f'/employee-imports/{bid2}',headers=H(A)).json()['data']
T('JOB-09','with worker DOWN the batch stays PENDING (job queued, not lost, not half-done)',b['status'] in('PENDING','QUEUED') and cnt()==n1,(b['status'],cnt()-n1))
print('worker pids killed:',len(pids))
open(sys.argv[1]+'/bid2','w').write(bid2)
save('j7a.json')
