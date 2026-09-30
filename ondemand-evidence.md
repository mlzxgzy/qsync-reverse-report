# QNAP Qsync for Windows —— on-demand（云端按需文件 / 占位符）机制逆向分析

- 分析目标：Qsync 6.1.0.0831 for Windows（x86 主体 + x64 Shell 扩展），安装目录 `$WD = /home/aaaa/.wine/drive_c/Program Files (x86)/QNAP/Qsync`
- 证据格式：`模块@地址`。地址一律是**虚拟地址（VA）**，各模块 ImageBase = `0x10000000`（QsyncCloudFile/QsyncLib/QFileSync 均为 x86，基址 0x10000000），故 `RVA = VA - 0x10000000`。文件偏移与 RVA 不同（例如 QsyncCloudFile.dll 的 `.rdata` 文件偏移 = RVA − 0x1600）。
- 反汇编工具：`qsync-analysis/.venv`（pefile + capstone），脚本见文末“工具”一节。
- 外部引用（枚举/结构定义）以 MS Learn 官方文档为准，见文末链接。

---

## 0. 结论速览（状态机全景）

```
                      ┌─────────────────────────── Qsync.exe (x86, Qt5 GUI) ─────────────────────────┐
                      │  UI: 空间节省模式 / Free up space / Keep on this device                       │
                      └───────────────┬───────────────────────────────────────────────────────────────┘
                                      │ CQsyncSyncDll (导出 API)
        ┌─────────────────────────────▼──────────────────────────────────────────────┐
        │ QsyncLib.dll (x86)                                                          │
        │  CQsyncDllManager  定时器 TIMER_CHECK_FREE_UP_SPACE / FreeUpSpaceThread      │
        │  CQsyncSession::RegisterSyncRoot/ConnectSyncRoot/ScanCompleteAction/SyncFileWithFlag │
        │  CloudFileMan::RegisterSyncRoot / ConnectSyncRoot / OnFetchData / OnCancelFetchData │
        │  加载 QsyncCloudFile.dll（LoadLibraryW + GetProcAddress 29 个 qc*）           │
        └───────┬───────────────────────────────┬──────────────────────────────────────┘
                │ qc* ABI                       │ QBack* / QFile*  （WFM CGI / QsyncSync）
        ┌───────▼───────────────────────┐       │
        │ QsyncCloudFile.dll (x86)      │       │
        │  唯一直接调用 cldapi.dll 的模块 │       │
        │  CfConnectSyncRoot + FETCH_DATA/CANCEL_FETCH_DATA 回调 │
        │  CfCreatePlaceholders / CfUpdatePlaceholder / CfConvertToPlaceholder │
        │  CfHydrate/Dehydrate/SetPinState/SetInSyncState/CfExecute/CfReportProviderProgress │
        └───────────────────────────────┘
                ▲  Explorer(exe) 触发 FETCH_DATA（打开/读取未水合占位符）
                │
        ┌───────┴───────────────────────┐   \\.\Pipe\QNAPQsyncCache / ...Command / QsyncExtCOMCache
        │ QsyncExt.dll (x64)            │◄──── 命名管道 + 共享内存 ────► 上面的 x86 客户端
        │  Shell 扩展: 图标覆盖 + 缩略图 │
        └───────────────────────────────┘
```

关键结论：

1. **只有 `QsyncCloudFile.dll` 调用 cldapi（Cf*）**，且是**静态导入表**（PE Import Table），不是 GetProcAddress。
2. 占位符层的“业务逻辑”全部在 `QsyncLib.dll`（`CloudFileMan::*`）与 `QFileSync.dll`（`CreateCloudFile`/`QFile*Placeholder*`）；`QsyncCloudFile.dll` 只是一层薄 C ABI 包装。
3. 同步根注册 **不使用 `CfRegisterSyncRoot`**（该函数不在导入表里！），而是走 WinRT `Windows.Storage.Provider.StorageProviderSyncRootManager.Register()`。
4. 水合（hydrate）= Explorer 打开/读取占位符 → cldapi 回调 `FETCH_DATA` → QsyncLib 起线程 → 从 NAS 拉 **≤128 KiB** 的分片 → `CfExecute(TRANSFER_DATA)` 把数据写回占位符。
5. 脱水（dehydrate）= pin state `UNPINNED`(2) + 显式 `CfDehydratePlaceholder`；“空间节省模式”即两者组合；另有自动 Free-up-space 定时器与磁盘占用阈值。

---

## 1. `QsyncCloudFile.dll` 导出 → `Cf*` 调用序列

`QsyncCloudFile.dll` 共 29 个导出（序号 1–29），其中 **`qcInit` 与 `qcUninit` 是同一个地址 `0x1000fef0`，函数体只有 `ret 0`（空实现）**：

```
QsyncCloudFile.dll@0x1000fef0   c2 00 00    ret 0        ; qcInit == qcUninit
```

下表给出“导出 → 内部包装函数 → Cf*/相关 Win32”的完整调用链（`→` 表示调用/tail-call；`0x1000ad80`/`0x1000b510` 等是模块内的匿名子程序）。

| 导出（序号） | 内部包装 | 最终 Cf*/Win32 调用序列 |
|---|---|---|
| `qcInit`/`qcUninit` (13/26) | — | 无（`ret 0`） |
| `qcSupportCloudFiles` (25) | — | `CfGetPlatformInfo` → **比较返回结构首个 DWORD 与 `0x4563`(=17763 → Win10 1809)**，`>=` 才返回 true |
| `qcIsRegisteredSyncRoot` (14) | `0x10002760` | `CfGetSyncRootInfoByPath(path, 1, buf, 0x1428, &len)`，再 `wcscmp(buf+0x1c, L"QNAPQsyncCloudProvider")` |
| `qcIsSyncRootRegistered` (15) | `0x10002760`（jmp） | 同上 |
| `qcRegisterSyncRoot` (16) | `0x100017b0` | `CfGetSyncRootInfoByPath`→（若已注册直接返回 0）；否则：`CreateDirectoryW` → WinRT `StorageFolder`(内部 `0x10001290`) → `StorageProviderSyncRootInfo` 各属性 setter（vtable）→ `StorageProviderSyncRootManager::Register` → `Sleep(1000)` → `RegOpenKeyExW/RegSetValueExW/RegCloseKey`（写 `SyncRootManager\<id>\ThumbnailProvider`）；失败日志 `Could not register the sync root, hr %08x.` |
| `qcUnregisterSyncRoot` (27) | `0x100022c0` | `GetTokenInformation`+`ConvertSidToStringSidW`(算 SID，用于拼 id) → `CfGetSyncRootInfoByPath` → `RegDeleteKeyW` / WinRT `Remove`；日志 `Could not unregister the sync root, hr %08x.` |
| `qcGetSyncRootId` (10) | `0x100024d0` | 无 Cf*；WinRT：`StorageFolder`(`0x10001290`) → `GetSyncRootInformationForFolder()` → `.Id`；失败日志 `GetSyncRootInformationForFolder(%s) failed, hr %08x` |
| `qcConnectSyncRoot` (1) | `0x1000a6a0` | **`CfConnectSyncRoot(path, &回调表, this, 6, &ConnectionKey)`**（详见 §2） |
| `qcDisconnectSyncRoot` (5) | `0x1000a820` | `CfDisconnectSyncRoot(ConnectionKey)`；日志 `Could not disconnect sync root, hr %08x.` |
| `qcCreatePlaceholder` (3) | `0x1000b2a0` | `GetFileAttributesW` → **`CfCreatePlaceholders(path, &info, 1, 0, NULL)`**；日志 `Creating placeholder for %sx.` / `Failed to create placeholder for %s with %08x.` |
| `qcConvertToPlaceholder` (2) | `0x1000b510`→`0x1000b601`→`0x1000b6c9` | `CfOpenFileWithOplock` → **`CfConvertToPlaceholder(handle, FileIdentity, len, flags, ...)`** → `CfCloseHandle` |
| `qcUpdatePlaceholderByPath` (29) | `0x1000b8e0`→`0x1000b9cd`→`0x1000bab0` | `GetFileAttributesW`→`CreateFileW`→`GetFileInformationByHandle`→**`CfUpdatePlaceholder`**→`CloseHandle` |
| `qcUpdatePlaceholder` (28) | `0x1000bab0` | `GetFileInformationByHandle`→**`CfUpdatePlaceholder`** |
| `qcRevertPlaceholderByPath` (19) | `0x1000b710`→`0x1000b7fd` | `GetFileAttributesW`→`CreateFileW`→**`CfRevertPlaceholder`**→`CloseHandle` |
| `qcGetPlaceholderInfo` (8) | `0x1000be60` | **`CfGetPlaceholderInfo`** |
| `qcGetPlaceholderInfoByPath` (9) | `0x1000bc90`→`0x1000bd7d` | `GetFileAttributesW`→`CreateFileW`→**`CfGetPlaceholderInfo`**→`CloseHandle` |
| `qcHydratePlaceholder` (11) | `0x1000c140` | `GetFileInformationByHandle`→**`CfHydratePlaceholder`** |
| `qcHydratePlaceholderByPath` (12) | `0x1000bf70`→`0x1000c061`→`0x1000c140` | `GetFileAttributesW`→`CreateFileW`→`GetFileInformationByHandle`→**`CfHydratePlaceholder`**→`CloseHandle` |
| `qcDehydratePlaceholder` (4) | `0x1000c1e0`→`0x1000c2d1` | 日志 `Dehydrating file %s`；`GetFileAttributesW`→`CfOpenFileWithOplock`(失败日志 `CfOpenFileWithOplock fail 1/2 %s, %d`)→**`CfDehydratePlaceholder`**→`CfCloseHandle` |
| `qcSetPinState` (23) | `0x1000c620` | **`CfSetPinState(handle, CF_PIN_STATE, 0, NULL)`**，5 分支跳表（值 0..4），见 §4 |
| `qcSetPinStateByPath` (24) | `0x1000c450`→`0x1000c53d`→`0x1000c620` | `GetFileAttributesW`→`CreateFileW`→`CfSetPinState`→`CloseHandle` |
| `qcSetInSyncState` (21) | —（直接内联） | **`CfSetInSyncState(handle, state, flags=0, NULL)`**（两处分支：InSync=1 / NotInSync=0） |
| `qcSetInSyncStateByPath` (22) | `0x1000c6b0`→`0x1000c7a1`→`0x1000c834` | `GetFileAttributesW`→`CreateFileW`→`CfSetInSyncState`→`CloseHandle` |
| `qcExecuteAction` (7) | — | **`CfExecute(&CF_OPERATION_PARAMETERS, &CF_OPERATION_INFO)`**（唯一向占位符**写数据**的通道，见 §5） |
| `qcReportTransferState` (18) | — | **`CfReportProviderProgress`**（进度上报，参数含 TransferKey/总长/已完成） |
| `qcEnsureThumbnailProviderRegistered` (6) | `0x10002d70` | 无 Cf*；`RegOpenKeyExW(SyncRootManager)`+`RegEnumKeyExW` 找 `QNAPQsyncCloudProvider!` 前缀的子键 → `RegSetValueExW(L"ThumbnailProvider", {DB2717F9-CAD3-4516-9BB5-2A93C2D4AAB9})` |
| `qcSetErrorStatus` (20) | `0x1000c890`→`0x10010a50` | `SHCreateItemFromParsingName` + `SHChangeNotify`（Explorer 刷新，非 cldapi） |
| `qcRemoveErrorStatus` (17) | `0x1000c890`→`0x10010a50` | 同上 |

> `qcSetErrorStatus` 的完整签名（`QsyncLib.dll@0x10012400` 转发）为 3 参数，第 2 参数是常量字符串 `L"Error"`（`QsyncLib.dll@0x1058d908`），第 1 参数是路径。

**符号级证据（导出的 Cf* 调用点）** —— `QsyncCloudFile.dll` 的 cldapi IAT：

```
IAT 0x1001425c CfCloseHandle      0x10014254 CfConvertToPlaceholder
IAT 0x10014264 CfConnectSyncRoot  0x10014288 CfCreatePlaceholders
IAT 0x10014274 CfDehydratePlaceholder 0x10014258 CfDisconnectSyncRoot
IAT 0x10014290 CfExecute          0x1001426c CfGetPlaceholderInfo
IAT 0x10014280 CfGetPlatformInfo  0x1001428c CfGetSyncRootInfoByPath
IAT 0x10014270 CfHydratePlaceholder 0x10014268 CfOpenFileWithOplock
IAT 0x10014260 CfReportProviderProgress 0x10014294 CfRevertPlaceholder
IAT 0x1001427c CfSetInSyncState   0x10014278 CfSetPinState
IAT 0x10014284 CfUpdatePlaceholder
```

### 1.1 QsyncLib.dll 侧的 qc* ABI 表（谁调用了谁）

`QsyncLib.dll@0x100120b0` 是加载器：`LoadLibraryW(L"QsyncCloudFile.dll")`（字符串 `QsyncLib.dll@0x1054d66c`）+ 29 次 `GetProcAddress`，把函数指针填入一个全局结构体（指针存于 `QsyncLib.dll@0x10638c84`）：

| 偏移 | 函数 | 偏移 | 函数 |
|---|---|---|---|
| +0x00 | HMODULE | +0x40 | `qcHydratePlaceholder` |
| +0x04 | loaded(bool) | +0x44 | `qcHydratePlaceholderByPath` |
| +0x08 | `qcInit` | +0x48 | `qcDehydratePlaceholder` |
| +0x0c | `qcUninit` | +0x4c | `qcSetPinState` |
| +0x10 | `qcIsRegisteredSyncRoot` | +0x50 | `qcSetPinStateByPath` |
| +0x14 | `qcRegisterSyncRoot` | +0x54 | `qcSetInSyncState` |
| +0x18 | `qcUnregisterSyncRoot` | +0x58 | `qcSetInSyncStateByPath` |
| +0x1c | `qcConnectSyncRoot` | +0x5c | `qcExecuteAction` |
| +0x20 | `qcDisconnectSyncRoot` | +0x60 | `qcReportTransferState` |
| +0x24 | `qcCreatePlaceholder` | +0x64 | `qcSupportCloudFiles` |
| +0x28 | `qcConvertToPlaceholder` | +0x68 | `qcIsSyncRootRegistered` |
| +0x2c | `qcRevertPlaceholderByPath` | +0x6c | `qcSetErrorStatus` |
| +0x30 | `qcUpdatePlaceholderByPath` | +0x70 | `qcRemoveErrorStatus` |
| +0x34 | `qcUpdatePlaceholder` | +0x74 | `qcGetSyncRootId` |
| +0x38 | `qcGetPlaceholderInfo` | +0x78 | `qcEnsureThumbnailProviderRegistered` |
| +0x3c | `qcGetPlaceholderInfoByPath` | | |

证据片段（`QsyncLib.dll@0x100120ea` 起）：

```
0x100120ea  68a0d65410      push 0x1054d6a0        ; STR:qcInit
0x100120f0  ffd7            call edi               ; GetProcAddress
0x100120fa  6894d65410      push 0x1054d694        ; STR:qcUninit
0x10012101  894608          mov dword ptr [esi+8], eax   ; 表[0x08]=qcInit
0x1001210e  68c0d65410      push 0x1054d6c0        ; STR:qcRegisterSyncRoot
0x10012115  89460c          mov dword ptr [esi+0xc], eax ; 表[0x0c]=qcUninit
0x10012129  894614          mov dword ptr [esi+0x14], eax ; 表[0x14]=qcRegisterSyncRoot
...
0x100122f1  894670          mov dword ptr [esi+0x70], eax ; 表[0x70]=qcRemoveErrorStatus
0x10012301  894674          mov dword ptr [esi+0x74], eax ; 表[0x74]=qcGetSyncRootId
0x1001230e  894678          mov dword ptr [esi+0x78], eax ; 表[0x78]=qcEnsureThumbnailProviderRegistered
```

`QFileSync.dll` 也独立 `LoadLibraryW` 该 DLL（`QFileSync.dll` 内含 UTF-16 字符串 `QsyncCloudFile.dll`，文件偏移 0x1a129c），并使用同一批 `qc*` 名字（`QFileSync.dll` 字符串 `CreateCloudFile qcConvertToPlaceholder FAILED(%s)(%d)`、`qcDehydratePlaceholder FAILED(%s)(%d)(%d)(%d)` 等）。

---

## 2. 同步根（sync root）：id、注册位置、回调

### 2.1 同步根 id 的拼接方式

id 的唯一构造点在 `QsyncCloudFile.dll@0x10002b50`（由 `qcRegisterSyncRoot → 0x100017b0` 调用），格式为：

```
<providerName> "!" <用户 SID 字符串> "!" <调用方传入的会话/标识串>
```

拼装证据（`QsyncCloudFile.dll@0x10002b50`）：

```
0x10002bd6  lea ecx,[ebp-0x1c]
0x10002be6  call dword ptr [0x1001424c]   ; api-ms-win-security-sddl-l1-1-0!ConvertSidToStringSidW
0x10002c29  call 0x10008560               ; wstring = <寄存器参数 edx 指向的字符串>
0x10002c31  push 0x10016cdc ; "!"          ; ← 文件偏移 0x156dc = 21 00 00 00 = L"!"
0x10002c3c  call 0x10008660               ; append "!"
0x10002c64  call 0x10008660               ; append SID 串
0x10002c6c  push 0x10016cdc ; "!"
0x10002c73  call 0x10008660               ; append "!"
0x10002c94  call 0x10008660               ; append 栈参数1（[ebx+8]）
```

其中 SID 来自当前进程令牌（`GetTokenInformation(TokenUser)`，`QsyncCloudFile.dll@0x10002a80`）。三个分量的来源：

- 第 1 段 = `qcRegisterSyncRoot` 的第 2 参数。调用方 `CloudFileMan::RegisterSyncRoot` 硬编码传 `L"QNAPQsyncCloudProvider"`：
  ```
  QsyncLib.dll@0x100092c2  68bc625410   push 0x105462bc   ; STR16:QNAPQsyncCloudProvider
  QsyncLib.dll@0x100092c7  ff7508       push dword ptr [ebp+8]
  QsyncLib.dll@0x100092ca  ffd0         call eax          ; eax = 表[0x14] = qcRegisterSyncRoot
  ```
- 第 3 段 = `qcRegisterSyncRoot` 的第 3 参数 ← `CloudFileMan::RegisterSyncRoot([ebp+0xc])` ← `CQsyncSession::RegisterSyncRoot`（`QsyncLib.dll@0x100e2c00`，日志 `[Thumbnail] CQsyncSession::RegisterSyncRoot begin root=%s session=%s display=%s saveSyncRootId=%d useSpaceSaving=%d`，字符串 `QsyncLib.dll@0x10581428`）。**该段的具体文本未逐字节确认**，只确认它是会话层传入的字符串（很可能是 session/NAS 标识）。
- provider 名另有独立用途：`IsSyncRootRegistered` 用 `CfGetSyncRootInfoByPath` 的标准信息缓冲 `+0x1c` 处内联宽串与 `L"QNAPQsyncCloudProvider"` 比较（`QsyncCloudFile.dll@0x1000286a` 引用该常量）；`EnsureThumbnailProviderRegistered` 用 `"QNAPQsyncCloudProvider" + "!"` 前缀去枚举同步根注册表子键（`QsyncCloudFile.dll@0x10002dad`、`0x10002dd0`）。

### 2.2 注册表位置

同步根注册由 `StorageProviderSyncRootManager` 完成（写入 `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\SyncRootManager\<syncRootId>`），Qsync 随后**自己**在该子键下补写缩略图提供者：

- `QsyncCloudFile.dll@0x10015318`：`SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\SyncRootManager`（UTF-16）
- `QsyncCloudFile.dll@0x10001c31`：`push 0x10016918` + `push 0x42`（长度 0x42=66）→ 构造 `...\SyncRootManager`
- `QsyncCloudFile.dll@0x10001c4c`：追加 `L"\"`（0x100168b4 = `5c 00 00 00`）
- `QsyncCloudFile.dll@0x10001c72`：追加同步根 id 字符串（`[ebp-0xa4]`，即 `0x10002b50` 的结果）
- `QsyncCloudFile.dll@0x10001cc9`：`RegSetValueExW(..., L"ThumbnailProvider", REG_SZ, 数据=CLSID 串)`；数据来自 `QsyncCloudFile.dll@0x100169a0`（长度 0x4e=78 字节的宽串缓冲区，即 `{DB2717F9-CAD3-4516-9BB5-2A93C2D4AAB9}`，`QsyncCloudFile.dll@0x100153a0`）

另外注册函数 `0x100017b0` 还引用 `SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Desktop\NameSpace`（`QsyncCloudFile.dll@0x10016ad8`，引用点 `0x10001ed8`、`0x10001f65`）与默认图标 `%SystemRoot%\system32\shell32.dll,-257`（`@0x100168b8`，引用点 `0x10001a3e`），即注册的 `StorageProviderSyncRootInfo` 属性包含 `IconResource`（默认 shell32 图标）。

### 2.3 `CfConnectSyncRoot` 注册了哪些回调

`qcConnectSyncRoot`（导出，`QsyncCloudFile.dll@0x1000ffd0`）先在堆上构造一个 0xA0 字节的管理对象，**硬编码回调表**在对象 `+0x28`：

```
0x100100ac  c7472800000000   mov dword ptr [edi+0x28], 0          ; Type = 0  CF_CALLBACK_TYPE_FETCH_DATA
0x100100b3  c7472ce0a00010   mov dword ptr [edi+0x2c], 0x1000a0e0 ; 回调函数
0x100100ba  c7473002000000   mov dword ptr [edi+0x30], 2          ; Type = 2  CF_CALLBACK_TYPE_CANCEL_FETCH_DATA
0x100100c1  c74734e0a10010   mov dword ptr [edi+0x34], 0x1000a1e0 ; 回调函数
0x100100c8  c74738ffffffff   mov dword ptr [edi+0x38], 0xffffffff ; CF_CALLBACK_TYPE_NONE 结束
```

实际调用（`QsyncCloudFile.dll@0x1000a6a0`）：

```
0x1000a6d3  lea eax,[ebx+0x20]   ; arg5 = &ConnectionKey
0x1000a6d6  push eax
0x1000a6d7  push 6               ; arg4 = CF_CONNECT_FLAG_REQUIRE_PROCESS_INFO(2)|REQUIRE_FULL_FILE_PATH(4)
0x1000a6d9  push ebx             ; arg3 = CallbackContext = 管理对象
0x1000a6da  lea eax,[ebx+0x28]
0x1000a6e4  push eax             ; arg2 = CF_CALLBACK_REGISTRATION 表
0x1000a6e5  push esi             ; arg1 = SyncRootPath
0x1000a6e6  call dword ptr [0x10014264]   ; cldapi.dll!CfConnectSyncRoot
```

即 **cldapi 层只注册 `FETCH_DATA`(0) 和 `CANCEL_FETCH_DATA`(2)**（没有 VALIDATE_DATA / NOTIFY_DELETE / DEHYDRATE 回调）。

回调实现（静态函数）：

- `QsyncCloudFile.dll@0x1000a0e0`：日志 `OnFetchData %s callback.`（`QsyncCloudFile.dll@0x10017348`）。
  参数解读（x86 `CF_CALLBACK_INFO` 8 字节对齐布局，已用多个字段验证）：
  `[+0x10]=CallbackContext`、`[+0x14]=VolumeGuidName`、`[+0x18]=VolumeDosName`、`[+0x40]=FileIdentity`、`[+0x44]=FileIdentityLength`、`[+0x48]=NormalizedPath`、`[+0x08]=ConnectionKey`、`[+0x50]=TransferKey`。
  代码把 `VolumeDosName + NormalizedPath` 拼成路径打印，然后
  ```
  0x1000a1a0  mov ecx, dword ptr [esi+0x10]   ; ecx = CallbackContext（管理对象）
  0x1000a1ab  push esi                        ; CF_CALLBACK_INFO*
  0x1000a1ac  call 0x1000a2e0                 ; 分发
  ```
- `QsyncCloudFile.dll@0x1000a1e0`：日志 `OnCancelFetchData %s callback.`，调用 `0x1000a4c0`。

**分发器** `QsyncCloudFile.dll@0x1000a2e0`：以 `CallbackContext+0x98`（一个 std::map，key = 回调类型 id）查找注册的处理函数并调用 `[[node+0x14]](&copied_callback_info, &params)`；注册发生在 `CfConnectSyncRoot` 成功之后（`QsyncCloudFile.dll@0x1000a705` 起的循环，输入是一张 `{id, fn}` 数组，`-1` 结束）。

**业务实现在 `QsyncLib.dll`**（这就是 TOOLKIT 提示的 `CloudFileMan::OnFetchData`）。`CloudFileMan::ConnectSyncRoot`（`QsyncLib.dll@0x10009460`）调用 `qcConnectSyncRoot(path, &0x1062ad00, ctx, ×)`，其中 `0x1062ad00` 是静态处理函数表（`QsyncLib.dll` `.data`）：

```
.file 0x628d00 (= VA 0x1062ad00)
  +0x00  type=0 (CF_CALLBACK_TYPE_FETCH_DATA)    fn=0x10009540   ← CloudFileMan::OnFetchData
  +0x08  type=1 (CF_CALLBACK_TYPE_VALIDATE_DATA) fn=0x10009790
  +0x10  type=-1 (NONE)                          fn=0
```

对应的日志字符串（`QsyncLib.dll`，UTF-16）：

```
QsyncLib.dll@0x105462f0  CloudFileMan::RegisterSyncRoot(%s)(%s)(%x)
QsyncLib.dll@0x10546348  CloudFileMan::UnregisterSyncRoot(%s)(%x)
QsyncLib.dll@0x105463a0  CloudFileMan::ConnectSyncRoot(%s) failed(%x)
QsyncLib.dll@0x10546400  CloudFileMan::DisconnectSyncRoot Failed(%x)
QsyncLib.dll@0x10546458  CloudFileMan::OnFetchData(%s)
QsyncLib.dll@0x10546498  CloudFileMan::OnCancelFetchData(%s)
```

> 说明：cldapi 层没有注册 `NOTIFY_DELETE`/`NOTIFY_RENAME`/`NOTIFY_DEHYDRATE` 等回调，因此 Qsync 的删除/改名确认**不是**通过 cldapi 回调完成的，而是走它自己的扫描/日志数据库（`CQsyncSession::ScanCompleteAction` 等）。

---

## 3. 占位符元数据（`CF_PLACEHOLDER_CREATE_INFO` / `FileIdentity`）

### 3.1 谁填充 `CF_PLACEHOLDER_CREATE_INFO`

`QsyncCloudFile.dll@0x1000b2a0`（`qcCreatePlaceholder` 的实现）从调用方传入的描述结构 `[edi]` 组装 `CF_PLACEHOLDER_CREATE_INFO`，然后：

```
0x1000b465  lea ecx,[ebp-0xa0]      ; &CF_PLACEHOLDER_CREATE_INFO（数组基址）
0x1000b476  push 0                  ; arg5 EntriesProcessed = NULL
0x1000b478  push 0                  ; arg4 CF_CREATE_FLAGS = CF_CREATE_FLAG_NONE
0x1000b47a  push 1                  ; arg3 PlaceholderCount = 1
0x1000b47c  push ecx                ; arg2 数组
0x1000b47d  push eax                ; arg1 FilePath（同步根/目录路径，若末尾无 '\' 会补）
0x1000b47e  call dword ptr [0x10014288]  ; cldapi.dll!CfCreatePlaceholders
```

**FileIdentity 的内容与长度**（关键）：

```
0x1000b34b  mov edx, dword ptr [edi+0x28]   ; ← 调用方提供的字符串指针（描述结构 +0x28）
0x1000b379  call 0x10008560                 ; 复制到局部 wstring [ebp-0x4c]
0x1000b397  mov dword ptr [ebp-0x68], eax   ; FileIdentity = 该 wstring 的数据指针
0x1000b3b6  mov dword ptr [ebp-0x60], 2     ; （枚举/标志位 = 2）
0x1000b3bd  lea eax,[ecx+1]                 ; strlen(w)+1
0x1000b3c6  add eax,eax                     ; ×2  → 字节数
0x1000b3d4  mov dword ptr [ebp-0x64], eax   ; FileIdentityLength = 2*(wcslen+1)，**含结尾 NUL**
```

结论：
- **`FileIdentity` 是一个 UTF-16 字符串**（不是不透明二进制 blob），且 `FileIdentityLength` 把结尾 NUL 也算进去。
- 另外两处对 `CF_PLACEHOLDER_CREATE_INFO.Flags` 的加工：
  ```
  0x1000b42c  test ecx, 0x80000        ; FILE_ATTRIBUTE_PINNED
  0x1000b436  xor eax, 0x80000         ; 传给 cldapi 前剥掉 pinned 属性
  0x1000b43e  test cl, 0x10
  0x1000b446  mov dword ptr [ebp-0x60], 3   ; flags&0x10 时改标志/尺寸
  0x1000b44d  movlpd qword ptr [ebp-0x70], xmm0  ; FileSize=0
  ```
  （与 §6 的 `SetFileAttributes^|FILE_ATTRIBUTE_PINNED` 日志互相印证：Qsync 把 Win32 属性 `FILE_ATTRIBUTE_PINNED=0x00080000` 与 cfapi 的 pin state 一起使用。）

### 3.2 `FileIdentity` 的语义（被谁读、怎么用）

`QsyncLib.dll` 的 `CloudFileMan::OnFetchData`（`@0x10009540`）在回调里读 `CF_CALLBACK_INFO+0x40`，**当作宽字符串**用于日志/路径：

```
0x100095f5  mov edx, dword ptr [edi+0x40]    ; FileIdentity
0x10009602  lea esi,[ecx+2] ... strlen ...
0x10009614  push ecx / push edx
0x10009619  call 0x10009140                  ; wstring::assign(&buf, FileIdentity, len)
0x1000962b  push 0x10546458                  ; "CloudFileMan::OnFetchData(%s)"
```

同时 `CallbackInfo+0x10`（CallbackContext，即 `qcConnectSyncRoot` 传进来的对象）里保存了每个同步根的上下文（`QsyncLib.dll` 侧传入的 `ctx`），OnFetchData 也会取用其中的字符串/对象。因此实现上等价于：

```
远端/本地路径 = f(CallbackContext 中的根路径, FileIdentity 中的相对路径字符串)
```

**未完全确认**：`FileIdentity` 里到底是 NAS 端路径还是本地相对路径（证据只能确定它是宽字符串并被当作路径拼接/打印）。旁证：`QFileSync.dll` 的 `CQWin32Connection::QFileGetFilePinState (CaseDisMatch)(strTempPathName=%s)` 与 `TranslatePath`/`TranslateBackDir` 说明本地显示路径与 NAS 路径之间有映射层。

### 3.3 `QFileSync.dll` 侧的封装链（QFile* ↔ qc*）

`QFileSync.dll` 导出的相关 API 只是 C 风格转发器（`QFileGetFileSize@0x10005b70`、`QFileReadFile@0x10005bb0` 都只做 `this->vtable[N]` 转发，函数体内无 Cf* 调用）：

| QFileSync 导出 | 内部/日志证据 | 与 qc*/cldapi 的关系 |
|---|---|---|
| `QFileCreatePlaceholder` (19, `@0x1000f8a0`) | 校验 3 个参数（路径、第二个路径、size ≥ 0）；`GetTempFileNameW(dir, L"qsync", 0, buf)`（`QFileSync.dll@0x101b4a70` = `qsync`）；日志 `QFileCreatePlaceholder(ERROR_DISK_FULL)(%d)(DestPath=%s)`、`QFileCreatePlaceholder(GenerateRandomFileName Failed)(%d)(%s)(%s)`、`QFileCreatePlaceholder(OpenFile Failed)(%d)` | 生成临时占位文件名 → 走 `CreateCloudFile` 序列 |
| `QFileGetFilePinState` (48, `@0x1000feb0`) / `QFileGetFilePinStateByPath` (49, `@0x1000fee0`) | `CQWin32Connection::QFileGetFilePinState(%s) ConvertPinState Failed`、`ConvertPinState(QCF_PIN_STATE) UNKNOWN PIN STATE(%d)`、`ConvertPinState(QFILE_FILE_PIN_STATE) UNKNOWN PIN STATE(%d)` | 读占位符状态（`qcGetPlaceholderInfo` → `CF_PLACEHOLDER_STANDARD_INFO` 的 pin state）并转换成 Qsync 自己的 `QFILE_FILE_PIN_STATE`（出现过 `QFILE_FILE_PIN_STATE_UNPINNED` / `_EXCLUDED`） |
| `QFileUpdatePlaceholderInfo` (103, `@0x1000fc00`) | `GetFileAttributesExW`；日志 `QFileUpdatePlaceholderInfo qcUpdatePlaceholderByPath failed(%s)(%d)(%d)` | → `qcUpdatePlaceholderByPath`（写 FileIdentity/大小/时间） |

`QFileSync.dll` 里 `CreateCloudFile` 的完整状态机可以直接从日志串序列读出来（同一模块字符串表）：

```
CreateCloudFile GetFileAttributesEx FAILED(%s)(%d)              → 先探测本地是否已有文件
CreateCloudFile qcConvertToPlaceholder FAILED(%s)(%d)(%d)       → 已存在：就地转占位符
CreateCloudFile qcUpdatePlaceholderByPath FAILED(%s)(%d)(%d)(%d)→ 写元数据（FileIdentity/大小/时间戳）
CreateCloudFile qcSetPinStateByPath FAILED(%s)(%d)              → 设 pin state
CreateCloudFile qcDehydratePlaceholder FAILED(%s)(%x)(%d)       → 立即脱水（只留元数据）
CreateCloudFile Delete cloud file(%s)(size=%lld)                → 清理实体文件
CreateCloudFile FAILED(%s)(%d)(%d)(%d)
```

`QFileSync.dll` 另有 `CQWin32Connection::ConvertFileByType(%s) qcDehydratePlaceholder FAILED(%d)(%d)` → 即“按类型/策略转换文件”时也会脱水。

---

## 4. pin state 语义与“空间节省模式”

### 4.1 Qsync 使用的 `CF_PIN_STATE_*`

`qcSetPinState` 的实现 `QsyncCloudFile.dll@0x1000c620` 是一个 5 路跳转表，**输入枚举与 `CF_PIN_STATE` 一一对应（0..4）**，非 0..4 或句柄为 -1 时返回 `0x80070057`：

```
0x1000c620  83f9ff        cmp ecx, -1            ; 无效句柄 → E_INVALIDARG
0x1000c627  83fa04        cmp edx, 4             ; 0..4
0x1000c62c  ff249590c60010 jmp dword ptr [edx*4 + 0x1000c690]
; 跳表 @0x1000c690 = { 0x1000c633, 0x1000c640, 0x1000c652, 0x1000c664, 0x1000c676 }
0x1000c639  call cldapi!CfSetPinState   ; eax=0 → CF_PIN_STATE_UNSPECIFIED
0x1000c64b  call cldapi!CfSetPinState   ; eax=1 → CF_PIN_STATE_PINNED
0x1000c65d  call cldapi!CfSetPinState   ; eax=2 → CF_PIN_STATE_UNPINNED
0x1000c66f  call cldapi!CfSetPinState   ; eax=3 → CF_PIN_STATE_EXCLUDED
0x1000c681  call cldapi!CfSetPinState   ; eax=4 → CF_PIN_STATE_INHERIT
; 4 个 push: push 0(flags) push 0(reserved) push eax(pinState) push ecx(handle)
```

`CF_PIN_STATE` 官方定义（MS Learn）：

| 值 | 名称 | 语义 |
|---|---|---|
| 0 | `CF_PIN_STATE_UNSPECIFIED` | 平台自由决定内容是否需要本地存在 |
| 1 | `CF_PIN_STATE_PINNED` | 平台异步通知 provider 取回内容；平台会**拒绝**对 pinned 占位符的脱水请求 |
| 2 | `CF_PIN_STATE_UNPINNED` | 平台异步通知 provider 脱水/失效 |
| 3 | `CF_PIN_STATE_EXCLUDED` | 永不同步到云端（只能由 provider 设置） |
| 4 | `CF_PIN_STATE_INHERIT` | 按父目录重新计算（移动语义） |

Qsync 自己在业务层用同一套名字（`QCF_PIN_STATE_*`，见 `QsyncLib.dll` 字符串）：

```
QCF_PIN_STATE_UNSPECIFIED / QCF_PIN_STATE_PINNED / QCF_PIN_STATE_UNPINNED / QCF_PIN_STATE_EXCLUDED
QCF_IN_SYNC_STATE_IN_SYNC
QSYNCSYNCDLL_PIN_STATE / QSYNCSYNCDLL_IN_SYNC_STATE   （对外导出 ABI，见 ?IsCloudFile@CQsyncSyncDll@@...）
QFILE_FILE_PIN_STATE_UNPINNED / QFILE_FILE_PIN_STATE_EXCLUDED （QFile 层再包一层）
```

### 4.2 “空间节省模式” = `UNPINNED` + 主动脱水

`CQsyncSession::ScanCompleteAction` 的分支（`QsyncLib.dll@0x10140d38`）：

```
0x10140d47  b902000000    mov ecx, 2                 ; ← QCF_PIN_STATE_UNPINNED
0x10140d4c  call 0x101c55d0                          ; qcSetPinState(path, 2)
0x10140d6f  6888b65910    push "CQsyncSession::ScanCompleteAction(%s) qcSetPinState(QCF_PIN_STATE_UNPINNED) failed(%s)(%d)"
0x10140d8f  push eax / call 0x10012320               ; 表[+0x48] = qcDehydratePlaceholder(path)
0x10140db0  push "CQsyncSession::ScanCompleteAction(%s) qcDehydratePlaceholder failed(%s)(%d)"
0x10140dd3  call 0x10012360                          ; 表[+0x58] = qcSetInSyncStateByPath(path, 1?) 
...
0x10140e01  b901000000    mov ecx, 1                 ; ← QCF_PIN_STATE_PINNED（另一分支）
0x10140e06  call 0x101c55d0                          ; qcSetPinState(path, 1)
0x10140e29  push "CQsyncSession::ScanCompleteAction(%s) qcSetPinState(QCF_PIN_STATE_PINNED) failed(%s)(%d)"
```

以及 UI/设置层证据：

- 图标资源真实存在：`$WD/Res/QsyncFolder_space_saving_mode.ico`、`$WD/Res/QsyncFolder_space_saving_mode_win11.ico`；字符串 `%sres\QsyncFolder_space_saving_mode.ico`（`QsyncLib.dll@0x…` 字符串表第 628 行）与 `..._win11.ico`。
- `CQsyncSession::SpaceSavingModeChange(%s) m_bUseSpaceSaving(%d)`（`QsyncLib.dll@0x1058ddb0` 引用点 `@0x101025fa`）——每个 session 有独立开关。
- `CQsyncSyncDll` 导出：`?SupportSpaceSaving@CQsyncSyncDll@@QAE_NXZ`、`?SyncPairUseSpaceSaving@CQsyncSyncDll@@QAE_NPAX@Z`、`?RegisterSpaceSavingSyncFolder@CQsyncSyncDll@@QAE_NPB_W@Z`、`?UpdateSpaceSavingSettingBySharePath@...`。
- `Qsync.exe` UI 文本：`Free Up Space Now`、`Free up space`、`Free up space automatically:`、`Last free up space date: %1`、以及
  `Files in Space-Saving Mode do not support smart delete. To free up space on your device, right-click the file and select "Free up space but keep on NAS".`
- `CQsyncSession::CreateUnpinnedFileThread(%s) CreateCloudFile(%s) failed(%d)` —— 新建文件时直接进入 “unpinned” 状态。
- `CQsyncSession::SyncFileWithFlag(%s)SetFileAttributes^ FILE_ATTRIBUTE_PINNED(%s)` / `|FILE_ATTRIBUTE_PINNED` —— 同时维护 Win32 属性位 0x00080000。

**结论**：空间节省模式 = 该同步对（folder pair）的文件在本地保持为**仅元数据**；provider 侧用 `CF_PIN_STATE_UNPINNED(2)` 标记并显式调用 `CfDehydratePlaceholder`（等价于 OneDrive 的 “Free up space”）。`CF_PIN_STATE_EXCLUDED(3)` 用于备份作业/不应下载的路径（`CQsyncSession::BackupJobDirEnterAction/SyncFileWithFlag … (QCF_PIN_STATE_EXCLUDED)`）。`CF_PIN_STATE_PINNED(1)` 对应 “保留在本机”。

---

## 5. 水合（hydrate）触发条件与流程

### 5.1 触发

Explorer/应用打开或读取一个“未水合”（`FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS`）的占位符时，Windows 过滤管理器不会自己下载，而是回调 provider。Qsync 的链路：

```
Explorer 读取占位符
  → cldapi 调 QsyncCloudFile.dll@0x1000a0e0   (CF_CALLBACK_TYPE_FETCH_DATA)
      log "OnFetchData %s callback."   (%s = VolumeDosName+NormalizedPath，见 §2.3)
  → QsyncCloudFile.dll@0x1000a2e0               (按 CallbackContext 的 map 分发 type=0)
  → QsyncLib.dll@0x10009540                     (CloudFileMan::OnFetchData)
      log "CloudFileMan::OnFetchData(%s)"       (%s = CF_CALLBACK_INFO->FileIdentity 宽串)
```

`CloudFileMan::OnFetchData` 的签名是标准 `__stdcall (CF_CALLBACK_INFO*, CF_CALLBACK_PARAMETERS*)`（`ret 8`，`QsyncLib.dll@0x1000977d`）。

### 5.2 参数解析与 128 KiB 分片（`QsyncLib.dll@0x100096ca`）

```
0x100096cd  mov eax,[edx+0x08]      ; FetchData.RequiredFileOffset 低 32 位
0x100096d0  mov ecx,[edx+0x0c]      ; 高 32 位
0x100096d3  mov [edi+0x60],eax      ; task+0x60 = 偏移(64bit)
0x100096d6  mov [edi+0x64],ecx
0x100096d9  mov ecx,[edx+0x14]      ; FetchData.RequiredLength 高 32 位
0x100096dc  mov eax,[edx+0x10]      ; 低 32 位
0x100096df  test ecx,ecx
0x100096e1  jl  0x100096f3
0x100096e3  jg  0x100096ec
0x100096e5  cmp eax, 0x20000        ; 0x20000 = 131072 = 128 KiB
0x100096ea  jbe 0x100096f3
0x100096ec  mov eax,0x20000         ; 超过 128 KiB → 截断
0x100096f1  xor ecx,ecx
0x100096f3  mov [edi+0x68],eax      ; task+0x68 = 实际请求长度(64bit，≤128KiB)
0x100096ff  mov [edi+0x6c],ecx
```

（观察到的 `CF_CALLBACK_PARAMETERS` 字段偏移是 `RequiredFileOffset@+0x08`、`RequiredLength@+0x10`，即该 SDK 中 `FetchData` 联合体从 +0x04 开始；官方文档的字段顺序一致，仅是 packing/对齐差异。**语义确定：offset + length，且 length 被上限 128 KiB 截断 ⇒ Qsync 是分块（range）下载**。）

### 5.3 异步线程与下载

任务对象 `new(0x78)`，把整个 `CF_CALLBACK_INFO`（0x58 字节）拷进 `task+0x08`，再补上 ConnectionKey/TransferKey/offset/length，然后起线程（`QsyncLib.dll@0x10009738`，`_beginthreadex` 风格：6 个参数，返回的线程句柄存 `task+0x70`）：

```
0x10009738  push &tid
0x10009739  push 0
0x1000973b  push edi                 ; 线程参数 = task
0x1000973c  push 0x100c5b30          ; 线程入口
0x10009741  push 0
0x10009743  push 0
0x1000974a  call 0x104ab0ad          ; CRT _beginthreadex
0x10009752  mov [edi+0x70],eax       ; 线程句柄
```

线程入口 `QsyncLib.dll@0x100c5b30`：取 `task+0x74`（一个 64 位 Key 的低位）作为对象，调用 `0x10168120(ecx, task)` 做真正的工作，然后 `CloseHandle(task+0x70)`、释放引用、`free(task, 0x78)`。

**下载实现**：`QsyncLib.dll@0x101687e6`（在 `CQsyncSession::CloudFileCopy` 内，`0x10168120` 的调用链上）先调用 **`QsyncSync.dll!QBackCloudFileCopy`**（IAT `0x1050869c`），随后立即用返回码调用 `qcExecuteAction` 把这段数据写回占位符：

```
0x1016875f  call dword ptr [0x1050869c]   ; QsyncSync.dll!QBackCloudFileCopy   ← 真正取数据
0x10168768  mov [ebp-0xc4ac], eax         ; dwRet
0x10168781  push "CQsyncSession::CloudFileCopy(%s) Failed(%d)"   ; 失败日志
0x101687bf  push [eax+0x6c]  ; Length.hi
0x101687c2  push [eax+0x68]  ; Length.lo        ← ≤128KiB
0x101687c5  push [eax+0x64]  ; Offset.hi
0x101687c8  push [eax+0x60]  ; Offset.lo
0x101687cb  push 0
0x101687cd  push [ebp-0xc4ac] ; dwRet
0x101687d3  push ecx
0x101687d4  push [eax+0x54]  ; TransferKey.hi
0x101687dd  push [eax+0x50]  ; TransferKey.lo
0x101687e0  push [eax+0x0c]  ; ConnectionKey.hi
0x101687e3  push [eax+0x08]  ; ConnectionKey.lo
0x101687e6  call 0x100123a0  ; → 表[+0x5c] = qcExecuteAction
0x10168803  push "CQsyncSession::CloudFileCopy(%s) error ack(dwRet=%d)(hrAck=0x%08X)"
```

`qcExecuteAction`（`QsyncCloudFile.dll@0x100105d0`）是一个 11 参数、按“操作类型”（`[ebp+0x18]`，本例=0）做 4 路跳表分派的 CfExecute 包装：

```
0x10010687  mov dword ptr [esp+0x58], 0x28  ; sizeof(CF_OPERATION_INFO)，所有分支共用
0x10010698  jmp dword ptr [eax*4 + 0x100107e4]
; 跳表 @0x100107e4 = { 0x10010751(arg5==0), 0x1001069f(arg5==1), 0x100106f3(arg5==2), 0x10010747(arg5==3) }
; ---- 分支 arg5==0（CloudFileCopy 走这条；0x10010751）----
0x10010751  mov ecx,[esi+0x24] / mov eax,[esi+0x20]   ; ConnectionKey ← 已连接同步根对象
0x1001075e  mov [esp+0x6c], ebx / mov [esp+0x68], edi ; TransferKey ← CF_CALLBACK_INFO+0x50/+0x54
0x1001076a  mov dword ptr [esp+0x5c], 0   ; ★ CF_OPERATION_INFO.Type = 0 = CF_OPERATION_TYPE_TRANSFER_DATA
0x10010772  mov dword ptr [esp+0x30], 0x28 ; CF_OPERATION_PARAMETERS（大小字段，0x28 字节）
0x1001077a  call 0x100109e0                ; 取要写回的数据缓冲（参数=下载返回码）
0x10010782  mov [esp+0x3c], eax            ; params: Buffer
0x1001077f  mov ecx,[ebp+0x28] / 0x10010795 mov eax,[ebp+0x2c]  ; params: offset/length（≤128 KiB，来自 task+0x60..0x6c）
0x100107b1  call dword ptr [0x10014290]    ; cldapi.dll!CfExecute(&params, &info)
; ---- 分支 arg5==1（0x1001069f）----
0x100106ac  mov dword ptr [esp+0x5c], 5    ; 另一种 CF_OPERATION_TYPE（本例未走这条）
0x100106c0  mov dword ptr [esp+0x30], 0x18 ; 另一套参数布局
```

`CfExecute` 的两个实参：`param1 = &CF_OPERATION_PARAMETERS`（`[esp+0x30]`）、`param2 = &CF_OPERATION_INFO`（`[esp+0x58]`）；`ConnectionKey` 用 `CallbackInfo+0x08` 在 `QsyncCloudFile.dll@0x1000ad80` 查表得到同步根对象后取其 `+0x20/+0x24`。进度上报走 `qcReportTransferState → CfReportProviderProgress`（`QsyncCloudFile.dll@0x10010892`，参数含 TransferKey 与总长/已完成）。

`CloudFileMan::OnCancelFetchData`（`QsyncLib.dll@0x10546498` 日志）对应 `CANCEL_FETCH_DATA`（用户取消/60 秒超时），用于中止该分片下载。

> 与 WFM CGI 的关系：本机没有 NAS 凭据，**未直接观测到 `func=` 请求**。但 `QBackCloudFileCopy` 是 `QsyncSync.dll` 的备份/版本化引擎入口（`QBack*`），其底层通过 `QFileSync.dll → QsyncAPI.dll (WFM*)` 访问 `/cgi-bin/qsync/qsyncsrv.cgi` 或旧 `/cgi-bin/filemanager/utilRequest.cgi`（TOOLKIT 已确认两套命名空间）。**“水合走 WFM 下载”这一层为间接证据（调用链），点对点的 func= 名称未确认。**

### 5.4 未水合文件上 `QFileReadFile` / `QFileGetFileSize` 的行为

- `QFileSync.dll@0x10005b70`（`QFileGetFileSize`）与 `@0x10005bb0`（`QFileReadFile`）都是**纯转发器**：取连接对象 → `[[obj]+0xc]` 拿实现对象 → `call [[impl vtbl+0x84]]`。函数体内**没有任何 Cf*/占位符判断**。
- 也就是说：Qsync 不在 QFile 层拦截读写。占位符的逻辑大小来自 `CF_PLACEHOLDER_CREATE_INFO.FsMetadata.FileSize`（§3.1 中由描述结构 `[edi+…]` 填入），因此 `QFileGetFileSize`/Win32 `GetFileSize` 对“仅占位符”的文件返回**真实大小**而不触发下载；
- `QFileReadFile` 最终落到普通 `ReadFile`，由过滤管理器发现数据缺失 → 触发 `FETCH_DATA` → §5.1 的链路。这与 cldapi 的设计一致（读写透明）。
- 需要 pin state / in-sync 状态时，走的是显式查询接口：`QFileGetFilePinState`/`…ByPath`（`QFileSync.dll@0x1000feb0`/`@0x1000fee0`）→ `qcGetPlaceholderInfo` → `CF_PLACEHOLDER_STANDARD_INFO`，再 `ConvertPinState()` 转成 QFile/ABI 层枚举。

---

## 6. 脱水（dehydrate）策略

### 6.1 主动脱水的三条路径（全部来自字符串级证据）

1) **扫描完成后按状态收敛**（主要路径，`CQsyncSession::ScanCompleteAction`）：

```
CQsyncSession::ScanCompleteAction(%s) qcSetPinState(QCF_PIN_STATE_UNPINNED) failed(%s)(%d)
CQsyncSession::ScanCompleteAction(%s) qcDehydratePlaceholder failed(%s)(%d)
CQsyncSession::ScanCompleteAction(%s) qcDehydratePlaceholder failed(%s)(%x)(%d)
CQsyncSession::ScanCompleteAction(%s) qcDehydratePlaceholder ignored(%s)
CQsyncSession::ScanCompleteAction(%s) qcSetPinState(QCF_PIN_STATE_PINNED) failed(%s)(%d)
CQsyncSession::ScanCompleteAction(%s) qcSetPinState(QCF_PIN_STATE_UNSPECIFIED) failed(%s)(%d)
CQsyncSession::CreateUnpinnedFileThread(%s) CreateCloudFile(%s) QBackOpenFile3(%s) failed(%d)
```
   代码形态见 §4.2（先 `qcSetPinState(path, 2)` 再 `qcDehydratePlaceholder(path)`，随后 `qcSetInSyncStateByPath(path, …)`）。

2) **按文件标志/类型转换**（`CQsyncSession::SyncFileWithFlag`、`CQWin32Connection::ConvertFileByType`、`QsyncUtils::ConvertToCloudFile`）：

```
CQsyncSession::SyncFileWithFlag(%s) qcDehydratePlaceholder Skipped(%s)
CQsyncSession::SyncFileWithFlag(%s) qcDehydratePlaceholder failed(%s)(%x)(%d)
CQWin32Connection::ConvertFileByType(%s) qcDehydratePlaceholder FAILED(%d)(%d)
QsyncUtils::ConvertToCloudFile qcDehydratePlaceholder FAILED(%s)(%x)(%d)
QsyncUtils::CreateCloudFile qcDehydratePlaceholder FAILED(%s)(%x)(%d)(%d)
```

3) **新建占位符时立即脱水**（`CreateCloudFile`，见 §3.3）——这样新建的文件一开始就只占元数据。

### 6.2 “Free up space” 的定时/配额逻辑

`CQsyncSyncDll` 公开 `?FreeupSpace@CQsyncSyncDll@@QAEXXZ`（立即释放），后台逻辑在 `CQsyncDllManager`：

```
QsyncLib.dll  (字符串)
  CQsyncDllManager::FreeUpSpaceThread Start Free Up Space
  CQsyncDllManager::FreeUpSpaceThread RegSetValueEx(QSYNC_SETTINGS_SPACE_SAVING_FREE_UP_SPACE) failed(%d)
  CQsyncDllManager::FreeUpSpaceThread(%s) DuringFreeUpSpace(%d) totoal DuringFreeUpSpace(%d)
  CQsyncDllManager::FreeUpSpaceFinished Free up space finished(%s)
  CQsyncDllManager::FreeUpSpaceFinished SetTimer(TIMER_CHECK_FREE_UP_SPACE) Next trigger time(%s)
  CQsyncDllManager::GetCheckFreeUpSpaceMSTime TriggerFreeUpSpace Trigger (Day=%d)(diff=%d)
  CQsyncDllManager::GetCheckFreeUpSpaceMSTime TriggerFreeUpSpace Check FREE_UP_SPACE_BY_DISK_SIZE
  CQsyncDllManager::GetCheckFreeUpSpaceMSTime TriggerFreeUpSpace Check FREE_UP_SPACE_BY_DISK_SIZE(Trigger)
  CQsyncDllManager::GetCheckFreeUpSpaceMSTime TriggerFreeUpSpace ignored (Day=%d)(diff=%d)
  CQsyncDllManager::GetCheckFreeUpSpaceMSTime Unknown Mode(%d)
  CQsyncDllManager::GetCheckFreeUpSpaceMSTime UpdateEnableFreeUpSpaceTime(%s)
  CQsyncDllManager::GetCheckFreeUpSpaceMSTime SetTimer(TIMER_CHECK_FREE_UP_SPACE) Next trigger time(%s)
  CQsyncDllManager::StartFreeUpSpaceThread Create thread failed(%d)
  CQsyncDllManager::UpdateFreeUpSpaceSize !m_bDuringFreeUpSpace
  CQsyncSession::TriggerFreeUpSpace(%s) m_bDuringFreeUpSpace
  CQsyncSession::TriggerFreeUpSpace(%s) AddFreeUpSpaceAction failed
  CQsyncSession::StartFreeUpSpaceThread StartFreeUpSpaceThread(Success)
```

对应的注册表键（`QsyncLib.dll` 字符串）：

```
QSYNC_SETTINGS_SPACE_SAVING_FREE_UP_SPACE
QSYNC_SETTINGS_SPACE_SAVING_FREE_UP_SPACE_MODE
QSYNC_SETTINGS_SPACE_SAVING_DISK_PERCENTAGE
QSYNC_SETTINGS_SPACE_SAVING_ENABLE_FREE_UP_SPACE_TIME
QSYNC_FOLDERPAIR_SPACE_SAVING_SETTING
QSYNC_FOLDERPAIR_USE_SPACE_SAVING
```

所以策略可归纳为：
- **手动**：UI 「Free Up Space Now」→ `CQsyncSyncDll::FreeupSpace` → `FreeUpSpaceThread`（`m_bDuringFreeUpSpace` 防重入）→ 对每个 session 的候选文件 `SetPinState(UNPINNED)+Dehydrate`。
- **自动**：`TIMER_CHECK_FREE_UP_SPACE` 周期检查，`FREE_UP_SPACE_BY_DISK_SIZE` 模式按磁盘占用百分比（`QSYNC_SETTINGS_SPACE_SAVING_DISK_PERCENTAGE`）触发，`QSYNC_SETTINGS_SPACE_SAVING_ENABLE_FREE_UP_SPACE_TIME` 记录上次执行时间（`Last free up space date: %1`）。
- **仅对开启空间节省的 folder pair** 生效（`QSYNC_FOLDERPAIR_USE_SPACE_SAVING` / `SyncPairUseSpaceSaving`）。
- 另有平台侧的低磁盘/空闲超时脱水（cldapi 的 `NOTIFY_DEHYDRATE`，Qsync **未注册**该回调，因此这部分完全交给系统；参见 §2.3）。

---

## 7. `cldapi.dll` 导入表 与 API 版本要求

### 7.1 `QsyncCloudFile.dll` 如何解析 Cf*

**是普通（静态）导入表，不是 `GetProcAddress`。** 证据：

- `QsyncCloudFile.dll` 的 `IMAGE_DIRECTORY_ENTRY_IMPORT` 中直接列出 `cldapi.dll` 及 18 个 `Cf*` 函数；
- IAT（RVA 0x14000）里存放的是指向 hint/name 表的 RVA（未绑定导入的典型形态）：
  ```
  file 0x12a00: 3ecf0100 faca0100 d6ca0100 b2ca0100 ...   ; = RVA 0x1cf3e, 0x1cafa, ...
  ```
- 模块虽然导入了 `GetProcAddress`/`LoadLibraryW`（IAT `0x10014140`/`0x1001414c`，并有 ILT thunk `jmp [IAT]`：`0x100120d9`/`0x100120d3`），但它们**只用于惰性解析 `combase.dll` 的 C++/WinRT 入口**，与 cldapi 无关：
  ```
  QsyncCloudFile.dll@0x10008011  push 0x10017114   ; STR:"RoGetActivationFactory"
  QsyncCloudFile.dll@0x10008016  push 0x100172a8   ; STR16:"combase.dll"
  QsyncCloudFile.dll@0x1000801b  call 0x100120d3   ; jmp [IAT LoadLibraryW]
  QsyncCloudFile.dll@0x10008021  call 0x100120d9   ; jmp [IAT GetProcAddress]
  QsyncCloudFile.dll@0x10008a45  push 0x1001712c   ; STR:"CoIncrementMTAUsage"
  ```
  （这类 `LoadLibraryW+GetProcAddress` 成对调用共 7 处，解析出的都是 WinRT 激活入口。）
- **全模块没有任何指令引用 `"CfConnectSyncRoot"` 等 `Cf*` 名字字符串**（对 `.text` 做 4 字节立即数扫描，命中 0 次）。这些字符串只作为导入名表存在 ⇒ Cf* 只可能来自静态 IAT。

### 7.2 版本要求

- 被要求的最小 `Cf*` 集合（18 个）：`CfConnectSyncRoot`、`CfDisconnectSyncRoot`、`CfCloseHandle`、`CfOpenFileWithOplock`、`CfCreatePlaceholders`、`CfConvertToPlaceholder`、`CfUpdatePlaceholder`、`CfRevertPlaceholder`、`CfGetPlaceholderInfo`、`CfGetSyncRootInfoByPath`、`CfGetPlatformInfo`、`CfHydratePlaceholder`、`CfDehydratePlaceholder`、`CfSetPinState`、`CfSetInSyncState`、`CfExecute`、`CfReportProviderProgress`。
  - 这些 API 的最小支持版本是 **Windows 10 1709**（Cloud Files API 首发）；
  - `CF_CONNECT_FLAG_BLOCK_SELF_IMPLICIT_HYDRATION` 是 1803 才有的（Qsync 未使用）。
- 运行时会再判断一次：`qcSupportCloudFiles` = `CfGetPlatformInfo()` 成功 **且** 平台版本 ≥ `0x4563`(=17763)：
  ```
  0x100108e6  call cldapi!CfGetPlatformInfo
  0x100108ec  test eax,eax ; js → false
  0x100108f0  cmp dword ptr [ebp-0x10], 0x4563    ; 17763 = Windows 10 1809
  0x100108ff  cmovae eax, ecx (1)
  ```
- 目录内的 `cldapi.dll` 是**正版 Microsoft x64 系统 DLL**（版本 10.0.22621.2506，CompanyName=Microsoft，InternalName=cldapi.dll，51 个导出），与 32 位进程不匹配；32 位的 `QsyncCloudFile.dll` 实际应由 `SysWOW64\cldapi.dll` 满足导入（此目录里的 x64 副本更像是给 x64 的 `QsyncExt.dll`/系统用的，或安装/Wine 环境带入的副本）。**注意：若把 x64 `cldapi.dll` 放在 x86 进程的搜索路径首位，会导致 `QsyncCloudFile.dll` 加载失败（架构不符）**。

---

## 8. 32/64 位与进程模型、命名管道

### 8.1 分工确认

| 模块 | 机器 | 角色 |
|---|---|---|
| `Qsync.exe` | `0x14c` x86 (Qt5 GUI) | UI + 云账号 API |
| `QsyncLib.dll` | x86 | 会话/同步调度、`CloudFileMan`（占位符业务逻辑） |
| `QFileSync.dll` | x86 | `QFile*` 远端文件抽象 + `CreateCloudFile` |
| `QsyncCloudFile.dll` | x86 | 唯一直接调用 cldapi 的占位符层 |
| `QsyncExt.dll` | `0x8664` x64 | Explorer Shell 扩展：图标覆盖 + 缩略图（COM in-proc） |
| `cldapi.dll`(目录内副本) | x64 | 系统 Cloud Filter API（10.0.22621.2506） |

`QsyncExt.dll` 的类型信息与注册证据：

```
.?AUIShellExtInit@@                        ; IShellExtInit
.?AUIShellIconOverlayIdentifier@@          ; IShellIconOverlayIdentifier
.?AUIThumbnailProvider@@                   ; IThumbnailProvider
.?AVCQsyncShellExt@@ / .?AVThumbnailProvider@Thumbnail@@
CLSID\{679f85cb-0220-4080-b29b-5540cc05aab6}
ForceRemove {17affcaf-2e65-4b1b-98a1-a7b3b4d8ad36} = s 'QsyncShellExt Class'
SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\ShellIconOverlayIdentifiers
Software\Classes\CLSID\{DB2717F9-CAD3-4516-9BB5-2A93C2D4AAB9}\LocalServer32
[Loader] DllGetClassObject enter clsid=%s thumbnailClsid=%d ppv=%p
OverlayIcon / Qsync1Verb..Qsync4Verb
```

注意 `{DB2717F9-CAD3-4516-9BB5-2A93C2D4AAB9}` 与 §2.2 中 x86 侧写进 `SyncRootManager\<id>\ThumbnailProvider` 的 CLSID **完全相同** —— 闭环确认：
**x86 侧注册“同步根的缩略图提供者 CLSID”，x64 的 `QsyncExt.dll` 提供该 COM 类，由 64 位 `explorer.exe` 加载。**

### 8.2 进程间通信（命名管道 / 共享内存）

字符串分布：

```
QsyncLib.dll (x86) : \\.\Pipe\QNAPQsyncCache
QsyncExt.dll (x64) : \\.\Pipe\QNAPQsyncCache
                     \\.\Pipe\QNAPQsyncCacheCommand
                     \\.\Pipe\QsyncExtCOMCache
                     QNAPQsyncCacheMutex
```

导入表印证了方向：

```
QsyncLib.dll  KERNEL32.dll : CreateNamedPipeW, ConnectNamedPipe, PeekNamedPipe,
                             DisconnectNamedPipe, CreateFileMappingW, ReadFile/WriteFile
QsyncExt.dll  KERNEL32.dll : CreateFileW, WaitNamedPipeW, TransactNamedPipe,
                             GetNamedPipeHandleStateW, SetNamedPipeHandleState,
                             DisconnectNamedPipe, ReadFile/WriteFile, CoCreateInstance, CoCreateGuid
```

即：**x86 客户端进程（Qsync.exe/QsyncLib）是 `\\.\Pipe\QNAPQsyncCache` 的命名管道服务端**（`CreateNamedPipeW`/`ConnectNamedPipe`/`PeekNamedPipe` + `CreateFileMappingW` 共享内存），**x64 的 Shell 扩展（`QsyncExt.dll`）是客户端**（`WaitNamedPipeW`/`TransactNamedPipe`/`SetNamedPipeHandleStateW`），用于查询占位符/图标/缩略图状态；`\\.\Pipe\QsyncExtCOMCache` 与 `\\.\Pipe\QNAPQsyncCacheCommand` 只在 `QsyncExt.dll` 里出现，因此其归属方向（谁建谁连）**未确认**。三者共用一个互斥体 `QNAPQsyncCacheMutex` 串行化访问。

---

## 9. 面向 Linux/FUSE 等价实现的语义映射

| Windows/cldapi 概念 | Qsync 的实际用法 | Linux/FUSE 等价 |
|---|---|---|
| sync root（`CfRegisterSyncRoot` + WinRT info） | 由 `StorageProviderSyncRootManager.Register` 注册；`Id = "QNAPQsyncCloudProvider!<SID>!<session>"`；ProviderName 固定 `QNAPQsyncCloudProvider` | 挂载点 + 一个配置/元数据 DB；id 仅需唯一稳定（provider + 用户 + 根路径 hash） |
| placeholder（`CfCreatePlaceholders`） | 只写元数据：RelativeFileName、FileSize、3 个 FILETIME、`FileIdentity`(UTF-16 串，含 NUL 的字节长度)、Flags(=2 之类) | 一个 inode + 扩展属性：远端路径/ID、大小、mtime/ctime/atime、pin state；文件内容存空（size 报真实值） |
| `FileIdentity` | UTF-16 字符串（很可能是远端/相对路径），回调里直接当路径用 | xattr `user.qsync.identity`（建议存 NAS 路径或 file id），fetch 时用它定位远端对象 |
| `CF_CALLBACK_TYPE_FETCH_DATA` | 打开/读取未水合文件时触发；`VolumeDosName+NormalizedPath` 记日志 | FUSE `read()`/`open()` 时发现数据不在本地 → 触发拉取 |
| `CF_CALLBACK_PARAMETERS.FetchData` | offset + length，**length 上限 128 KiB** | FUSE read(offset, size)：按 128 KiB 分片下载并回填 cache |
| `CANCEL_FETCH_DATA` | 用户取消/60s 超时 | 检测中断/关闭 → 取消后台分片任务 |
| `CfExecute(TRANSFER_DATA)` + TransferKey | 下载完成后把分片写回占位符；`CfReportProviderProgress` 报进度 | 直接把下载的数据写入本地 cache 文件/内存，更新 inode 的 present-range 位图 |
| pin state | `UNSPECIFIED=0/PINNED=1/UNPINNED=2/EXCLUDED=3/INHERIT=4`；空间节省=UNPINNED+Dehydrate | xattr `user.qsync.pin`（0..4 同值），并在 icache/evict 逻辑里使用 |
| `CfDehydratePlaceholder` | 主动截断本地内容只留元数据（unpin 后） | 释放本地块（`fallocate(PUNCH_HOLE)` / 删除缓存文件），保留 inode 与元数据 |
| `CfHydratePlaceholder` | 显式水合（用户右键/预取） | 显式 `ioctl`/xattr 触发一次后台 fetch |
| `CfSetInSyncState` | 1 == IN_SYNC（脱水后置位） | 单独 xattr/标志位，用于 UI/冲突判断 |
| 属性位 `FILE_ATTRIBUTE_PINNED(0x80000)` | 与 pin state 一起维护 | 可用 xattr 同步，便于文件管理器显示 |
| Shell 扩展（x64 COM） | 图标覆盖 + 缩略图，经命名管道问 x86 客户端 | Linux 用 GVfs/Nautilus 扩展或 FUSE 侧提供缩略图/emblem（纯可选，不影响核心状态机） |

关键的可移植“状态机”抽象（与 Windows 细节无关）：

```
state = { absent(仅元数据) | present(数据本地) }
pin   = UNSPECIFIED | PINNED | UNPINNED | EXCLUDED
insync= IN_SYNC | NOT_IN_SYNC

create(nas_path, size, times, identity):  state=absent, pin=UNPINNED(空间节省) 或 PINNED
hydrate(range):  fetch(range ∩ 128KiB 网格) → state=present(部分) → 全 range 覆盖后 present
dehydrate():     要求 pin!=PINNED → 丢弃本地数据 → state=absent, insync=IN_SYNC
set_pin(PINNED): 平台不得脱水（需要 provider 保证 pin 语义，脱水请求要拒绝）
set_pin(EXCLUDED, 备份/不回传路径): 永不下发下载
free_up_space(): 按 session 设置遍历 state=present 且 pin!=PINNED 的文件 → dehydrate
```

---

## 10. 未确认 / 存疑项（明确标注）

1. **同步根 id 第 3 段的确切文本**：只确认它是 `CQsyncSession::RegisterSyncRoot` 传入的 session 串（日志 `session=%s`），未反查到其内容（可能是 NAS 名+用户、或 GUID）。第 1 段 `QNAPQsyncCloudProvider` 与第 2 段 SID 已确认。
2. **水合时 WFM CGI 的具体 `func=` 名**：调用链为 `CloudFileCopy → QBackCloudFileCopy → (QsyncSync/QFileSync) → QsyncAPI(WFM*)`；既有资料（TOOLKIT）已确认存在 `/cgi-bin/qsync/qsyncsrv.cgi` 与旧 `utilRequest.cgi` 两套命名空间，但本次未逐字节定位到水合请求的 func 参数。
3. **`FileIdentity` 的内容是 NAS 路径还是本地相对路径**：仅确认它是 UTF-16 串、长度含 NUL、在回调中被当路径使用。
4. **`CF_PLACEHOLDER_CREATE_INFO` 每个字段的精确偏移**：常量（`Flags` 中 `FILE_ATTRIBUTE_PINNED` 的剥离、`FileIdentityLength=2*(len+1)`、`FileSize` 清零分支）已确认；整套字段到 `[edi+…]` 描述结构的映射未逐字段穷举。
5. **`QsyncLib` 侧 type=1 处理函数 `0x10009790` 的具体语义**（推测为 VALIDATE_DATA/FETCH_PLACEHOLDERS 类）未确认；cldapi 回调表里并没有注册 type=1，因此它可能只在内部被复用。
6. `qcExecuteAction` 的另外 3 个跳表分支（操作类型 1/2/3，其中类型 1 用 `Type=5`、参数布局 0x18）对应的具体 `CF_OPERATION_TYPE` 语义未逐一确认；本文只确认下载回写路径（类型 0 ⇒ `CF_OPERATION_TYPE_TRANSFER_DATA`）。

---

## 11. 复现用工具（临时脚本目录）

本次分析新增了脚本目录（未修改任何既有文件）：

```
qsync-analysis/od-work/qdis.py    # PE + capstone 基础反汇编，IAT/导出/字符串注解
qsync-analysis/od-work/qx.py      # 全 .text 线性反汇编 + 函数归属（funcs/dis/calls/xref）
qsync-analysis/od-work/qcalls.py  # 递归收集导出函数的调用序列（含 tail-call）
qsync-analysis/od-work/qpaths.py  # 导出 → Cf*/文件 API 的调用路径
qsync-analysis/od-work/cf.py      # 按函数列出某 DLL 的导入调用点
qsync-analysis/od-work/callers.py # 按 e8 rel32 扫描指定 VA 的调用者
qsync-analysis/od-work/rng.py     # 任意 VA 范围的反汇编（含字符串/IAT 注解）
qsync-analysis/od-work/fseq.py    # 指定导出名的导入调用序列
```

外部文档引用：

- [CF_PIN_STATE (cfapi.h)](https://learn.microsoft.com/en-us/windows/win32/api/cfapi/ne-cfapi-cf_pin_state)
- [CF_CALLBACK_TYPE (cfapi.h)](https://learn.microsoft.com/en-us/windows/win32/api/cfapi/ne-cfapi-cf_callback_type)
- [CF_CALLBACK_INFO (cfapi.h)](https://learn.microsoft.com/en-us/windows/win32/api/cfapi/ns-cfapi-cf_callback_info)
- [CF_CALLBACK_PARAMETERS (cfapi.h)](https://learn.microsoft.com/en-us/windows/win32/api/cfapi/ns-cfapi-cf_callback_parameters)
- [CF_CONNECT_FLAGS (cfapi.h)](https://learn.microsoft.com/en-us/windows/win32/api/cfapi/ne-cfapi-cf_connect_flags)
- [CF_OPERATION_TYPE (cfapi.h)](https://learn.microsoft.com/en-us/windows/win32/api/cfapi/ne-cfapi-cf_operation_type)
- [CF_PLACEHOLDER_CREATE_INFO (cfapi.h)](https://learn.microsoft.com/en-us/windows/win32/api/cfapi/ns-cfapi-cf_placeholder_create_info)
