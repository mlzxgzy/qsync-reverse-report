import pefile, sys, re
from capstone import *
def load(p):
    pe=pefile.PE(p, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
    return pe
def off2rva(pe, off):
    return pe.get_rva_from_offset(off)
def find_string_refs(path, needle, maxrefs=10):
    pe=load(path); data=open(path,'rb').read()
    hits=[m.start() for m in re.finditer(re.escape(needle), data)]
    out=[]
    for h in hits[:4]:
        rva=off2rva(pe,h)
        if rva is None: continue
        pat=rva.to_bytes(4,'little')
        for m in re.finditer(re.escape(pat), data):
            out.append((h, rva, m.start()))
    return pe, hits, out[:maxrefs]
if __name__=="__main__":
    path=sys.argv[1]; needle=sys.argv[2].encode()
    pe,hits,refs=find_string_refs(path,needle)
    print(f"string occurrences: {[hex(h) for h in hits]}")
    for h,rva,roff in refs:
        print(f"  str@{hex(h)} rva={hex(rva)} xref@{hex(roff)}")
