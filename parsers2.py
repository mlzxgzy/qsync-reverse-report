# -*- coding: utf-8 -*-
"""按 '::Parser' 日志串把 .rdata 字符串切成桶 → 每个解析器的字段名集合。
   同一解析器在多个模块/多份 .rdata 副本中重复，最后合并去重。
"""
import re, json, sys, glob

MODS = ["QFileSync.dll","QsyncAPI.dll","QsyncLib.dll","Qsync.exe"]
FIELD = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{1,40}$')
NOISE = {'true','false','null','NULL','http','https','sid','func','POST','GET',
         'UTF-8','utf-8','TCP','status','result','success','error','data','name','type','code'}
SKIP = re.compile(r'^(api-ms|KERNEL|USER32|OLE|ADVAPI|SHELL|SHLWAPI|Qt5|MSVC|VCRUNTIME|api-)')

def strings(path, minlen=2):
    data=open(path,'rb').read(); res=[]
    for m in re.finditer(rb'[\x20-\x7e]{%d,}'%minlen, data): res.append((m.start(), m.group().decode('ascii')))
    for m in re.finditer(rb'(?:[\x20-\x7e]\x00){%d,}'%minlen, data): res.append((m.start(), m.group().decode('utf-16le')))
    res.sort(); return res

def looks_field(s):
    if not FIELD.match(s) or s in NOISE or s.startswith('.'): return False
    if SKIP.match(s): return False
    if s.isupper() and len(s)>6: return False
    if re.match(r'^(Get|Set|Reg|Create|Close|Query|Enum|Read|Write|Wait|Sleep|Lock|Unlock)', s): return False
    return True

MARK = re.compile(r'::Parser\b')

def bucket(path):
    ss=strings(path); buckets=[]; cur=None
    for off,s in ss:
        if MARK.search(s):
            # 取该日志串里的类名
            m=re.search(r'([A-Za-z_][A-Za-z0-9_]*)::Parser', s)
            cur={"cls": m.group(1) if m else "?", "log": s[:120], "off": off, "fields": [], "mod": path}
            buckets.append(cur); continue
        if cur is not None and looks_field(s):
            f=re.sub(r'^(R|\d)(?=[A-Za-z])', '', s)   # 去掉内存前缀噪声字符
            if f and f not in cur["fields"]: cur["fields"].append(f)
    return [b for b in buckets if b["fields"]]

if __name__=="__main__":
    allb=[]
    for p in MODS: allb += bucket(p)
    merged={}
    for b in allb:
        k=b["cls"]
        if k not in merged: merged[k]={"fields":[], "logs":set(), "mods":set()}
        for f in b["fields"]:
            if f not in merged[k]["fields"]: merged[k]["fields"].append(f)
        merged[k]["logs"].add(b["log"]); merged[k]["mods"].add(b["mod"])
    filt = sys.argv[1] if len(sys.argv)>1 else None
    json.dump({k:{"fields":v["fields"],"logs":sorted(v["logs"]),"mods":sorted(v["mods"])}
               for k,v in merged.items()},
              open("qsync-analysis/out/parser_fields.json","w"), ensure_ascii=False, indent=1)
    print(f"共 {len(merged)} 个解析器")
    for k in sorted(merged):
        if filt and not re.search(filt,k): continue
        print(f"\n=== {k}   [{','.join(sorted(merged[k]['mods']))}]")
        print("   " + ", ".join(merged[k]['fields'][:60]))
