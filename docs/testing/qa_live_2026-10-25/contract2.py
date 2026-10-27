import json,re,glob,os,sys
SP=sys.argv[1]
spec=json.load(open(SP+'/openapi.json'))
def norm(p): return re.sub(r'\{[^}/]+\}','{}',p.rstrip('/'))
ops={}
for p,v in spec['paths'].items():
    for m in v:
        if m in('get','post','put','patch','delete'): ops.setdefault(norm(p),set()).add(m.upper())
def clean(s):
    s=s.split('?')[0]
    s=re.sub(r'\$\{[^}]*\}|\$\{[^}]*\}','{}',s); s=re.sub(r'\$[A-Za-z_][A-Za-z0-9_]*','{}',s)
    return norm('/v1'+s) if not s.startswith('/v1') else norm(s)
def match(path,method):
    if path in ops: return method in ops[path], ops[path]
    # dynamic segment may stand for a literal (e.g. /{}/approve vs /x/approve)
    rx=[o for o in ops if re.fullmatch(re.escape(path).replace(r'\{\}','[^/]+'),o) or re.fullmatch(re.escape(o).replace(r'\{\}','[^/]+'),path)]
    for o in rx:
        if method in ops[o]: return True,ops[o]
    return (False, ops[rx[0]]) if rx else (None,None)
def run(name,files,rx,ngroup):
    bad=[];tot=0;seen=set()
    for f in files:
        if any(k in f for k in('node_modules','/build/','.test.','/test/','.spec.')): continue
        t=open(f,errors='ignore').read()
        for m in rx.finditer(t):
            meth=m.group(1).upper(); p=clean(m.group(2)); line=t[:m.start()].count('\n')+1
            if (meth,p) in seen: continue
            seen.add((meth,p)); tot+=1
            ok,have=match(p,meth)
            if ok is not True: bad.append((meth,p,'NO ROUTE' if ok is None else 'METHOD (server has %s)'%sorted(have),f"{os.path.relpath(f)}:{line}"))
    print(f"== {name}: {tot} distinct calls, {len(bad)} mismatches")
    for b in bad: print("  ",*b)
web=glob.glob('web/src/**/*.ts*',recursive=True)
run('web',web,re.compile(r"apiClient\.(get|post|put|patch|delete)(?:<[^()]*?>)?\(\s*[`\"'](/[^`\"']*)[`\"']",re.S),2)
mob=glob.glob('mobile/lib/**/*.dart',recursive=True)
run('mobile',mob,re.compile(r"_?client\.(get|post|put|patch|delete)(?:<[^()]*?>)?\(\s*'(/[^']*)'"),2)
