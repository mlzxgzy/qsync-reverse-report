import re,os,glob,json,base64
D="."
OUT="qsync-analysis/out"
os.makedirs(OUT,exist_ok=True)
B64=re.compile(r'[A-Za-z0-9+/]{60,}={0,2}')
def strings(path):
    data=open(path,'rb').read()
    res=set()
    for m in re.finditer(rb'[\x20-\x7e]{4,}', data):
        res.add(m.group().decode('ascii'))
    for m in re.finditer(rb'(?:[\x20-\x7e]\x00){4,}', data):
        res.add(m.group().decode('utf-16le'))
    return res
def clean(ss):
    out=[]
    for s in ss:
        if len(s)>4000: continue
        if len(B64.findall(s))>=2: continue
        if 'svg' in s.lower() and 'xmlns' in s: continue
        out.append(s)
    return sorted(set(out))
files=sorted(glob.glob("*.dll")+glob.glob("*.exe"))
allc={}
for f in files:
    c=clean(strings(f)); allc[f]=c
    open(f"{OUT}/str_{f}.txt","w").write("\n".join(c))
json.dump({k:len(v) for k,v in allc.items()}, open(f"{OUT}/str_counts.json","w"), indent=1)
# endpoint inventory
funcs={}
urls=set()
for f,c in allc.items():
    for s in c:
        for m in re.finditer(r'func=([a-zA-Z0-9_]+)', s):
            funcs.setdefault(m.group(1),set()).add(f)
        for m in re.finditer(r'(?:https?|%1%2:%3|%ls%ls:%d|%s%s:%d)[^\s"\'<>]{0,200}', s):
            t=m.group(0)
            if ':' in t and ('cgi' in t or 'api' in t or 'oauth' in t or 'php' in t):
                urls.add((f,t))
open(f"{OUT}/func_inventory.txt","w").write("\n".join(f"{k}\t{','.join(sorted(v))}" for k,v in sorted(funcs.items())))
open(f"{OUT}/url_inventory.txt","w").write("\n".join(f"{f}\t{t}" for f,t in sorted(urls)))
print("string counts:", json.dumps({k:v for k,v in sorted(allc.items())}, indent=1))
print("distinct func= :", len(funcs))
print("distinct urls  :", len(urls))
