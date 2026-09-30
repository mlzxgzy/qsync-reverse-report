import pefile, sys
from capstone import *
def setup(path):
    pe=pefile.PE(path, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
    ib=pe.OPTIONAL_HEADER.ImageBase
    return pe, ib
def func_code(pe, path, rva, n=400):
    data=open(path,'rb').read()
    sec=pe.get_section_by_rva(rva)
    off=rva-sec.VirtualAddress+sec.PointerToRawData
    return data[off:off+n], pe.OPTIONAL_HEADER.ImageBase+rva
def dis(path, name, n=140):
    pe,ib=setup(path)
    for e in pe.DIRECTORY_ENTRY_EXPORT.symbols:
        if e.name and e.name.decode()==name:
            code, va = func_code(pe, path, e.address, n*6)
            md=Cs(CS_ARCH_X86, CS_MODE_32); md.detail=True
            out=[]
            for i in md.disasm(code, va):
                out.append(f"{i.address:08x}  {i.mnemonic:8s} {i.op_str}")
                if i.mnemonic=='ret' and len(out)>4: break
            return out
    return [f"export {name} not found"]
if __name__=="__main__":
    path=sys.argv[1]
    for nm in sys.argv[2:]:
        print(f"\n===== {nm} =====")
        for l in dis(path, nm, 120): print(l)
