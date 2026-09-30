# -*- coding: utf-8 -*-
"""从 URL 模板自动抽取「端点 → 参数(+printf 类型)」结构化规格"""
import re, json, glob, collections

TYPES = {'%d':'int','%u':'uint','%ld':'int32','%lu':'uint32','%lld':'int64',
         '%llu':'uint64','%s':'string','%ls':'wstring','%ls':'string','%f':'float'}
# 归一化：把 %ls / %s 统一成 %s 再解析
def norm(t):
    return t.replace('%ls','%s')

def parse_tmpl(t):
    """返回 (path, [(name, type)])"""
    t = norm(t)
    t = t.replace('%ls%ls','%s').replace('%s%s:%d','%s').replace('%1%2:%3','%s')
    m = re.match(r'^[^/]*?(/(?:%s)?cgi-bin.*|/share\.cgi.*|/oauth.*|/v1.*|/api.*)$', t)
    p = m.group(1) if m else t
    # 拆 path / query
    if '?' in p:
        path, q = p.split('?', 1)
    else:
        path, q = p, ''
    params = []
    for kv in q.split('&') if q else []:
        if not kv: continue
        if '=' in kv:
            k, v = kv.split('=', 1)
            ty = TYPES.get(v, 'string' if '%' in v else 'const')
            params.append((k, ty, v))
        else:
            # 形如 'func=login' 已处理；裸字段
            params.append((kv, 'string', ''))
    return path, params

def main():
    rows = collections.defaultdict(lambda: {'func': set(), 'params': collections.OrderedDict(),
                                            'mods': set(), 'raw': set()})
    for line in open("qsync-analysis/out/url_inventory.txt"):
        mod, _, tpl = line.rstrip('\n').partition('\t')
        path, params = parse_tmpl(tpl)
        if not path.startswith('/'): continue
        func = None
        for k, ty, v in params:
            if k == 'func': func = v
        key = (path, func)
        r = rows[key]
        r['func'].add(func); r['mods'].add(mod); r['raw'].add(tpl)
        for k, ty, v in params:
            if k == 'func': continue
            r['params'].setdefault(k, set()).add(ty)
    out = []
    for (path, func), r in sorted(rows.items(), key=lambda x: (x[0][0] or '', str(x[0][1]))):
        out.append({
            'path': path,
            'func': func,
            'modules': sorted(r['mods']),
            'params': [{'name': k, 'types': sorted(v)} for k, v in r['params'].items()],
            'raw_templates': sorted(r['raw'])[:3],
        })
    json.dump(out, open("qsync-analysis/out/api_endpoints.json","w"), ensure_ascii=False, indent=1)
    print(f"提取端点 {len(out)} 条")
    # 打印参数最多的若干条作为抽样
    for e in sorted(out, key=lambda x: -len(x['params']))[:8]:
        print(f"\n{e['path']}  func={e['func']}")
        print("   " + ", ".join(f"{p['name']}:{('/'.join(p['types']))}" for p in e['params']))

main()
