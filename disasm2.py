import pefile, sys
from capstone import *
path=sys.argv[1]; pe=pefile.PE(path, fast_load=True)
pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
data=open(path,'rb').read(); ib=pe.OPTIONAL_HEADER.ImageBase
md=Cs(CS_ARCH_X86, CS_MODE_32)
def dis_va(va, n=60):
    rva=va-ib; sec=pe.get_section_by_rva(rva)
    off=rva-sec.VirtualAddress+sec.PointerToRawData
    out=[]
    for i in md.disasm(data[off:off+n*7], va):
        out.append(f"{i.address:08x}  {i.mnemonic:8s} {i.op_str}")
        if len(out)>=n: break
    return out
for e in pe.DIRECTORY_ENTRY_EXPORT.symbols:
    nm=e.name.decode() if e.name else None
    if nm in sys.argv[2:]:
        print(f"===== {nm} @ {hex(ib+e.address)} =====")
        for l in dis_va(ib+e.address, 45): print(l)
        print()
