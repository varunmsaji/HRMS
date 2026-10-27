import sys; sys.path.insert(0,sys.argv[1]); from qa import *
a=reg('Auth'); c=a['c']
r=c.post('/auth/login',json=dict(email=a['email'],password=PW))
T('AUTH-01','login blocked until email verified (403 EMAIL_NOT_VERIFIED)',r.status_code==403 and r.json()['error']['code']=='EMAIL_NOT_VERIFIED',r.text)
r=c.post('/auth/email/verify',json=dict(token='x'*43)); T('AUTH-02','garbage verification token rejected (4xx, stable error shape)',400<=r.status_code<500 and 'error' in r.json(),r.text)
tok,_=mail_token(a['email'],'Verify'); T('AUTH-03','verification email issued (sandbox sender, link captured)',tok is not None)
r=c.post('/auth/email/verify',json=dict(token=tok)); T('AUTH-04','valid verification token accepted',r.status_code in(200,204),r.text)
r=c.post('/auth/email/verify',json=dict(token=tok)); T('AUTH-05','verification token is single-use',400<=r.status_code<500,r.status_code)
r=c.post('/auth/login',json=dict(email=a['email'],password=PW)); ok=r.status_code==200
T('AUTH-06','valid login -> 200 + access token + HttpOnly refresh cookie',ok and 'access_token' in r.json()['data'] and 'hrms_refresh' in c.cookies and 'httponly' in r.headers.get('set-cookie','').lower(),r.status_code)
a['tok']=r.json()['data']['access_token']; cid=a['cid']
r1=c.post('/auth/login',json=dict(email=a['email'],password='wrong-Password-1!')); r2=c.post('/auth/login',json=dict(email='nobody-%s@example.com'%uuid.uuid4().hex[:5],password='wrong-Password-1!'))
T('AUTH-07','wrong password and unknown email give identical 401 (no user enumeration)',r1.status_code==r2.status_code==401 and r1.json()['error']['code']==r2.json()['error']['code'] and r1.json()['error']['message']==r2.json()['error']['message'],(r1.status_code,r2.status_code,r1.json()['error']['code'],r2.json()['error']['code']))
m=mk()
T('AUTH-08','/auth/me without token -> 401',m.get('/auth/me').status_code==401)
T('AUTH-09','garbage bearer -> 401',m.get('/auth/me',headers={'Authorization':'Bearer abc.def.ghi'}).status_code==401)
t=a['tok']; tam=t[:-4]+('AAAA' if not t.endswith('AAAA') else 'BBBB')
T('AUTH-10','tampered signature -> 401',m.get('/auth/me',headers={'Authorization':'Bearer '+tam}).status_code==401)
pl=json.loads(base64.urlsafe_b64decode(t.split('.')[1]+'=='))
T('AUTH-11','alg=none token -> 401',m.get('/auth/me',headers={'Authorization':'Bearer '+forge(pl,alg='none')}).status_code==401)
ex=dict(pl,exp=int(time.time())-60,iat=int(time.time())-900)
T('AUTH-12','correctly-signed but EXPIRED token -> 401',m.get('/auth/me',headers={'Authorization':'Bearer '+forge(ex)}).status_code==401)
T('AUTH-13','token signed with wrong secret -> 401',m.get('/auth/me',headers={'Authorization':'Bearer '+forge(pl,secret='some-other-secret-xxxxxxxx')}).status_code==401)
fs=dict(pl,sub=str(uuid.uuid4()))
T('AUTH-14','validly-signed token for non-existent user/session -> 401/403',m.get('/auth/me',headers={'Authorization':'Bearer '+forge(fs)}).status_code in(401,403))
# refresh rotation + reuse detection
old=c.cookies.get('hrms_refresh'); r=c.post('/auth/token/refresh'); new=c.cookies.get('hrms_refresh')
T('AUTH-15','refresh issues new access token and rotates refresh cookie',r.status_code==200 and new and new!=old,r.status_code)
at2=r.json()['data']['access_token']
m2=mk(); m2.cookies.set('hrms_refresh',old); r=m2.post('/auth/token/refresh')
T('AUTH-16','re-using a rotated refresh token is rejected',r.status_code in(401,403),r.status_code)
c.cookies.set('hrms_refresh',new); r=c.post('/auth/token/refresh')
T('AUTH-17','refresh-token reuse revokes the whole family (newest token also dead)',r.status_code in(401,403),r.status_code)
# fresh session for logout
r=c.post('/auth/login',json=dict(email=a['email'],password=PW)); tk=r.json()['data']['access_token']
T('AUTH-18','access token works before logout',m.get('/auth/me',headers={'Authorization':'Bearer '+tk}).status_code==200)
r=c.post('/auth/logout',headers={'Authorization':'Bearer '+tk}); T('AUTH-19','logout succeeds',r.status_code in(200,204),r.status_code)
T('AUTH-20','access token invalid immediately after logout (session invalidation)',m.get('/auth/me',headers={'Authorization':'Bearer '+tk}).status_code==401,m.get('/auth/me',headers={'Authorization':'Bearer '+tk}).status_code)
T('AUTH-21','refresh after logout rejected',c.post('/auth/token/refresh').status_code in(401,403))
# password reset
unk=m.post('/auth/password/forgot',json=dict(email='nobody-%s@example.com'%uuid.uuid4().hex[:6])); kn=m.post('/auth/password/forgot',json=dict(email=a['email']))
T('AUTH-22','forgot-password: known vs unknown email indistinguishable',unk.status_code==kn.status_code and unk.status_code<300 and unk.json().get('data')==kn.json().get('data'),(unk.status_code,kn.status_code,unk.text[:100],kn.text[:100]))
rt,_=mail_token(a['email'],'eset'); T('AUTH-23','reset email issued for known account only',rt is not None)
r=m.post('/auth/password/reset',json=dict(token=rt,password='short')); T('AUTH-24','reset with weak password rejected',r.status_code==422 or 400<=r.status_code<500,r.status_code)
NP='New-Pass-987654!'
r=m.post('/auth/password/reset',json=dict(token=rt,password=NP)); T('AUTH-25','reset with valid token + strong password succeeds',r.status_code in(200,204),r.text[:200])
T('AUTH-26','reset token single-use',400<=m.post('/auth/password/reset',json=dict(token=rt,password=NP+'x')).status_code<500)
T('AUTH-27','old password no longer works',m.post('/auth/login',json=dict(email=a['email'],password=PW)).status_code==401)
T('AUTH-28','new password works',m.post('/auth/login',json=dict(email=a['email'],password=NP)).status_code==200)
# malformed bodies
T('AUTH-29','login with missing fields -> 422 with field details',m.post('/auth/login',json={}).status_code==422)
r=m.post('/auth/login',content=b'{not json',headers={'content-type':'application/json'}); T('AUTH-30','malformed JSON -> 4xx, no stack trace',400<=r.status_code<500 and 'Traceback' not in r.text,r.text[:150])
# brute force
codes=[mk().post('/auth/login',json=dict(email=a['email'],password='bad-Pass-%d!'%i)).status_code for i in range(25)]
T('AUTH-31','login brute-force eventually rate-limited (429)',429 in codes,sorted(set(codes)))
r=mk().post('/auth/login',json=dict(email=a['email'],password='bad-Pass-x!'))
T('AUTH-32','429 carries Retry-After and stable error body',r.status_code!=429 or ('retry-after' in r.headers and 'error' in r.json()),dict(r.headers))
save('j1.json')
