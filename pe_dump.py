import pefile, sys, os, json
D="/home/aaaa/.wine/drive_c/Program Files (x86)/QNAP/Qsync"
targets=["Qsync.exe","QsyncSvc.exe","QsyncAPI.dll","QsyncLib.dll","QFileSync.dll","QsyncSync.dll",
         "QsyncCloudFile.dll","RdiffDll.dll","QsyncExt.dll","QsyncBackupDll.dll","QSystemLib.dll",
         "Qfile.dll","QUiLib.dll","QASYNCLOGGER.dll","libcurl.dll","quazip.dll"]
out={}
for t in targets:
    p=os.path.join(D,t)
    if not os.path.exists(p): continue
    pe=pefile.PE(p, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT'],
                                           pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
    info={"machine":hex(pe.FILE_HEADER.Machine),"timestamp":pe.FILE_HEADER.TimeDateStamp,
          "exports":[],"imports":{}}
    if hasattr(pe,'DIRECTORY_ENTRY_EXPORT'):
        for e in pe.DIRECTORY_ENTRY_EXPORT.symbols:
            info["exports"].append((e.ordinal, e.name.decode() if e.name else None))
    if hasattr(pe,'DIRECTORY_ENTRY_IMPORT'):
        for m in pe.DIRECTORY_ENTRY_IMPORT:
            info["imports"][m.dll.decode(errors='replace')]=[i.name.decode() if i.name else f"ord{i.ordinal}" for i in m.imports]
    out[t]=info
json.dump(out, open("/home/aaaa/.wine/drive_c/Program Files (x86)/QNAP/Qsync/qsync-analysis/out/pe_dump.json","w"), indent=1)
for t,i in out.items():
    print(f"\n===== {t}  ({i['machine']})  exports={len(i['exports'])} imports={len(i['imports'])}")
    for o,n in i["exports"][:200]:
        print(f"   {o:4d} {n}")
