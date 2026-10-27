import json,re,glob,sys,collections
SP=sys.argv[1]; spec=json.load(open(SP+'/openapi.json'))
def norm(p): return re.sub(r'\{[^}/]+\}','{}',p.rstrip('/'))
ops={(m.upper(),norm(p)) for p,v in spec['paths'].items() for m in v if m in('get','post','put','patch','delete')}
M={'getList':'GET','get':'GET','download':'GET','post':'POST','put':'PUT','patch':'PATCH','delete':'DELETE'}
def clean(s):
    s=s.split('?')[0]; s=re.sub(r'\$\{[^}]*\}','{}',s); s=re.sub(r'\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*','{}',s); return norm('/v1'+s)
def match(m,p):
    if (m,p) in ops: return (m,p)
    for (om,op) in ops:
        if om==m and re.fullmatch(re.escape(op).replace(r'\{\}','[^/]+'),p): return (om,op)
        if om==m and re.fullmatch(re.escape(p).replace(r'\{\}','[^/]+'),op): return (om,op)
rxw=re.compile(r"apiClient\.(getList|get|download|post|put|patch|delete)(?:<[^()]*?>)?\(\s*[`\"'](/[^`\"']*)[`\"']",re.S)
rxm=re.compile(r"client\.(getList|get|post|put|patch|delete)(?:<[^()]*?>)?\(\s*'(/[^']*)'")
rxm2=re.compile(r"_client\s*\.(getList|get|post|put|patch|delete)(?:<[^()]*?>)?\(\s*'(/[^']*)'",re.S)
cov={'web':set(),'mobile':set()}
for f in glob.glob('web/src/**/*.ts*',recursive=True):
    if '.test.' in f: continue
    for m in rxw.finditer(open(f,errors='ignore').read()):
        k=match(M[m.group(1)],clean(m.group(2)));  k and cov['web'].add(k)
for f in glob.glob('mobile/lib/**/*.dart',recursive=True):
    t=open(f,errors='ignore').read()
    for rx in(rxm,rxm2):
        for m in rx.finditer(t):
            k=match(M[m.group(1)],clean(m.group(2))); k and cov['mobile'].add(k)
allc=cov['web']|cov['mobile']
print(f"operations: {len(ops)}; web covers {len(cov['web'])}; mobile covers {len(cov['mobile'])}; either {len(allc)}; neither {len(ops-allc)}")
unc=sorted(ops-allc,key=lambda x:(x[1],x[0]))
print('NO CLIENT:'); 
g=collections.defaultdict(list)
for m,p in unc: g[p.split('/')[2] if p.count('/')>1 else p].append(m+' '+p)
for k,v in g.items(): print(' ',k,len(v),'|',' ; '.join(v[:4]))
print('web-only:',len(cov['web']-cov['mobile']),' mobile-only:',len(cov['mobile']-cov['web']))
json.dump({'web':sorted(map(list,cov['web'])),'mobile':sorted(map(list,cov['mobile'])),'none':sorted(map(list,unc))},open(SP+'/coverage.json','w'))
