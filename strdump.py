import re,sys,os,json
D="."
def strings(path, minlen=4):
    data=open(path,'rb').read()
    res=[]
    for m in re.finditer(rb'[\x20-\x7e]{%d,}'%minlen, data):
        res.append((m.start(), m.group().decode('ascii')))
    # utf-16le
    for m in re.finditer(rb'(?:[\x20-\x7e]\x00){%d,}'%minlen, data):
        res.append((m.start(), m.group().decode('utf-16le')))
    res.sort()
    return res
if __name__=="__main__":
    p=sys.argv[1]
    pats=[re.compile(x) for x in sys.argv[2:]] if len(sys.argv)>2 else None
    for off,s in strings(p):
        if pats is None or any(x.search(s) for x in pats):
            print(f"{off:08x} {s}")
