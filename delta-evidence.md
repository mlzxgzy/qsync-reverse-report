# QNAP Qsync for Windows — 增量传输 / 版本化(versioning) / delta 同步 机制逆向证据报告

目标版本：Qsync 6.1.0.0831 Windows（PE 构建时间 2026-08-31，Qt5 + MSVC 原生）。
分析对象：`RdiffDll.dll`、`QsyncSync.dll`、`QFileSync.dll`、`QsyncAPI.dll`、`QsyncLib.dll`。
所有偏移均为 **RVA**（`模块@0x偏移`，镜像基址 `0x10000000`）。未运行 Qsync，未联网。

---

## 0. 结论速览

| # | 结论 | 置信度 |
|---|---|---|
| 1 | `RdiffDll.dll` 是 QNAP 自己封装的 **librsync**（含 `rdiff` CLI 代码），29 个导出全部是**未修饰的 C 名字、`__cdecl`**（不存在 `?rdiff_sign@@YAHPAE...` 这类 C++ 修饰名）。 | 高 |
| 2 | 客户端实际只用了其中 3 个：`rdiff_sign` / `rdiff_delta` / `rdiff_patch`（`QsyncSync.dll` 静态导入）。 | 高 |
| 3 | 块大小默认 **0x100000 = 1 MiB**；强校验和长度默认 **0x10 = 16 字节**。QsyncSync 调用点显式传 1 MiB / 16。 | 高 |
| 4 | 滚动弱校验和是经典 rsync/librsync 形式：`A=Σ(b+31)`，`B=Σ(n-i)(b+31)`，`weak=(B<<16)|(A&0xffff)`，`CHAR_OFFSET=31`。 | 高 |
| 5 | 强校验和 = **MD4**（RFC1320，IV `0x67452301…`），取前 `sum_size`（=16）字节。 | 高 |
| 6 | signature 文件 = librsync 原生二进制格式：`magic(4B BE)=0x72730136` + `block_len(4B BE)` + `strong_sum_len(4B BE)` + 每块 `weak(4B BE)+strong(strong_sum_len)`。 | 高 |
| 7 | delta 文件 = `magic(4B BE)=0x72730236` + 命令流：`0x00`=END、`0x41..0x44`=LITERAL_{1,2,4,8}、`0x45..0x54`=COPY_{where{1,2,4,8}}_{len{1,2,4,8}}，所有整数 **大端**。 | 高 |
| 8 | 版本化 CGI 有 12 个 `func=versioning_*` 端点，Qsync 同步引擎（QsyncSync+QFileSync）用其中的 lock/gen_sig/get_sig/stat_delta/gen_delta/get_delta/upload_file/commit_upload/unlock/clean_version；`versioning_probe/stat/gen_file/delete_all/get_progress` 只在 `QsyncAPI.dll`（Qfile 客户端）里。 | 高 |
| 9 | delta 与整文件上传的判定点有两处：① `copy_delta_file` 先做 `QFileStatFileDelta`(`func=versioning_stat_delta`)，失败/不满足条件 → 走整文件路径；② `copy_file_delta_sync` 里 `[struct+0x1e090] & 0x10000000` 标志位 + 64 位尺寸比较。 | 中高 |
| 10 | 服务端日志（`func=qbox_get_sync_log` / `qbox_get_max_log` / `qbox_write_log`）由 `QsyncLib.dll` 使用（水印参数 `lower`/`number`），与 delta 的具体耦合方式未完全确认。 | 中 |

---

## 1. 方法与工具

* `qsync-analysis/.venv/bin/python` + `pefile` + `capstone`（x86 32 位模式，反汇编窗口按 `.text` 中的 `0xCC` 填充定位函数边界）。
* 字符串定位：现有 `out/str_<模块>.txt` + 自建带 RVA 的字符串扫描（区分 ASCII / UTF-16LE —— 这一点很关键：`QsyncAPI.dll` 的 URL 模板是 **UTF-16 宽字符串**，`QFileSync.dll` 的是 ASCII）。
* 导入/导出表：`out/pe_dump.json`。

---

## 2. RdiffDll.dll 总体事实

* PE：`machine=0x14c`（x86），29 个导出，**只导入 `KERNEL32.dll`**（静态 CRT）——证据：`out/pe_dump.json` → `RdiffDll.dll.imports == ['KERNEL32.dll']`。
* **导出名是未修饰的 C 名字，不是 C++ 修饰名。** 证据：`pe_dump.json` 中 29 个导出名为 `rdiff_combine … rdiff_split`（无 `?`/`@@`）；这些名字在 `.rdata` 中作为普通 ASCII 字符串存在（`RdiffDll.dll@0x000261xx` 区）。因此"先确认修饰名"的提示不成立。
* **调用约定**：所有导出函数结尾都是 `mov esp,ebp / pop ebp / ret`（无 `ret N`）→ `__cdecl`；参数全部从 `[ebp+8]` 起读。例：`RdiffDll.dll@0x00003740 rdiff_set_input_size`：`mov eax,[ebp+8]; mov [0x100288b0],eax; pop ebp; ret`。
* 模块内部的非导出辅助函数使用 `__fastcall`（第 1 参 `ecx`、第 2 参 `edx`、其余入栈），例：`fopen` 包装 `RdiffDll.dll@0x00001e90`（`ecx=name, edx=mode`）。
* **librsync 谱系证据**：`RdiffDll.dll@0x000268c8 "librsync"`、`@0x000260ac "rs_job_t"`、`@0x000265c0 "rs_signature_t"`、`@0x000265d0 "scoop buffer"`、`@0x00025f78 "emit DELTA magic"`、`@0x00026174 "sent header (magic %#x, block len = %d, strong sum len = %d)"`、`@0x00026354 "bogus command 0x%02x"`；PDB 路径 `RdiffDll.dll@0x00026d84 "D:\Work\GitRepos\GitLab\Qsync_Win_VS2017\ThirdParty\RdiffDll\Release\RdiffDll.pdb"`（QNAP 的第三方库目录）。
* **只有 3 个导出被使用**：`QsyncSync.dll` 的导入表中 `RdiffDll.dll = ['rdiff_patch','rdiff_sign','rdiff_delta']`；全工程再无其它模块导入 `RdiffDll.dll`（`pe_dump.json` 全量扫描）。其余 26 个导出在本安装包里是死代码（其中 `rdiff_comp` 甚至含空指针写，见 §3.4）。
* 全局状态（`.data`，初值即默认值，`RdiffDll.dll@0x000288b0` 起）：

```
0x000288b0  00 00 10 00   -> input_size  = 0x00100000 (1 MiB)
0x000288b4  00 00 10 00   -> output_size = 0x00100000 (1 MiB)
0x000288b8  80 00 00 00   -> 0x80
0x000288f8  00 00 10 00   -> block_size  = 0x00100000 (1 MiB)
0x000288fc  10 00 00 00   -> sum_size    = 0x10 (16)
```

---

## 3. 29 个导出：签名与语义

统一约定：返回值为 `int`，取值是 librsync 的 `rs_result`（见 §7），`0` = 成功；
`100 (0x64)` = 打开文件失败；`102 (0x66)` = 内存分配失败（这两个常量由 QNAP 包装层直接写入 eax，例：`RdiffDll.dll@0x00003834 mov eax,0x64`）。

### 3.1 全局参数存取（10 个，均无参/单参 `int`）

| 导出 | RVA | 语义 | 证据 |
|---|---|---|---|
| `rdiff_get_input_size` | 0x3750 | `int f(void)`；读全局 0x100288b0 | `mov eax,[0x100288b0]; ret` |
| `rdiff_set_input_size` | 0x3740 | `void f(int)` | `mov [0x100288b0],eax` |
| `rdiff_get_output_size` | 0x3770 | `int f(void)`；读 0x100288b4 | `mov eax,[0x100288b4]` |
| `rdiff_set_output_size` | 0x3760 | `void f(int)` | `mov [0x100288b4],eax` |
| `rdiff_get_block_size` | 0x37a0 | `int f(void)`；读 0x100288f8 | `mov eax,[0x100288f8]` |
| `rdiff_set_block_size` | 0x3780 | `void f(int)` | `mov [0x100288f8],eax` |
| `rdiff_set_block_size_default` | 0x3790 | `void f(void)`；**默认 1 MiB** | `mov dword ptr [0x100288f8],0x100000; ret` |
| `rdiff_get_sum_size` | 0x37d0 | `int f(void)`；读 0x100288fc | `mov eax,[0x100288fc]` |
| `rdiff_set_sum_size` | 0x37b0 | `void f(int)` | `mov [0x100288fc],eax` |
| `rdiff_set_sum_size_default` | 0x37c0 | `void f(void)`；**默认 16** | `mov dword ptr [0x100288fc],0x10; ret` |

### 3.2 主流程（3 个；也就是 Qsync 真正使用的 3 个）

| 导出 | RVA | 签名 | 语义 | 证据 |
|---|---|---|---|---|
| `rdiff_sign` | 0x37e0 | `int rdiff_sign(const char* basis, const char* sigout, int block_len, int strong_len)` | 对 `basis` 生成 signature 写入 `sigout` | `fopen([ebp+8],"rb")→esi`、`fopen([ebp+0xc],"wb")→ebx`；`[edi+0x14]=[ebp+0x10]`、`[edi+0x18]=[ebp+0x14]`（job 的 block_len / strong_sum_len，由 SIG_HEADER 写进文件头）；`call 0x10005f60`(=rs_whole_run(job,in,out)) |
| `rdiff_delta` | 0x3940 | `int rdiff_delta(const char* sigfile, const char* newfile, const char* deltaout)` | 用 `sigfile` 作 basis 签名，对 `newfile` 生成 delta 写入 `deltaout` | `fopen([ebp+8],"rb")→edi` 交给 `call 0x10006080`(loadsig)；`fopen([ebp+0xc],"rb")→ebx`；`fopen([ebp+0x10],"wb")→[esp+0x10]`；`call 0x100058b0`(rs_build_hash_table)；`rs_whole_run(job,ebx,[esp+0x10])` |
| `rdiff_patch` | 0x3b60 | `int rdiff_patch(const char* basis, const char* deltafile, const char* out)` | 把 `deltafile` 打到 `basis` 上生成 `out` | `fopen([ebp+8],"rb")→esi`(basis)、`fopen([ebp+0xc],"rb")→ebx`(delta)、`fopen([ebp+0x10],"wb")→[esp+0x10]`(out)；job 名 `@0x000264d4 "patch"`；`[edi+0x160]=0x100011d0`、`[edi+0x164]=esi`（basis 回调/句柄）；随后初始化 MD4 上下文（见 §6） |

### 3.3 块级工具

| 导出 | RVA | 签名 | 语义 | 证据 |
|---|---|---|---|---|
| `rdiff_get_block` | 0x4e60 | `int rdiff_get_block(const char* src, const char* dstfile, int block_size, int index)` | 把 `src` 的第 `index` 块（长 `block_size`）写入文件 `dstfile` | `fopen([ebp+8],"rb")→edi`；`malloc([ebp+0x10])`；`fseek(f, block_size*[ebp+0x14], SEEK_SET)`（`imul ecx,[ebp+0x14]; call 0x10008c92`）；`fread`+`fopen([ebp+0xc],"wb")`+`fwrite` |
| `rdiff_fget_block` | 0x4f60 | `int rdiff_fget_block(FILE* in, FILE* out, int block_size, int index)` | 同上，FILE* 版 | `fseek([ebp+8], block_size*[ebp+0x14], 0)`；`fread(buf,1,block_size,in)`；`fwrite(buf,1,n,[ebp+0xc])` |
| `rdiff_getnumberofchunk` | 0x46f0 | `int rdiff_getnumberofchunk(const char* sigfile, int* out_count)` | 读出 signature 的块数 | loadsig 后 `mov ecx,ebx; mov edx,[ebx+8]; mov [eax],edx`（`[ebx+8]` = sig->count） |
| `rdiff_compare` | 0x47c0 | `int rdiff_compare(const char* f1, const char* f2, int* equal)` | 比较两文件整体 MD4（16 进制字符串比较），`*equal = (strcmp(hex1,hex2)==0)` | 两次 `malloc(0x21)`（33 字节 = 32 hex + NUL），`call 0x100061a0(f, buf)` 求摘要→hex，`sete cl; mov [eax],ecx`（`eax=[ebp+0x10]` 出参），返回 0 |
| `rdiff_mdfour` | 0x48f0 | `int rdiff_mdfour(const char* file, char out[33])` | 计算整个文件的 MD4 并以小写 16 进制写入 `out`（32 字符 + NUL） | `fopen([ebp+8],"rb")→esi`；`mov edx,[ebp+0xc]; mov ecx,esi; call 0x100061a0`；失败返回 `lea eax,[esi+0x64]`(=100) |
| `rdiff_num_to_hex_char` | 0x5010 | `int rdiff_num_to_hex_char(char* buf, int value, int width)` | `sprintf(buf,"%0*X",width,value)`（格式串 `@0x00026068 "%0*X"`） | `push [ebp+0xc]; push [ebp+0x10]; push 0x10026068; push [ebp+8]; call sprintf` |

### 3.4 块比较 / 分块文件（QNAP 自加，Qsync 未使用）

| 导出 | RVA | 签名 | 语义 | 证据 / 置信度 |
|---|---|---|---|---|
| `rdiff_compsign` | 0x4110 | `int rdiff_compsign(const char* sigA, const char* sigB, void* outStruct)` | 比较两个 signature 文件，逐块分类 | loadsig(A)→`ebx`、loadsig(B)→`edi`；`cmp [ebx+0x10],[edi+0x10]` 不等则 `mov esi,0x6c`(=108)；`calloc(max(count1,count2), 8)`（`push 8; push ecx; call 0x1000fece`）；输出结构：`+0xc=count1`、`+0x10=count2`、`+8=差异数`、`+0x14=数组指针`，数组元素 8 字节 `{u32 index; u32 status}`；status：`1`=相同(`0x4380 mov [eax+edx*8+4],1`)、`2`=不同(`0x4373 …,2`)、`3`=仅第一份有(`0x43d9 …,3`)、`4`=仅第二份有(`0x43b9 …,4`)。**高** |
| `rdiff_firstsign` | 0x4550 | `int rdiff_firstsign(const char* sigfile, void* outStruct)` | 把某 signature 的全部块标记为"对方没有"（status=3），是 compsign 的引导版本 | loadsig→`edi`；`calloc(count,8)`→`[ebx+0x14]`；`[ebx]=count`、`[ebx+4]=block_len([edi+0x10])`、`[ebx+8]=count`、`[ebx+0x10]=count`；循环 `mov [eax+ecx*8],ecx; mov [eax+ecx*8+4],3`；内存失败返回 0x66=102。**高** |
| `rdiff_comp` | 0x3da0 | `int rdiff_comp(const char* sigfile, const char* datafile, const char* tag, const char* blockpath)`（形参名推断） | 用 signature 校验另一个文件的分块（逐块抽块 → 算 MD4 → 与签名逐块比对），并生成对照记录 | loadsig([ebp+8])；循环内 `rdiff_get_block([ebp+0xc] /*data*/, [ebp+0x14] /*块文件*/, i, block_len)`（`push [ebx+0x10]; push edi; push esi; push [ebp+0xc]; call 0x10004e60`），再用 `0x100061a0` 对抽出的块算摘要并与强校验和 hex 比较；`[ebp+0x10]` 是拼进记录的字符串。**注意：该函数含空指针写**——`RdiffDll.dll@0x00003e44` 处 `edi==0`（`@0x00003dbd xor edi,edi` 后未被改写），原始字节 `89 0f a3 04 00 00 00` = `mov [edi],ecx; mov [4],eax`，即向地址 0 / 4 写；因此**在线下载包中它是坏/死代码**，语义只能算部分确认。**中** |
| `rdiff_split` | 0x4950 | `int rdiff_split(const char* src, const char* prefix, int chunk_size)` | 把 `src` 按 `chunk_size` 切成 `<prefix><%04X>` 若干文件 | `malloc([ebp+0x10])` 读缓冲 + 两个 0xff 名字缓冲；`sprintf(buf,"%0*X",4,index)`（`push esi; push 4; push 0x10026068`）后接前缀 → `fopen(name,"wb")` + `fwrite`；EOF 时另建 `<prefix>SIZE`（从 `0x000264dc "SIZE"` 拷 4 字节 + `0x000264e0` 的 NUL），以 `"wt"`(`0x000264e4`) 打开并写十进制块数（`push index; push 0x000264e8 "%d"`）。**中高** |
| `rdiff_combine` | 0x4b30 | `int rdiff_combine(const char* prefix, const char* outfile)` | `split` 的逆操作：读 `<prefix>SIZE` 得块数，再顺序拼接 `<prefix><%04X>` 到 `outfile` | 先 `strcpy(buf,prefix)` + 追加 `"SIZE"` → `fopen(buf,"rt")(0x000264ec)` → `call 0x10003710(f,"%d\n", &count)`（`0x000264f0 "%d\n"`）；`fopen([ebp+8],"wb")`；`malloc(0x400)` 循环 `fread`/`fwrite`。**中高** |
| `rdiff_modify` | 0x4d00 | `int rdiff_modify(const char* dest, const char* name, int index)` | 以 `r+b` 打开 `dest`，`fseek(index*0x180000)` 后追加某个小文件的内容 | `fopen([ebp+8],"r+b")(0x000264f4)`；`imul eax,esi,0x180000`（**1.5 MiB/块**）→ `fseek`；`malloc(4)` 装 `[ebp+0xc]` 字符串并追加 `word [0x000264f8]`(='.'+NUL) 作为源文件名；循环 `fread(0x400)/fwrite`。语义只到"按 1.5 MiB 步长回填"这一层，**中**（Qsync 未用） |
| `rdiff_generate_chunk_list` | 0x4fc0 | `int rdiff_generate_chunk_list(void** ppOut)` | `*ppOut = calloc(1,0x18)`（`push 0x18; push 1; call 0x1000fece`）；返回 0 | 高 |
| `rdiff_free_chunk_list` | 0x4fe0 | `void rdiff_free_chunk_list(void* p)` | 释放 `p->[0x14]` 再释放 `p` | `mov eax,[esi+0x14]; …free…; xorps xmm0,xmm0; movups [esi],xmm0; …free(esi)` |
| `rdiff_copy_file` | 0x5030 | `int rdiff_copy_file(const char* src, const char* dst)` | 尾调用内部拷贝例程 0x10001df0：`fopen(src,"rb")`+`fopen(dst,"wb")`+ **1 MiB 缓冲**(`push 0x100000`)循环读写；返回 0 成功 / 1 src 打开失败 / 2 dst 打开失败 | `mov edx,[ebp+0xc]; mov ecx,[ebp+8]; jmp 0x10001df0`；0x1df0 实体见 §3.5 |
| `rdiff_move_file` | 0x5040 | `int rdiff_move_file(const char* src, const char* dst)` | 先 `rdiff_copy_file`，成功后 `remove(src)`；`remove` 失败返回 3 | `call 0x10001df0; test eax,eax; jne ret; push [ebp+8]; call 0x10009753(remove); mov ecx,3; cmovne eax,ecx` |

### 3.5 参考：内部文件拷贝例程（`0x1df0`）

`RdiffDll.dll@0x00001df0`：`fopen_s(src,"rb")`（`0x1000943e`）→ 失败 `return 1`；
`fopen_s(dst,"wb")` → 失败 `fclose(src); return 2`；
`malloc(0x100000)`；`while(!feof(src)){ n=fread(buf,1,0x100000,src); fwrite(buf,1,n,dst); }`；返回 0。
（`RdiffDll.dll@0x00001e33 push 0x100000; call 0x1000b395` / `@0x00001e71 test eax,eax; je 0x10001e50`）

---

## 4. signature / delta 头字段来源（谁写头）

`RdiffDll.dll@0x00002b10`（signature 生成 job 的起始状态，`rdiff_sign` 在 `@0x00003882` 把它写进 `[job+0xc]`）：

```
0x2b1b  mov edx,4
0x2b20  push 0
0x2b22  push 0x72730136          ; SIG magic
0x2b27  mov ecx,esi
0x2b29  call 0x10002f60          ; rs_squirt_n(job, len=4, value, 0)
0x2b2e  mov eax,[esi+0x14]       ; block_len
0x2b34  push edx; push eax; mov edx,4; call 0x10002f60
0x2b40  mov eax,[esi+0x18]       ; strong_sum_len
0x2b46  push edx; push eax; mov edx,4; call 0x10002f60
0x2b52  push [esi+0x18]; push [esi+0x14]; push 0x72730136
0x2b5d  push 0x10026174          ; "sent header (magic %#x, block len = %d, strong sum len = %d)"
0x2b62  call 0x10005d10          ; rs_trace
0x2b78  mov dword ptr [esi+0xc],0x10002d80   ; 下一状态 = 逐块发签名
```

**字序**：`0x10002f60` 是"写 N 字节大端"的通用发射器（`RdiffDll.dll@0x00002f60`）：

```
0x2f77  lea esi,[edi-1]                 ; edi = 字节数
0x2f90  mov byte ptr [ebp+esi-0xc],cl   ; 从高地址向低地址填
0x2f94  shrd ecx,eax,8
0x2f98  sar eax,8
0x2f9b  sub esi,1
0x2f9e  jns 0x10002f90
0x2fd3  call 0x10007d50                 ; memcpy 到输出缓冲 [ebx+0x12c]，长度记在 [ebx+0x140]
```
即 **大端（MSB first）**。字节数 `>8` → `mov eax,0x6b`（=107）。

---

## 5. 滚动校验和（弱校验和）公式 —— 完整推导

### 5.1 delta 扫描主循环

`RdiffDll.dll@0x0000131e`（在 0x1280 起的 `rs_delta_s_scan` 中）：

```
0x131e  mov edx,[esi+0x11c]        ; 扫描缓冲基址
0x1326  mov ebx,[esi+0x128]        ; 当前窗口起点 pos
0x132c  mov eax,[esi+0x14]         ; block_len = n
0x132f  add edx,ebx
0x1331  movzx ecx,byte ptr [edx+eax]   ; in  = buf[pos+n]
0x1335  movzx eax,byte ptr [edx]       ; out = buf[pos]
0x1338  sub ecx,eax                    ; in - out
0x133a  add [esi+0x2c],ecx             ; A += (in - out)
0x133d  movzx eax,byte ptr [edx]       ; out
0x1340  mov ecx,[esi+0x2c]             ; A'
0x1343  add eax,0x1f                   ; out + 31        <== CHAR_OFFSET = 31
0x1346  imul eax,[esi+0x28]            ; (out+31) * n
0x134a  sub ecx,eax
0x1352  add [esi+0x30],ecx             ; B += A' - n*(out+31)
```

job 状态字段：`+0x28 = n(block_len)`、`+0x2c = A(s1)`、`+0x30 = B(s2)`、`+0x128 = pos`、`+0x11c = buffer`。

### 5.2 弱校验和的组装

```
0x13b6  movzx eax,word ptr [esi+0x2c]  ; A & 0xffff
0x13b9  mov ecx,[esi+0x30]             ; B
0x13be  shl ecx,0x10
0x13c1  or ecx,eax                     ; weak = (B<<16) | (A&0xffff)
```
同一形式也在弱匹配函数里出现：`RdiffDll.dll@0x0000165e-0x00001672`
（`mov eax,[edx+0x30]; shl eax,0x10; … movzx eax,word ptr [edx+0x2c]; or edx,eax`）。

### 5.3 一次性（非滚动）计算与调试自检

`RdiffDll.dll@0x000053e0`（`calc weak sum from scratch`，出口把 s1/s2 存回 acc 结构）：

```
0x53ec  add dword ptr [ebx],edi        ; acc.total_len += len
0x5405  movzx ecx,byte ptr [edx]
0x540b  add eax,ecx                    ; A += b   (配合下面 0x1f 的补正)
0x5411  add esi,eax                    ; B += A
...
0x548a  add eax,0x1f0                  ; 16*31 = 0x1f0   (小循环里逐字节 add eax,0x1f)
0x548f  add esi,0x1078                 ; 31*(16*17/2) = 0x1078
...
0x54ab  add eax,0x1f                   ; 逐字节：A += 31
0x54ae  add eax,ecx                    ; A += b
0x54b0  add esi,eax                    ; B += A
0x54b8  mov [ebx+8],esi                ; s2
0x54bc  mov [ebx+4],eax                ; s1
```
即 `A=Σ(b+31)`、`B=Σ(n-i)(b+31)`（权重 n..1），与滚动公式完全自洽。

调用点：`RdiffDll.dll@0x0000160d/0x00001626`（窗口不满时从零计算），随后
`RdiffDll.dll@0x0000162e push [edi]; push 0x10025e1c "calculate weak sum from scratch length %d"`。
调试模式下会把滚动值与重算值比较：`RdiffDll.dll@0x000013d1 push edx; push ecx; push 0x10025dd8 "mismatch between rolled sum %#x and check %#x"`。

### 5.4 哈希桶

`RdiffDll.dll@0x0000167a`：`eax = weak; eax >>= 16; eax += weak; esi = (u16)eax` → 用低 16 位作桶索引
（`0x1688 mov eax,[ebx+0x1c]` 桶数组，`0x168f mov edi,[eax+esi*4]` 链头，`0x16aa movzx eax,word ptr [ecx]` 比较弱校验和，
`0x16cb` trace `"found weak match for %08x in token %d"`，之后逐字节比较强校验和 `[ebx+0x14]`(=strong_sum_len) 字节，
失败 trace `RdiffDll.dll@0x00001794 "this was a false positive, the strong sig doesn't match"`）。
块签名记录大小 24 字节：`lea esi,[eax+eax*2]; shl esi,3`（`0x16b8-0x16be`），即 `{u32 weak; u32 i; u8 strong[16]}`。

---

## 6. `rdiff_mdfour` 用的是什么哈希 —— **MD4**

1. `rdiff_patch` 里对 job+0x50 的 0x5c 字节做 `memset` 后写入：
   `RdiffDll.dll@0x00003cae mov dword ptr [edi+0x50],0x67452301`、
   `@0x00003cb7 …0xefcdab89`、`@0x00003cc0 …0x98badcfe`、`@0x00003cc7 …0x10325476`、`@0x00003cd2/+0x60=0`、`@0x00003cd9/+0x64=0`。
   同一常量也在 `RdiffDll.dll@0x000016f6 movaps xmm0,xmmword ptr [0x10026a70]` 使用；该处 16 字节为
   `RdiffDll.dll@0x00026a70: 01 23 45 67 89 ab cd ef fe dc ba 98 76 54 32 10`
   = 小端 dword `0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476` = **RFC1320 MD4 初始向量**。
   （MD5 的 IV 相同，但区分点在轮函数；librsync 只用 MD4。）
2. 字符串：`RdiffDll.dll@0x0002616c "mdfour"`；类型名 `@0x000260ac "rs_job_t"`。
3. 摘要计算/输出函数：`RdiffDll.dll@0x00002820`（喂块，强校验和路径：弱匹配成功后 `push [esp+0x18]; call 0x10002820` @0x1720）与 `0x00002920`（取结果，`lea edx,[esp+0x94]; lea ecx,[esp+0x30]; call 0x10002920` @0x172d）。
4. 16 进制化查表：`RdiffDll.dll@0x00024d98 "0123456789abcdef"`（`movzx ecx,byte ptr [ecx+0x10024d98]`，见 `rdiff_comp` @0x3ede、`rdiff_compsign` @0x42cd）。
5. 长度：signature 头里的 `strong_sum_len` 被限制为 `1..0x10`
   （`RdiffDll.dll@0x00005230 cmp ebx,0x10; ja 0x1000526d`，越界 trace `@0x000264fc "strong sum length %d is implausible"`，返回 `0x6a`）；
   Qsync 传 16 → 即**完整 MD4 摘要**。

---

## 7. 返回码（`rs_result`）—— 由 `rs_strerror` 表反推（强证据）

`RdiffDll.dll@0x00002e60` 是 `rs_strerror`：`cmp ecx,0x6b; ja → "unexplained problem"`，否则
`movzx eax,byte ptr [ecx+0x10002eec]`（索引表）→ `jmp [eax*4+0x10002ebc]`（跳转表，0x10002ebc 起 16 项，见下表）。
解码结果：

| code | 出错信息（字符串 RVA 与原文） | 对应 librsync 名字（推断） | 本 DLL 中的使用点 |
|---|---|---|---|
| 0 (0x00) | `0x000261ec "OK"` | RS_DONE | 全部成功返回 |
| 1 (0x01) | `0x00026200 "blocked waiting for input or output buffers"` | RS_BLOCKED | job 驱动 |
| 2 (0x02) | `0x000261f0 "still running"` | RS_RUNNING | job 驱动 |
| 100 (0x64) | `0x0002629c "IO error"` | RS_IO_ERROR | `rdiff_sign/delta/patch/comp/compare/mdfour/get_block/getnumberofchunk` 打开文件失败（`mov eax,0x64` @0x3834、@0x399e、@0x3bb6、@0x3e09、@0x4811、@0x4908、@0x4e7c、@0x4717） |
| 101 (0x65) | `0x000262a8 "bad command line syntax"` | RS_PARAM_ERROR | — |
| 102 (0x66) | `0x0002628c "out of memory"` | RS_MEM_ERROR | `rdiff_comp`@0x3e59、`rdiff_firstsign`@0x4603 分配失败 |
| 103 (0x67) | `0x00026250 "unexpected end of input"` | RS_INPUT_ENDED | **signature 读完后用它表示 EOF**：`SIG_BLOCK_READ` `RdiffDll.dll@0x000050cb cmp eax,0x67; cmove eax,ecx(0)` → 把 103 归一成 0 |
| 104 (0x68) | `0x0002622c "bad magic number at start of stream"` | RS_BAD_MAGIC | sig magic 不符 `@0x000053a0 mov eax,0x68`；delta magic 不符 `@0x0000369a mov eax,0x68` |
| 105 (0x69) | `0x00026278 "unimplemented case"` | RS_UNIMPLEMENTED | — |
| 106 (0x6a) | `0x00026268 "stream corrupt"` | RS_CORRUPT | `strong_sum_len` 不合理 `@0x0000527b`、`block_len < 1` `@0x000052f1`、patch 遇到非法命令 `@0x00003256` |
| 107 (0x6b) | `0x000262c0 "library internal error"` | RS_INTERNAL_ERROR | 整数长度 >8 `@0x00003007` |
| 108 (0x6c) | **索引表越界，未定义** | —（本构建新增/未命名） | `rdiff_delta` "no signature is loaded into the job"`@0x00001a87`；`rdiff_compsign` block_len 不一致 `@0x000041ef` |

---

## 8. signature 文件二进制格式

**生成端**（§4 的 `0x2b10`）与**解析端**（`SIG_LOAD_MAGIC @0x5320` → `SIG_LOAD_BLOCKLEN @0x5290` → `SIG_LOAD_STRONG @0x51c0` → `SIG_BLOCK_READ @0x5070` → 强校验和状态 `0x50e0`）双向印证：

| 偏移 | 长度 | 含义 | 证据 |
|---|---|---|---|
| 0 | 4 | magic = `0x72730136`，**大端** → 字节 `72 73 01 36`（"rs\x01\x36"） | 写：`@0x00002b22 push 0x72730136`；读：`@0x0000538d cmp edi,0x72730136`，不符 → `push 0x10026574 "wrong magic number %#10x for signature"` + 返回 104 |
| 4 | 4 | `block_len`，大端 | 写：`@0x00002b2e mov eax,[esi+0x14]`；读：`@0x000052b5-0x000052db`（`movzx esi,[eax]; mov bl,[eax+2]; mov ch,[eax+3]; … shl esi,8; or` 逐字节大端重组）→ `mov [edi+0x14],esi` |
| 8 | 4 | `strong_sum_len`，大端，必须 `1..16` | 写：`@0x00002b40 mov eax,[esi+0x18]`；读：`@0x000051ed-0x00005227`（同样大端重组 `ebx`）→ `mov [edi+0x18],ebx`；`cmp ebx,0x10; ja 0x1000526d`（`"strong sum length %d is implausible"` → 106） |
| 12 | 4 | 第 0 块 `weak_sum`，大端 | `SIG_BLOCK_READ @0x00005070`：`call 0x100057a0(job, buf, 4)` 取 4 字节 → `@0x00005097-0x000050b3` 大端重组 `edx` → `mov [esi+0x24],edx`；随后 `mov dword ptr [esi+0xc],0x100050e0`（下一状态读强校验和） |
| 16 | strong_sum_len | 第 0 块强校验和（MD4 前 N 字节，**原始字节，非 16 进制**） | 状态 `0x100050e0` 读取 `strong_sum_len` 字节；`rdiff_delta` 里直接从 `[sig+0x18] + i*24 + 8` 取 `strong_sum_len` 字节比较（`@0x0000173a-0x00001760`） |
| … | 12+strong_sum_len 的整数倍 | 后续块，重复 | `rdiff_getnumberofchunk @0x00004750 mov edx,[ebx+8]` 给出块数；`rdiff_delta @0x000016b8` 用 `24*idx` 索引 `[sig+0x18]` 的块数组 |

**块数不是文件头字段**，而是读到底（`SIG_BLOCK_READ` 读到 EOF 返回 103 → 归一成 0 = 正常结束）后由 `[sig+8]` 计数。

> 说明：`.data` 里的 `rs_signature_t` 记录布局为 `{u32 weak; u32 i; u8 strong[16]}` = 24 字节（`@0x000016b8 lea esi,[eax+eax*2]; shl esi,3` + `@0x00001744 add esi,8`）。

---

## 9. delta 文件二进制格式

**magic**：`0x72730236` 大端 → 字节 `72 73 02 36`
（`RdiffDll.dll@0x00001a5f push 0; push 0x72730236; mov edx,4; call 0x10002f60`，trace `@0x00025f78 "emit DELTA magic"`）。
`rdiff_patch` 入口校验：`@0x0000367d cmp edi,0x72730236`，不符 → `push 0x1002648c "got magic number %#x rather than expected value %#x"` + 返回 104。

**命令流**（命令码 → 分发表在 `RdiffDll.dll@0x00024db0`，每条 16 字节；patch 解码器 `PATCH_CMD @0x30a0` 用
`mov eax,ebx; shl eax,4; lea edi,[eax+0x10024db0]; mov dword ptr [esi+0x48],edi` 取表项）：

| 命令字节 | 含义 | 表项字段 | 生成端证据 | 解析端证据 |
|---|---|---|---|---|
| `0x00` | END（结束） | kind=1000 | `EMIT_END @0x1560`：`xor bl,bl; mov byte ptr [ecx+esi+0x12c],bl; inc [esi+0x140]`，trace `@0x00026050 "emit END, cmd_byte=%#x"` | `RUN_CMD @0x00003233 sub eax,0x3e8; je 0x1000327c` → 返回 0（完成） |
| `0x41/0x42/0x43/0x44` | LITERAL，后跟 1/2/4/8 字节**大端长度**，再跟该长度的原始字节 | kind=1001，`[+8]`=1/2/4/8 | `EMIT_LITERAL @0x1ae0`：按长度选 `bl`=`0x41/0x42/0x43`（`@0x1b57 mov ebx,0x41`、`@0x1b50 0x42`、`@0x1b49 0x43`），写命令字节后 `call 0x10002f60(job, len, len_bytes)`，trace `@0x00025f94 "emit LITERAL_N%d(len=%d), cmd_byte=%#x"` | 表：`0x41→[+8]=1`、`0x42→2`、`0x43→4`、`0x44→8`；kind=1001 → `@0x00003238 je 0x10003290`（literal 状态机） |
| `0x45..0x48` | COPY，where 用 1 字节、len 用 1/2/4/8 字节（大端） | kind=1003，`[+8]`=where_bytes=1，`[+0xc]`=len_bytes | `EMIT_COPY @0x1bf0`：命令字节计算 `@0x1c66-0x1ccc`：`where_bytes==1 → 0x44+1=0x45`，`==2 → 0x47+2=0x49`，`==4 → 0x49+4=0x4d`，`==8 → 0x49+8=0x51`，再按 `len_bytes` `+0/+1/+2/+3`；随后两次 `call 0x10002f60` 分别写 where、len；trace `@0x00026018 "emit COPY_N%d_N%d(where=%.0f, len=%.0f), cmd_byte=%#x"` | 表：`0x45..0x48 → where=1,len=1/2/4/8`；`0x49..0x4c → where=2`；`0x4d..0x50 → where=4`；`0x51..0x54 → where=8`；kind=1003 → `@0x0000323f je 0x10003350`（copy 状态机） |
| 其它（`0x01..0x40`、`0x55`+） | 非法/保留 | kind=1001/1005 但 `[+8]=0` | — | `RUN_CMD @0x00003244 push 0x10026354 "bogus command 0x%02x"; mov eax,0x6a`（106） |

**字序 / 其它约束**：多字节整数一律**大端**（§4 的 `0x10002f60`）；`rs_patch_s_cmdbyte` 的 trace 是
`@0x00026308 "got command byte 0x%02x (%s), len_1=%.0f"`、`@0x00026334 "running command 0x%x, kind %d"`；
COPY 从 basis 读取：`@0x0002640c "copy %.0f bytes from basis at offset %.0f"`。

**slack delta 模式**：若载入的 signature 的 `block_len == 0`，delta 退化为"整段 literal"：
`RdiffDll.dll@0x00001a6e cmp dword ptr [esi+0x14],0; je 0x10001aa3` → 状态 `0x100019b0`，
trace `@0x00025ed8 "block length is zero for this delta; therefore using slack deltas"`、
`@0x00025e84 "emit slack delta for %.0f available bytes"`。
（若 `block_len!=0` 但 `[job+0x1c]==0`（没载入 signature）→ `@0x00025eb0 "no signature is loaded into the job"` + 返回 **108**。）

---

## 10. 端到端：QsyncSync 如何调用 rdiff

`QsyncSync.dll` 的 IAT：`rdiff_patch@0x1009139c`、`rdiff_sign@0x100913a0`、`rdiff_delta@0x100913a4`。
三个薄包装（把宽字符串转成 0x800 字节多字节缓冲后调用，`call 0x1002ba00` 做转换）：

| 包装 | RVA | 调用 | 参数顺序 |
|---|---|---|---|
| QRdiffSign | 0x7840 | `@0x00007896 call [rdiff_sign]` | `push [ebp+0x14]; push [ebp+0x10]; push edi([ebp+0xc]); push ebx([ebp+8])` → `(src, sig, block, sum)` |
| QRdiffDelta | 0x7680 | `@0x000076ff call [rdiff_delta]` | `push edi([ebp+0x10]); push ebx([ebp+0xc]); push esi([ebp+8])` → `(sig, new, delta)` |
| QRdiffPatch | 0x7760 | `@0x000077df call [rdiff_patch]` | `push ebx([ebp+0x10]); push edi([ebp+0xc]); push esi([ebp+8])` → `(basis, delta, out)` |

三者都返回 BOOL（成功 `lea eax,[esi+1]`=1，失败 0，见 `@0x00007722`）。

### ★ 关键：Qsync 传的块参数

`QsyncSync.dll@0x0000c4ea`（`copy_delta_file` 内，QRdiffSign 调用点）：

```
0x0000c4d5  push 0x10              ; strong_sum_len = 16
0x0000c4d7  push 0x100000          ; block_len = 1 MiB (1048576)
0x0000c4dc  lea ecx,[ebp-0x2004]   ; 签名输出路径
0x0000c4e2  lea eax,[esi+0xe08c]   ; 源文件路径
0x0000c4e8  push ecx
0x0000c4e9  push eax
0x0000c4ea  call 0x10007840        ; QRdiffSign -> rdiff_sign
```

→ **Qsync 使用 1 MiB 块 + 16 字节 MD4 强校验和**，与 `rdiff_set_block_size_default` / `rdiff_set_sum_size_default` 的常量一致。
（弱校验和 4 字节，特征值约 `block_len + 4 + 16 = 1 MiB + 20` 字节/块签名。）

---

## 11. versioning CGI 端点表（参数含义）

`QFileSync.dll` 与 `QsyncAPI.dll` 各有一套；两套 URL 一一对应：
`%s%s:%d/%scgi-bin/qsync/qsyncsrv.cgi?...`（新式，第 4 个 `%s` 是 QTS5 的 `/qsync/` 前缀位）与
`%s%s:%d/cgi-bin/filemanager/utilRequest.cgi?...`（旧式）。
（`QsyncAPI.dll` 用 `%ls` 宽字符串，`QFileSync.dll` 用窄字符串。）

| func | 参数（按顺序） | QFileSync 模板 RVA | QsyncAPI 模板 RVA | 含义 |
|---|---|---|---|---|
| `versioning_lock&check_version=1` | `sid, source_path, source_file, version_id, lockid` | 0x1ca590 / 旧式 0x1ca618 | 0x0f5840 / 0x0f5960 | 检查/续用已有版本锁 |
| `versioning_lock&create_version=1` | `sid, source_path, source_file` | 0x1ca6a8 / 0x1ca718 | 0x0f5a90 / 0x0f5b80 | **新建一个版本（拿 lockid + version_id）** |
| `versioning_unlock` | `sid, source_path, source_file, lockid` | 0x1cac10 / 0x1cac80 | 0x0f5e28 / 0x0f5f10 | 释放锁 |
| `versioning_gen_sig` | `sid, source_path, source_file, lockid, version_id` | 0x1cb190 / 0x1cb210 | 0x0f61c0 / 0x0f62c8 | **让服务端为旧版本生成 signature** |
| `versioning_get_sig` | `sid, source_path, source_file, lockid, version_id` | 0x1cb738 / 0x1cb7b8 | （同类，见下） | 下载该 signature 文件 |
| `versioning_stat_delta` | `sid, source_path, source_file, version_id` | 0x1cc0a8 / 0x1cc120 | 0x0f6a28 / 0x0f6b20 | **查询 delta 是否可行/多大（不带 lockid）** |
| `versioning_gen_delta` | `sid, source_path, source_file, lockid, version_id` | 0x1cc668 / 0x1cc6e8 | 0x0f6df8 / 0x0f6f00 | 让服务端计算 delta |
| `versioning_get_delta` | `sid, source_path, source_file, lockid, version_id, offset` | 0x1ccc90 / 0x1ccd18 | （同类） | 下载 delta（`offset` 支持分段续传） |
| `versioning_clean_version` | `sid, source_path, source_file, lockid, version_id` | 0x1cced0 / 0x1ccf50 | 0x0f7220 / 0x0f7330 | 清理某版本的临时文件 |
| `versioning_commit_upload` | `sid, settime=1, mtime, source_path, source_file, lockid, version_id` | 0x1cba10 / 0x1cbaa8 | 0x0f6598 / 0x0f66d0 | **提交新版本（成功即版本生效）** |
| `versioning_upload_file` | `sid, dest_path, overwrite=%d, version_id, versioning_version=1, source_file, offset, upload_name, filesize` | 0x1cd7d8 / 0x1cd898 | 仅 QFileSync | **分片上传数据（offset/filesize/upload_name 支持断点续传）** |
| `versioning_probe` | `sid` | — | 0x0f5558 / 0x0f55e8 | 探测服务端是否支持版本化（能力位） |
| `versioning_stat`（带路径） | `source_path, source_file, sid` | — | 0x0ed848 | 单文件版本化状态 |
| `versioning_stat`（不带） | `sid` | — | 0x0f7b78 | 版本化总状态 |
| `versioning_gen_file` | `sid` | — | 0x0f1b30 | 生成"版本化文件"（按需/流式） |
| `versioning_get_progress` | `sid` | — | 0x0f17f0 | 取生成进度 |
| `versioning_delete_all` | `sid` | — | 0x0f7938 | 清空版本化数据 |

参数语义（由模板 + 字符串键名交叉确认）：
`source_path` = 共享文件夹内目录（相对路径）、`source_file` = 文件名、`lockid` = 版本锁 ID（`versioning_lock&create_version=1` 返回）、
`version_id` = 版本 ID（同一次 lock 返回）、`offset` = 续传偏移、`filesize` = 本次上传的分片大小、
`upload_name` = 上传临时名、`dest_path` = 目标目录、`overwrite` = 是否覆盖、`mtime` = 提交时设置的文件时间。

**返回/JSON 键名证据**（`QFileSync.dll`）：`0x1d3a40 "lockid"`、`0x1d3a48 "version_id"`、
`0x1d3418 "versioning_version"`、`0x1d3998 "versioning_support"`、`0x1cd7c0 "delta"`、`0x1be7f8 "source_total"`、
`0x1bfc1c "file_total"`、`0x1b9f4c "&get_versioning=1"`；
`QsyncAPI.dll`：`0x0e8d34 "versioning_version"`、`0x0e8d20 "versioning_enable"`、`0x0e8d08 "qbox_versioning_enable"`、
`0x0f86f8 "versioning_support"`、`0x0e9314 "lockid"`、`0x0e87d0 "version_id"`、`0x0e8bf0 "[WFM] CGetMoveStatusJson::Parser version_id is null (%s)"`。
JSON 解析类：`QFileSync.dll@0x1ec918 ".?AVCGenVersioningSigJson@@"`、`@0x1ec8b8 ".?AVCStatDeltaJson@@"`、`@0x1ecxxx "CGetVersioningLockResultJson"`（字符串 `str_QFileSync.dll.txt` 第 584/622/3192 行，配合日志 `CGenVersioningSigJson::Parser status(%d)`、`CGetVersioningLockResultJson::Parser status(%d)`）。

---

## 12. QFileSync.dll 导出 → CGI 映射

`QFileVersioning*` / `QFile*Delta*` / `QFile*Signature*` 这些导出本身只是 **C 语言的 vtable 转发壳**，
真正的实现在 `.text` 后半段的内部 `CQWebManConnection` 方法里（导出地址都 < 0x10040，实现都在 0xe7xxx 以上）。

### 12.1 转发壳（参数校验 + `call [vtable+N]`）

| 导出 | RVA | 行为 | 证据 |
|---|---|---|---|
| `QFileVersioningLock` | 0xf1d0 | `(conn, pathW, ?, lockid, out)` → `call [vtable+0x120]`；任一必需参数为空返回 `0x57`(87=ERROR_INVALID_PARAMETER) | `@0x0000f210 call dword ptr [eax+0x120]` |
| `QFileVersioningUnLock` | 0xf230 | → `[vtable+0x124]` | 同构 |
| `QFileGenFileSignature` | 0xf290 | → `[vtable+0x128]` | `@0x0000f2d0 call [eax+0x128]` |
| `QFileGetFileSignature` | 0xf2f0 | → `[vtable+0x12c]` | 同构 |
| `QFileGenFileDelta` | 0xf3f0 | → `[vtable+0x124]`? / 相邻槽 | 同构（0x51 字节） |
| `QFileGetFileDelta` | 0xf450 | → 相邻槽 | 同构 |
| `QFileStatFileDelta` | 0xf700 | `(conn, source_pathW, source_fileW, version_idW, outStruct(0x2018B), out2)` → `call [vtable+0x130]` | `@0x0000f748 call dword ptr [eax+0x130]` |
| `QFileVersioningCleanVersion` | 0xf6a0 | → 相邻槽 | 同构 |
| `QFileCopyDeltaSignatureToPath` | 0xe280 | 取 `[arg2]->vtable[0xc]` 得到连接对象，比较两个对象是否同一连接（同连接返回 `0x32`=ERROR_NOT_SUPPORTED，见日志 `QFileCopyDeltaSignatureToPath(pSrcConnection==pDestConnection)(ERROR_NOT_SUPPORTED)`），最后用 16 个栈参数调用虚函数 | `@0x0000e294 call [eax+0xc]`、`@0x0000e2fb call [eax+0x20]`、`@0x0000e30a call [eax+0x3c]`、`@0x0000e399…` 连续 16 个 `push` |

### 12.2 实现函数（按 URL 模板的代码引用点定位）

| CGI | 实现函数起始 RVA（`QFileSync.dll`） |
|---|---|
| `versioning_lock&check_version=1` | 0x000e75f2 |
| `versioning_lock&create_version=1` | 0x000e779f |
| `versioning_unlock` | 0x000e8bd4 |
| `versioning_gen_sig` | 0x000ea051 |
| `versioning_get_sig` | 0x000eb9c1 |
| `versioning_stat_delta` | 0x000ee4b6 |
| `versioning_commit_upload` | 0x000ecfc1 |
| `versioning_gen_delta` | 0x000efcfb |
| `versioning_get_delta` | 0x000f165c / 0x000f1a77（两处引用） |
| `versioning_clean_version` | 0x000f34e1 |
| `versioning_upload_file` | 0x000f4ca4 |

### 12.3 方法名（日志字符串，直接给出与 WFM 导出的对应关系）

`QFileSync.dll` 内部方法与其调用的 QsyncAPI 语义体（同源编译，函数名相同）：

| 日志字符串（含证据所在字符串文件行号） | 语义 |
|---|---|
| `CQWebManConnection::VersioningLock() WFMQsyncVersioningLock failure(...)` | lock |
| `CQWebManConnection::VersioningLock() WFMQsyncVersioningUnLock failure(...)` | unlock |
| `CQWebManConnection::GenFileSignature() WFMQsyncGenVersioningSig failure(FilePath=%s)(%d)(%d)` | gen_sig |
| `CQWebManConnection::GetFileSignature() WFMQsyncGetVersioningSigToHandle failure(FilePath=%s)(%d)(%d)` | get_sig |
| `CQWebManConnection::GenFileDelta() WFMQsyncGenVersioningDelta dwParseResult(%d) retry)` | gen_delta |
| `CQWebManConnection::GetFileDelta() WFMQsyncGetVersioningDeltaToHandle failure(FilePath=%s)(%d)(%d)` | get_delta |
| `CQWebManConnection::VersioningCommitVersion() WFMQsyncVersioningCommitUpload failure(...)` | commit_upload |
| `CQWebManConnection::VersioningCleanVersion() WFMQsyncVersioningCleanVersion failure(...)` | clean_version |
| `CQWebManConnection::DeltaSyncCopyMoveFrom() WFMQsyncVersioningUploadFilewithHandle failure(strDestPathName=%s)(%d)(%d)` | upload_file |
| `CQWebManConnection::GenFileSignature() GetProgress Failed(dwStatus=%d dwShareErrorCode=%d)` / `VersioningCommitVersion() GetProgress Failed(...)` | 通过 `WFMGetProgress`/`versioning_get_progress` 轮询 |

---

## 13. QsyncAPI.dll 导出 → CGI / 结构体映射

`QsyncAPI.dll` 的导出是 MSVC C++ 修饰名（`?WFMQsyncGenVersioningDelta@@YAKPAXPB_WK1111PA_NPAKPAU_WFM_VERSIONING_PVID@@@Z` 等）。
注意：`QsyncAPI.dll` 只被 `Qsync.exe`(9 个函数) 和 `Qfile.dll`(54 个函数) 导入，
**同步引擎（`QsyncLib.dll`/`QsyncSync.dll`）不导入它** —— 同步引擎走的是 `QFileSync.dll` 内自带的同源 `CQWebManConnection` 实现。
因此"这些调用对应 QsyncAPI 的哪些导出"的答案是**同名同源的一份实现**，映射表如下（按修饰名解析 + 内部日志字符串 + URL 模板三方对齐）：

| QsyncAPI 导出（修饰名已解析） | 参数（源级） | CGI | 证据 |
|---|---|---|---|
| `WFMQsyncVersioningLock` | `(void* conn, const wchar_t* path, int, int, BOOL*, DWORD*, _WFM_VERSIONING_LOCK*)` | `versioning_lock&check_version=1` + `&create_version=1` | 函数体 0x5b820 内含 `[WFM] WFMQsyncVersioningLock …` 全部日志；URL 模板 `QsyncAPI.dll@0x0f5840/0x0f5960/0x0f5a90/0x0f5b80` |
| `WFMQsyncVersioningUnLock` | `(…, DWORD*)` | `versioning_unlock` | 0x5d530；模板 `@0x0f5e28/0x0f5f10`；日志 `[WFM] WFMQsyncVersioningUnLock: get error status = %d` |
| `WFMQsyncGenVersioningSig` | `(…, _WFM_VERSIONING_PVID*)` | `versioning_gen_sig` | 0x53890；模板 `@0x0f61c0/0x0f62c8`；日志 `@0x0f640c IsSuccess failed`、`@0x0f63d8 WFM_PARSE_XML_FAIL` |
| `WFMQsyncGenVersioningDelta` | `(…, _WFM_VERSIONING_PVID*)` | `versioning_gen_delta` | 0x529d0；模板 `@0x0f6df8/0x0f6f00`；日志 `@0x0f705c empty PID`、`@0x0f7088 IsSuccess failed` |
| `WFMQsyncVersioningStatDelta` | `(…, _WFM_VERSIONING_DELTA_INFO*)` | `versioning_stat_delta` | 0x5c770；模板 `@0x0f6a28/0x0f6b20`；日志 `@0x0f6c58 IsSuccess failed` |
| `WFMQsyncVersioningCommitUpload` | `(…, __int64 mtime, BOOL, DWORD*, _WFM_VERSIONING_PVID*)` | `versioning_commit_upload` | 0x5a920；模板 `@0x0f6598/0x0f66d0`；日志 `@0x0f6850 empty PID` |
| `WFMQsyncVersioningCleanVersion` | `(…, DWORD*)` | `versioning_clean_version` | 0x59b30；模板 `@0x0f7220/0x0f7330`；日志 `@0x0f7488 status failed(%d)` |
| `WFMDeleteAllVersioning` | `(…, BOOL*, BOOL*, DWORD*)` | `versioning_delete_all` | 0x38360；模板 `@0x0f7938`；日志 `@0x0f7a04 failed(%d)` |
| `WFMQsyncGetVersioningProbe` | `(…, DWORD*, _WFM_VERSIONING_PROBE*)` | `versioning_probe` | 0x55ce0；模板 `@0x0f5558`（qsyncsrv）/`@0x0f55e8`（utilRequest）；日志 `[WFM] WFMQsyncGetVersioningProbe: empty version`（探测返回里必须有 version 字段） |
| `WFMGetFileVersionList` | `(…, BOOL*, BOOL*, DWORD*, DWORD*, _WFM_FILE_VERSION***)` | （版本列表，`&version_id=%ls&show_deleted=1` @0x0ed848 附近/line 280） | 0x3f690；日志 `[WFM] WFMGetFileVersionList: No versioining(%s)(%s)` |
| `WFMQsyncGetSyncLog` | `(…, int, __int64, wchar_t*, BOOL*, DWORD*, _WFM_SYNC_LOG_INFORMATION***, DWORD*, DWORD*)` | `qbox_get_sync_log&lower=%ls&number=%d&syncing_folder=%ls&get_detail=1&sub_folder=%ls` | 0x7ce60；日志 `[WFMShare] WFMQsyncGetSyncLog: got log number > output buffer number` |
| `WFMQsyncGetMaxLog` | `(…, _WFM_QSYNC_MAX_LOG_INFO*, DWORD*)` | `qbox_get_max_log`（含 `folder=%ls` 变体、`qsyncsrv.fcgi`/`qsyncsrvPrepare.cgi` 变体） | 0x7b9f0 |
| `WFMQsyncQboxGetMaxLog` | `(…, _WFM_QSYNC_QBOX_MAX_LOG_INFO*, DWORD*)` | `qbox_get_max_log` | 0x7db60 |
| `WFMGetUseQboxCGI` | `(…, BOOL*)` | 选择新旧 CGI 命名空间（`use qbox cgi`） | 0x47070 内含 `[WFM] WFMGetUseQboxCGI: WFM_PARSE_XML_INVALID_PARAMETER` |
| `WFMGetProgress` | `(…, int, int, DWORD*, DWORD*)` | 进度轮询 | 0x…；`QsyncAPI.dll` 字符串 `?WFMGetProgress@@YAKPAXPB_WK11HPA_NPAK@Z`（行 2733） |

**结构体字段（按解析点偏移推断，置信度中）**：
* `_WFM_VERSIONING_PVID`：至少含 `pid`（`GenVersioningDelta/CommitUpload` 的日志都检查 `empty PID`）与 `version_id`/`lockid`。
* `versioning_stat_delta` 的输出结构（`QFileSync` 调用点 `0x0000becc` 起传入，大小 **0x2018** 字节，先 `memset(…,0x2018)`）：
  * `+0` : 有效/状态标志（`QFileSync` 侧 `cmp dword ptr [ebp-0x2014],0` 判断）
  * `+8` : 64 位量（低 32 位在 `+8`，高 32 位在 `+0xc`；`QFileSync` 侧与另一个 64 位局部量比较）
  * 其余字段未逐一确认。
* 日志里出现的键：`lockid`、`version_id`、`versioning_version`、`versioning_support`、`status`、`pid`、`offset`、`filesize`、`source_total`、`file_total`。

---

## 14. 完整时序（本地改文件 → 上传 / 下载）

同步引擎的入口是 `QsyncSync.dll` 的 `copy_file_delta_sync`（日志 `QsyncSync.dll: "copy_file_delta_sync (Status=%d, SrcFile=%s, DestFile=%s)"`，字符串行 2186），
它调用 `copy_delta_file`（`QsyncSync.dll@0x0000bc00`，函数体 0xbc00–0xcf79，唯一调用点 `@0x0001047b`）。
`copy_delta_file` 内部按方向分成两支，两支都以 `QFileStatFileDelta` 探测开头，以 `QFileVersioningUnLock` 收尾：

```
                     ┌─ QFileStatFileDelta  (func=versioning_stat_delta
                     │    &source_path&source_file&version_id)
   copy_delta_file ──┤         │ 返回 delta 信息 / 失败
   (0xbc00)          │         ├─ 不可用 ─► 清空结构 → 走整文件传输（无 delta）
                     │         └─ 可用 ─┐
                     │                 │
                     ├── 分支 A（NAS → 本地，下载）──────────────────────────────
                     │   QFileVersioningLock            [0x0000bf9c]  versioning_lock&create_version=1
                     │   QRdiffSign(local_basis)        [0x0000c4ea]  rdiff_sign(块=1MiB, 强=16)
                     │   QFileCopyDeltaSignatureToPath  [0x0000c604]  上传 signature（versioning_upload_file）
                     │   QFileGenFileDelta              [0x0000c676]  versioning_gen_delta
                     │   QFileGetFileDelta              [0x0000c767]  versioning_get_delta(&offset=…)
                     │   QRdiffPatch(…)                 [0x0000c7d0]  rdiff_patch → 生成新文件
                     │   QBackOpenFile3 / QBackSetFileTime / QBackDeleteFileByPath / QBackMoveFileToPath
                     │                                 [0xc84b / 0xc88e / 0xc8bb / 0xc8ec] 落盘 + 设置时间
                     │
                     ├── 分支 B（本地 → NAS，上传）──────────────────────────────
                     │   QFileVersioningLock            [0x0000bf9c / 0x0000c30d]
                     │   QFileGenFileSignature          [0x0000cb32]  versioning_gen_sig
                     │   QFileGetFileSignature          [0x0000cbbb]  versioning_get_sig（下载服务端旧版本签名）
                     │   QRdiffDelta(sig, local_new, delta)  [0x0000cc4b]
                     │        push [ebp-0x1004] (delta 输出)
                     │        push [esi+0xa08c] (本地新文件)
                     │        push [ebp-0x2004] (刚下载的签名)
                     │   QFileCopyDeltaSignatureToPath  [0x0000cdd8]  上传 delta
                     │   …（服务端侧 commit；见 copy_delta_file 尾部与 QsyncSync 调用方）
                     │
                     └─ QFileVersioningUnLock           [0x0000ceff]  versioning_unlock
```

对应的 HTTP 时序（以"本地改文件 → 上传"为例）：

```
Client                                             NAS (qsyncsrv.cgi / utilRequest.cgi)
  │  GET func=versioning_lock&create_version=1&sid&source_path&source_file
  │────────────────────────────────────────────────────────►│
  │◄──────────── {lockid, version_id} ─────────────────────│
  │  GET func=versioning_gen_sig&sid&source_path&source_file&lockid&version_id   ← 服务端为旧版本造签名
  │────────────────────────────────────────────────────────►│
  │  GET func=versioning_get_sig&…&lockid&version_id
  │────────────────────────────────────────────────────────►│  （下载签名文件到本地临时文件）
  │◄──────────── signature bytes ──────────────────────────│
  │  [本地] rdiff_delta(sig, 新文件, delta)                 │
  │  POST func=versioning_upload_file&sid&dest_path&overwrite&version_id
  │        &versioning_version=1&source_file&offset&upload_name&filesize
  │────────────────────────────────────────────────────────►│  （分片上传 delta / 或整文件分片）
  │  GET func=versioning_commit_upload&sid&settime=1&mtime
  │        &source_path&source_file&lockid&version_id
  │────────────────────────────────────────────────────────►│  （提交，新版本生效）
  │  GET func=versioning_unlock&sid&source_path&source_file&lockid
  │────────────────────────────────────────────────────────►│
  │  （出错时 GET func=versioning_clean_version&…&lockid&version_id 清理）
```

"本地改文件 → 服务端生成签名 → 本地算 delta → 上传 delta → 提交新版本" 这条链在反汇编里逐项可见：
`QFileGenFileSignature`→`QFileGetFileSignature`→`QRdiffDelta`→`QFileCopyDeltaSignatureToPath`→（提交）`QFileVersioningUnLock`（分支 B，`QsyncSync.dll@0xcb32 / 0xcbbb / 0xcc4b / 0xcdd8 / 0xceff`）。
反向（服务端有新版本，本地要更新）：`QFileVersioningLock`→`QRdiffSign`→上传签名→`QFileGenFileDelta`→`QFileGetFileDelta`→`QRdiffPatch`（分支 A，`QsyncSync.dll@0xbf9c / 0xc4ea / 0xc604 / 0xc676 / 0xc767 / 0xc7d0`）。

其它导出与 versioning 的关系：
* `QFileVersioningCleanVersion` ← `QsyncSync.dll` 的 `clean_versioning_files`（日志 `clean_versioning_files(src=%s)(version_id=%s)`、`clean_versioning_files QFileVersioningCleanVersion Failed (version_id=%s)(dwStatus=%d)`）。
* `WFMGetFileVersionList` / `WFMDeleteAllVersioning` / `WFMQsyncGetVersioningProbe` 只在 `QsyncAPI.dll`（Qfile 客户端）内，用于"版本列表/清理/能力探测"UI 路径。

---

## 15. 何时走 delta、何时走整文件上传

### 15.1 同步引擎入口的标志位判定（`copy_file_delta_sync`）

`QsyncSync.dll@0x000103ce` 起：

```
0x103ce  mov ecx,[ebp-0x24bc4]        ; 64 位量 A(高/低)
0x103d4  mov ebx,[ebp-0x24b98]
0x103da  mov edi,[ebp-0x24b9c]
0x103eb  test edi,edi ; jne 0x10010c5f           ; A 的有符号条件不满足 → 不走 delta
0x103f3  mov eax,[esi+0x211e8]
0x103f9  test eax,eax ; je 0x10010c5f            ; 服务端/远端尺寸为 0 → 不走 delta
0x10401  cmp [ebp-0x6218],edi ; jl 0x10010c5f
0x1040d  jg 0x1001041b
0x1040f  cmp [ebp-0x621c],eax ; jb 0x10010c5f
0x1041b  mov eax,[esi+0x1e090]
0x10421  and eax,0x10000000                      ; ★ 同步选项/能力标志位
0x10429  je 0x100104d3                           ; 未置位 → 直接去整文件路径
0x1042f  test ecx,ecx ; je 0x100104d3
0x10437/0x10455  两个宽字符串缓冲必须为空（宽字符串长度 == 0），否则 0x100104d3
0x10471  push 0; push &[ebp-0xc25c]; push esi
0x1047b  call 0x1000bc00                          ; copy_delta_file（delta 路径）
```
→ delta 分支的前置条件 =「尺寸比较通过」+「`[conn/ctx+0x1e090]` 的第 31 位置 1」+「两个路径串为空」；否则跳 `0x100104d3`（整文件传输路径）。

### 15.2 delta 可用性判定（`copy_delta_file` 内的 `versioning_stat_delta` 结果）

`QsyncSync.dll@0x0000bee8` 调用 `QFileStatFileDelta`（出参结构在 `[ebp-0x2014]`，大小 0x2018），随后：

```
0x0bef7  test eax,eax ; jne 0x1000bf2f          ; RPC 失败 → 无 delta
0x0befb  cmp dword ptr [ebp-0x2014],eax(0)
0x0bf01  je 0x1000bf2f                          ; +0 标志为 0 → 无 delta
0x0bf03  mov ecx,[ebp-0x2840]                   ; 本地 64 位量（hi）
0x0bf09  cmp [ebp-0x2008],ecx                   ; 结构 +0xc（hi）
0x0bf0f  jl 0x1000bf2f
0x0bf11  mov eax,[ebp-0x2844]                   ; 本地 64 位量（lo）
0x0bf17  jg 0x1000bf21                          ; 严格大于 → 用 delta
0x0bf19  cmp [ebp-0x200c],eax                   ; 结构 +8（lo）
0x0bf1f  jbe 0x1000bf2f                         ; ≤ → 无 delta
0x0bf21  mov [ebp-0xeafc],eax ; mov [ebp-0xeaf8],ecx   ; 记录采用
0x0bf2f  （无 delta 清理路径：memset(…,0x2018) 后继续）
```
即：**只有 `versioning_stat_delta` 返回的有效标志非 0，并且返回结构 `+8/+0xc` 处的 64 位量对本地 64 位量满足"严格大于"时**才继续 delta 流程。
两个 64 位量的具体语义（"delta 大小 vs 本地文件大小" 还是别的组合）需要 `_WFM_VERSIONING_DELTA_INFO` 的字段定义才能定论 ⇒ **置信度中**；但"失败/不满足即退回整文件"这一结构是明确的。

### 15.3 其它阈值

* `MaxFileSize`：`QsyncLib.dll` 中存在配置/SQL 键字符串 `MaxFileSize`（`str_QsyncLib.dll.txt` 行 17593，紧邻 `MaxFileListCount`(17592)、`MultiPartFileSize`(17639)）以及导出成员
  `?GetMaxFileSize@CQsyncSyncDll@@QAE_JXZ`（= `__int64 CQsyncSyncDll::GetMaxFileSize(void)`，同时出现在 `Qsync.exe` 字符串行 22165）。
  **它决定的是"分片/多部分上传"的大小上限**（与 `MultiPartFileSize`、`versioning_upload_file` 的 `offset/filesize` 分片配合），
  而不是 delta 的开关；本次未定位到读取该键的具体代码（字符串不是通过 `push imm32` 引用的）⇒ 该点**未完全确认**。
* 整文件/分片上传路径：`QsyncSync.dll` 有 `IgnoreMultipartUpload` 字段（SQL 建表串 `str_QsyncLib.dll.txt` 行 15269）、
  `QFileResumeCopyandMoveFileToPath(DestPath=%s)(offset=%lld)`（`str_QFileSync.dll.txt` 行 5036）等，说明超过阈值走分片断点续传。

---

## 16. qbox 日志（`qbox_write_log` / `qbox_get_sync_log` / `qbox_get_max_log`）

**URL（`QsyncLib.dll`，唯一使用 `qbox_write_log` 的模块）**：

| 功能 | RVA | 模板 |
|---|---|---|
| 写日志 | 0x5d2fe0 | `%s%s:%d/cgi-bin/qsync/qsyncsrv.cgi?func=qbox_write_log&sid=%s&filepath=%s&action=%d` |
| 读同步日志 | 0x5ceff8 | `%s%s:%d/%scgi-bin/qsync/qsyncsrv.cgi?func=qbox_get_sync_log&sid=%s&lower=%s&number=%d&syncing_folder=%s&get_detail=1&sub_folder=%s` |
| 读同步日志（旧式） | 0x5cf080 | `%s%s:%d/cgi-bin/filemanager/utilRequest.cgi?func=qbox_get_sync_log&sid=%s&lower=%s&number=%d&syncing_folder=%s&sub_folder=%s` |
| 读同步日志（不带文件夹） | 0x5cf100 / 0x5cf170 | `…&get_detail=1&sub_folder=%s` / `…&lower=%s&number=%d&sub_folder=%s` |
| 日志水位 | 0x5ce010 / 0x5ce208 / 0x5ce060 / 0x5ce0b0 / 0x5ce0f8 / 0x5ce258 | `func=qbox_get_max_log&sid=%s`（`folder=%s` 变体；还有 `qsyncsrv.fcgi`、`qsyncsrvPrepare.cgi`、`qsyncPrepare.cgi`、`utilRequest.cgi` 多种前缀） |

**调用点（代码引用该模板的函数）**：`QsyncLib.dll` — `qbox_write_log` 模板被 `@0x003027ad` 引用（函数起始 `0x003022a0`）；
`qbox_get_sync_log` 模板被 `@0x002ebc63/@0x002ebcf8`（函数 `0x002ebc4a`）与 `@0x002eb9ad/@0x002eb9a8`（函数 `0x002eb8c7`）引用。
`QsyncAPI.dll` 侧对应 `WFMQsyncGetSyncLog`(0x7ce60)、`WFMQsyncGetMaxLog`(0x7b9f0)、`WFMQsyncQboxGetMaxLog`(0x7db60)。

**语义（由参数名可确定的部分）**：
* `lower` = 水位/游标（下一次拉取从哪个序号开始）、`number` = 本次拉取条数、`syncing_folder`/`sub_folder` = 过滤目录、`get_detail=1` = 只要明细
  （`QsyncAPI.dll@0x0f1xxx` 的 `qbox_get_sync_log` 变体与日志 `[WFMShare] WFMQsyncGetSyncLog: got log number > output buffer number` 印证"按条数拉、比对条数"）；
* `qbox_get_max_log` 返回"日志最大序号"（`_WFM_QSYNC_MAX_LOG_INFO` / `_WFM_QSYNC_QBOX_MAX_LOG_INFO`），与服务端 `qsyncsrv.fcgi`/`qsyncsrvPrepare.cgi` 多端点并存，用于取得水位上界；
* `_WFM_SYNC_LOG_INFORMATION` 的结构体字段本次未逐字段解析（`WFMQsyncGetSyncLog` 的缓冲数校验日志 `got log number > output buffer number` 说明它是"数组 + 条数"形式）。
* `QsyncLib.dll` 另有 `CQsyncSession::UpdateMaxFileListCount (m_unMaxFileListCount=%d)`（`str_QsyncLib.dll.txt` 行 13671/13672）
  与本地 SQLite 日志表（`QsyncSyncFileLogTable`、`QsyncErrorFileTable` 等建表串，行 14637/17464），说明客户端把"服务端日志发现 + 本地文件日志表"合起来做增量发现与状态对账。

**与 versioning 的关系（置信度中）**：服务端同步日志是"别的客户端/手机改了什么"的发现通道；`QsyncLib.dll` 拉日志 →
对发现的文件调用比较/同步（`QBackCompareTwoFileEqual`、`CheckConnectSpeed` 等）→ 需要传输时进入 §14 的 `copy_delta_file`（其中 `versioning_stat_delta` 决定是否用 delta）。
本报告没有在反汇编层面把"日志条目 → copy_delta_file"这条调用链完整连起来（`QsyncLib.dll` 体量 6.8 MB，调用链跨 `CQsyncSession`/`CCloudFileMan`），因此这一步的**直接证据缺失**，仅能给出组件与参数级证据。

---

## 17. 置信度与未确认项

| 项目 | 状态 |
|---|---|
| RdiffDll 29 导出签名/语义 | 除 `rdiff_comp`（含空指针写，判定为坏/死代码）与 `rdiff_modify`（只到"按 1.5 MiB 步长回填"）外，**高** |
| signature / delta 二进制格式 | **高**（生成端 + 解析端双向印证；命令码表来自 `0x24db0`） |
| 块大小 1 MiB / 强校验和 16 / CHAR_OFFSET 31 / MD4 | **高** |
| versioning CGI 端点与参数 | **高**（两个模块各一套模板，逐字） |
| `QFileSync` 导出 → CGI 映射 | 转发壳与 vtable 槽位**高**；"实现函数起始地址 ↔ CGI"用 URL 引用点定位，**中高**（函数名未从符号表确认） |
| `QsyncAPI` 导出 → CGI | **高**（修饰名 + 函数体内日志 + URL 模板三方一致） |
| `_WFM_VERSIONING_DELTA_INFO` / `_WFM_VERSIONING_LOCK` / `_WFM_VERSIONING_PROBE` / `_WFM_SYNC_LOG_INFORMATION` 字段级布局 | 只知道 `stat_delta` 结构大小 0x2018、`+0` 标志、`+8/+0xc` 64 位量；其余**未确认** |
| delta vs 整文件上传的判定表达式 | 分支结构与常量（含 `0x10000000` 标志位）**高**；两个 64 位量的语义名**中** |
| `MaxFileSize` 的读取代码与默认值 | 只确认键名与 getter 存在；**未确认**具体默认值与读取点 |
| 服务端日志 → delta 调用的完整调用链 | **未确认**（仅有端点、参数、模块归属与相邻日志） |
| 服务端（NAS 端 CGI）实现 | 不在本安装包内，未分析 |

---

## 18. 证据索引（常用 RVA 速查）

**RdiffDll.dll**

```
0x00001df0  内部文件拷贝例程（1 MiB 缓冲）
0x000024d98 16 进制查表 "0123456789abcdef"
0x000024db0 delta 命令分发表（16B/项）
0x000025dd8 "mismatch between rolled sum %#x and check %#x"
0x000025e1c "calculate weak sum from scratch length %d"
0x000025f78 "emit DELTA magic"      0x000025f94 "emit LITERAL_N%d…"
0x000026018 "emit COPY_N%d_N%d…"    0x000026050 "emit END, cmd_byte=%#x"
0x000026174 "sent header (magic %#x, block len = %d, strong sum len = %d)"
0x00002648c "got magic number %#x rather than expected value %#x"
0x0000264fc "strong sum length %d is implausible"
0x000026520 "allocated sigset_t (strong_sum_len=%d, block_len=%d)"
0x000026558 "block length of %d is bogus"
0x000026574 "wrong magic number %#10x for signature"
0x0000267dc "found weak match for %08x in token %d"
0x000026804 "this was a false positive, the strong sig doesn't match"
0x0000268c8 "librsync"
0x0001280 run rs_delta 扫描      0x00013xx 滚动公式
0x00015c0 弱匹配 + MD4 比较      0x0001a40 emit DELTA magic
0x0001ae0 emit LITERAL           0x0001bf0 emit COPY       0x0001560 emit END
0x0002b10 signature 头           0x0002d80 逐块发签名
0x0002e60 rs_strerror            0x0002ebc/0x0002eec 跳转表/索引表
0x0002f60 大端整数发射器
0x0003090 patch 命令解码（PATCH_CMD 0x30a0 / 0x31b0 / RUN_CMD 0x3210）
0x0003610 patch magic 校验
0x0005070 signature 块读取       0x00051c0 strong_sum_len 校验
0x0005290 block_len 校验         0x0005320 signature magic 校验
0x00053e0 从零计算弱校验和
0x00037e0 rdiff_sign  0x0003940 rdiff_delta  0x0003b60 rdiff_patch
0x0003da0 rdiff_comp  0x0004110 rdiff_compsign  0x0004550 rdiff_firstsign
0x00046f0 rdiff_getnumberofchunk  0x00047c0 rdiff_compare  0x00048f0 rdiff_mdfour
0x0004950 rdiff_split 0x0004b30 rdiff_combine 0x0004d00 rdiff_modify
0x0004e60 rdiff_get_block 0x0004f60 rdiff_fget_block
0x0004fc0/0x0004fe0 chunk_list 0x0005010 num_to_hex 0x0005030/0x0005040 copy/move_file
全局: 0x100288b0 input / 0x100288b4 output / 0x100288f8 block(=0x100000) / 0x100288fc sum(=0x10)
     0x10026a70 MD4 IV
```

**QsyncSync.dll**

```
0x00007680 QRdiffDelta(wrapper)   0x00007760 QRdiffPatch  0x00007840 QRdiffSign
0x0000bc00 copy_delta_file        0x0000bf9c VersioningLock（分支 A）
0x0000c4d5/0xc4ea push 0x10 / 0x100000 + QRdiffSign
0x0000c604 QFileCopyDeltaSignatureToPath(上传签名)
0x0000c676 QFileGenFileDelta      0x0000c767 QFileGetFileDelta  0x0000c7d0 QRdiffPatch
0x0000cb32 QFileGenFileSignature  0x0000cbbb QFileGetFileSignature
0x0000cc4b QRdiffDelta（sig=[ebp-0x2004], new=[esi+0xa08c], delta=[ebp-0x1004]）
0x0000cdd8 QFileCopyDeltaSignatureToPath(上传 delta)  0x0000ceff QFileVersioningUnLock
0x0000bee8 QFileStatFileDelta 调用点；0x0000bef7-0x0000bf2d delta 可用性判定
0x000103ce-0x0001047b copy_file_delta_sync 的 delta 门槛（0x10000000 标志位 @0x10421）
```

**QFileSync.dll**

```
versioning URL 模板: 0x1ca590 lock(check) / 0x1ca6a8 lock(create) / 0x1cac10 unlock
                    0x1cb190 gen_sig / 0x1cb738 get_sig / 0x1cc0a8 stat_delta
                    0x1cc668 gen_delta / 0x1ccc90 get_delta / 0x1cba10 commit_upload
                    0x1cced0 clean_version / 0x1cd7d8 upload_file
实现函数: 0xe75f2 / 0xe779f / 0xe8bd4 / 0xea051 / 0xeb9c1 / 0xee4b6 / 0xefcfb / 0xf165c / 0xf34e1 / 0xf4ca4
导出: 0xe280 CopyDeltaSignatureToPath / 0xf1d0 VersioningLock / 0xf230 UnLock /
      0xf290 GenFileSignature / 0xf2f0 GetFileSignature / 0xf3f0 GenFileDelta /
      0xf450 GetFileDelta / 0xf6a0 VersioningCleanVersion / 0xf700 StatFileDelta
键: 0x1d3a40 lockid / 0x1d3a48 version_id / 0x1d3418 versioning_version / 0x1cd7c0 delta
```

**QsyncAPI.dll / QsyncLib.dll**

```
QsyncAPI: 0x0f5840/0x0f5a90 lock / 0x0f5e28 unlock / 0x0f61c0 gen_sig / 0x0f6598 commit_upload
          0x0f6a28 stat_delta / 0x0f6df8 gen_delta / 0x0f7220 clean_version / 0x0f7938 delete_all
          0x0f5558 versioning_probe / 0x0ed848 versioning_stat&source_path / 0x0f7b78 versioning_stat
          0x0f1b30 versioning_gen_file / 0x0f17f0 versioning_get_progress
导出函数体: 0x5b820 Lock / 0x5d530 UnLock / 0x53890 GenSig / 0x529d0 GenDelta / 0x5c770 StatDelta
          0x5a920 CommitUpload / 0x59b30 CleanVersion / 0x38360 DeleteAllVersioning / 0x55ce0 GetVersioningProbe
          0x7ce60 GetSyncLog / 0x7b9f0 GetMaxLog / 0x7db60 QboxGetMaxLog / 0x47070 GetUseQboxCGI
QsyncLib: 0x5d2fe0 qbox_write_log / 0x5ceff8 & 0x5cf080 qbox_get_sync_log / 0x5ce010.. qbox_get_max_log
          0x3022a0 引用 qbox_write_log 的函数；0x2eb8c7 & 0x2ebc4a 引用 qbox_get_sync_log 的函数
```
