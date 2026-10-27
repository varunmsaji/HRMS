import sys; sys.path.insert(0,sys.argv[1]); from qa import *
import psycopg
bid2=open(sys.argv[1]+'/bid2').read()
with psycopg.connect('postgresql://hrms:hrms_dev_password@localhost:5433/hrms_qa_e2e') as cx:   # owner role, read-only query
    cu=cx.cursor(); cu.execute("select status,total_rows,success_count,error_count,company_id from employee_import_batch where id=%s",(bid2,)); st,tot,ok,er,cid=cu.fetchone()
    T('JOB-10','after worker restart the queued batch completes (message survived the outage)',st in('COMPLETED','COMPLETED_WITH_ERRORS') and (tot,ok,er)==(4,2,2),(st,tot,ok,er))
    cu.execute("select count(*),count(distinct personal_email) from employee where company_id=%s and personal_email like %s",(cid,'%bravi%')) if False else None
    cu.execute("select count(*) from employee where company_id=%s and personal_email in ('ravib@example.com','anitab@example.com')",(cid,)); n=cu.fetchone()[0]
    T('JOB-11','recovered batch created each valid employee exactly once (no duplicates)',n==2,n)
    cu.execute("select count(*) from employee_import_batch where company_id=%s and status='PROCESSING'",(cid,)); T('JOB-12','no batch left stuck in PROCESSING',cu.fetchone()[0]==0)
import json; r=json.load(open(sys.argv[1]+'/j7a.json')); save('j7a.json') if False else None
RES[:0]=[tuple(x) for x in r]; save('j7.json')
