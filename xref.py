import re,os,sys,glob
D="."
def allstrings(path,minlen=4):
    data=open(path,'rb').read()
    out=set()
    for m in re.finditer(rb'[\x20-\x7e]{%d,}'%minlen,data): out.add(m.group().decode('ascii'))
    for m in re.finditer(rb'(?:[\x20-\x7e]\x00){%d,}'%minlen,data): out.add(m.group().decode('utf-16le'))
    return out
pats=sys.argv[1:]
files=[f for f in glob.glob("*.dll")+glob.glob("*.exe")]
cache={f:allstrings(f) for f in files}
for p in pats:
    rx=re.compile(p,re.I)
    print(f"=== refs to: {p}")
    for f in sorted(files):
        hits=sorted({s for s in cache[f] if rx.search(s)})
        if hits:
            print(f"   {f}")
            for h in hits[:6]: print(f"        {h[:160]}")
