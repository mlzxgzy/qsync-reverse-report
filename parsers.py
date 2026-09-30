# -*- coding: utf-8 -*-
"""从 .rdata 字面量簇还原各 JSON/XML 解析器读取的字段名。
   原理：MSVC 会把同一解析器用到的字符串常量连续排在 .rdata 里，
        解析器日志串（如 'CGetPathInfoJson::Parser status(%d)'）紧邻其字段名簇。
"""
import re, json, sys

MODS = ["QFileSync.dll","QsyncAPI.dll","QsyncLib.dll","Qsync.exe"]

def strings(path, minlen=2):
    data = open(path,'rb').read()
    res = []
    for m in re.finditer(rb'[\x20-\x7e]{%d,}' % minlen, data):
        res.append((m.start(), m.group().decode('ascii')))
    for m in re.finditer(rb'(?:[\x20-\x7e]\x00){%d,}' % minlen, data):
        res.append((m.start(), m.group().decode('utf-16le')))
    res.sort()
    return res

FIELD = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{1,40}$')
NOISE = {'true','false','null','NULL','http','https','sid','func','POST','GET',
         'UTF-8','utf-8','TCP','status','result','success','error'}

def looks_field(s):
    if not FIELD.match(s): return False
    if ' ' in s or '%' in s or '(' in s: return False
    if s in NOISE: return False
    if s.startswith(('.','?','__')): return False
    if re.match(r'^(api-ms|KERNEL|USER|OLE|ADVAPI|SHELL|SHLWAPI|Qt5|MSVC|VCRUNTIME)', s): return False
    if s.isupper() and len(s) > 6: return False
    return True

def clusters(paths, parser_re, window_strings=45, max_bytes=0x900):
    out = {}
    for p in paths:
        ss = strings(p)
        for i,(off,s) in enumerate(ss):
            if re.search(parser_re, s):
                fields, logs = [], []
                for j in range(i+1, min(i+window_strings, len(ss))):
                    o2, s2 = ss[j]
                    if o2 - off > max_bytes: break
                    if looks_field(s2):
                        if s2 not in fields: fields.append(s2)
                    elif ('%' in s2 or '(' in s2) and len(s2) < 200:
                        if s2 not in logs: logs.append(s2)
                if fields:
                    out.setdefault(s, []).append({"module":p, "off":hex(off),
                                                  "fields":fields, "next_logs":logs[:4]})
    return out

if __name__ == "__main__":
    pat = sys.argv[1] if len(sys.argv)>1 else r'C[A-Za-z]*Json|C[A-Za-z]*Xml'
    res = clusters(MODS, pat)
    for k in sorted(res):
        for e in res[k]:
            print(f"\n### {k}   [{e['module']}@{e['off']}]")
            print("  fields:", ", ".join(e['fields'][:40]))
            if e['next_logs']: print("  near  :", " | ".join(x[:80] for x in e['next_logs']))
