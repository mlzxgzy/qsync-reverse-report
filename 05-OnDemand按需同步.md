# 05 · On-Demand（按需同步 / 空间节省模式）

> **这是本报告的核心章节** —— 你的目标是在 Linux 上做出等价能力。好消息先说：

## ⭐ 最重要的一条结论

> **[已确认] 服务端 API 中不存在任何 on-demand 概念。**
>
> 对全部 322 个端点做正则匹配（`hydrat|dehydrat|placeholder|pin|ondemand|cloud_file`），命中数为 **0**。
> 占位符的「已下载 / 未下载 / 固定 / 释放」状态**完全由客户端本地维护**（Windows 上交给 Cloud Files API 的 minifilter + 客户端自己的 SQLite/注册表）。
>
> **推论**：Linux 实现 on-demand **不需要 NAS 端任何配合**，也不需要修改任何协议。你只要
> ① 复用 04 篇的 `stat` / `get_list` / `download` 端点拿元数据与内容，
> ② 在自己的文件系统层（FUSE）里造出「占位符 + 水合/脱水」语义即可。

---

## 5.1 Windows 侧实现全貌

```
Qsync.exe (x86)
 │
 ├─ QsyncLib.dll
 │    └─ CloudFileMan::*  ──运行时 LoadLibrary──►  QsyncCloudFile.dll (x86)
 │                                                    │
 │                                                    ├─ 静态/动态绑定 cldapi.dll
 │                                                    │     CfConnectSyncRoot  ← 注册 2 个回调
 │                                                    │     CfCreatePlaceholders / CfHydratePlaceholder
 │                                                    │     CfDehydratePlaceholder / CfSetPinState / ...
 │                                                    │
 │                                                    └─ WinRT (C++/WinRT 2.0.230511.6)
 │                                                          Windows.Storage.Provider.StorageProviderSyncRootManager
 │                                                          Windows.Storage.Provider.StorageProviderSyncRootInfo
 │                                                          Windows.Storage.Provider.StorageProviderItemProperties
 │                                                          Windows.Storage.StorageFolder / StorageFile
 │
 └─ QFileSync.dll: QFileCreatePlaceholder / QFileUpdatePlaceholderInfo /
                   QFileGetFilePinState[ByPath] / QFileCloudFileCopy
```

**[已确认]** 证据：
```
QsyncCloudFile.dll PDB: C:\Workspace\...\QsyncLib\Windows\QCloudFile\QsyncCloudFile\Release Unicode\QsyncCloudFile.pdb
QsyncCloudFile.dll: "C++/WinRT version:2.0.230511.6"
QsyncCloudFile.dll: "QNAPQsyncCloudProvider"
QsyncCloudFile.dll 导入表: cldapi.dll → CfConnectSyncRoot, CfDisconnectSyncRoot, CfCreatePlaceholders,
    CfConvertToPlaceholder, CfRevertPlaceholder, CfUpdatePlaceholder, CfGetPlaceholderInfo,
    CfHydratePlaceholder, CfDehydratePlaceholder, CfSetPinState, CfSetInSyncState,
    CfGetPlatformInfo, CfGetSyncRootInfoByPath, CfOpenFileWithOplock, CfCloseHandle,
    CfReportProviderProgress, CfExecute
QsyncLib.dll: "CloudFileMan::RegisterSyncRoot(%s)(%s)(%x)"
              "CloudFileMan::ConnectSyncRoot(%s) failed(%x)"
              "CloudFileMan::DisconnectSyncRoot Failed(%x)"
              "CloudFileMan::OnFetchData(%s)"
              "CloudFileMan::OnCancelFetchData(%s)"
              "CQsyncDllManager::OnInitDialog !g_pQsyncCloudFileHelper(%d)(%d)(%d)"
```

### 同步根的注册：走 WinRT，**不用 `CfRegisterSyncRoot`** ★
**[已确认]** 能力探测 `qcSupportCloudFiles` = `CfGetPlatformInfo` 后要求**版本 ≥ `0x4563`（17763 = Windows 10 1809）**。

**[已确认]** `QsyncCloudFile.dll` 的导入表里**没有 `CfRegisterSyncRoot`**。注册通过 WinRT：
`Windows.Storage.Provider.StorageProviderSyncRootManager::Register()`，
配合 `StorageProviderSyncRootInfo`（`Id`、`DisplayName`、`Path`、`IconResource` 等）与
`StorageProviderItemProperties`（向 Explorer 暴露自定义列）。
证据：`Windows.Storage.Provider.StorageProviderSyncRootManager` / `StorageProviderSyncRootInfo` /
`StorageProviderItemProperties` / `StorageProviderItemProperty` / `GetFolderFromPathOnMTA`（路径→`StorageFolder`）；
以及 `%SystemRoot%\system32\shell32.dll,-257`（默认 `IconResource`）。

注册后写入 **`HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\SyncRootManager\<syncRootId>`**，
Qsync 再在该子键下自己补写缩略图提供者：
```
RegSetValueExW(...\SyncRootManager\<syncRootId>, L"ThumbnailProvider", REG_SZ,
               L"{DB2717F9-CAD3-4516-9BB5-2A93C2D4AAB9}")
```
（键路径 `QsyncCloudFile.dll@0x10015318`；写值 `@0x10001cc9`；CLSID 串 `@0x100153a0`）

### 同步根 ID 的构成 **[已确认]**
唯一构造点 `QsyncCloudFile.dll@0x10002b50`：
```
<ProviderName> "!" <用户 SID 字符串> "!" <会话/标识串>
```
- 第 1 段：硬编码 `QNAPQsyncCloudProvider`
  （`CloudFileMan::RegisterSyncRoot` 在 `QsyncLib.dll@0x100092c2` `push 0x105462bc` 传入）
- 第 2 段：当前进程令牌的**用户 SID**（`GetTokenInformation(TokenUser)` → `ConvertSidToStringSidW`）
- 第 3 段：会话层传入的字符串（`CQsyncSession::RegisterSyncRoot` 的 `session` 参数，**具体文本未逐字节确认**）

其他用法：`IsSyncRootRegistered` 用 `CfGetSyncRootInfoByPath` 取标准信息后比较内联的 `QNAPQsyncCloudProvider`；
`EnsureThumbnailProviderRegistered` 用 `"QNAPQsyncCloudProvider" + "!"` 前缀枚举 `SyncRootManager` 子键。

`QsyncLib.dll` 另有字面量 `.syncrootid`。
错误日志：`Could not register the sync root, hr %08x` / `Could not connect to sync root, hr %08x` /
`Could not disconnect sync root, hr %08x` / `Could not unregister the sync root, hr %08x` /
`GetSyncRootInformationForFolder(%s) failed, hr %08x`。

### 回调
**[已确认]** 只实现了 **2 个**回调：
```
OnFetchData       %s callback     ← 用户/程序读取未水合文件时被系统调用 → 触发下载
OnCancelFetchData %s callback     ← 读取被取消 → 中止下载
```
**判据**：`QsyncLib.dll` 里 `CloudFileMan` 类**一共只有 6 个方法**（穷举其全部 `CloudFileMan::*` 字符串）：
```
RegisterSyncRoot / UnregisterSyncRoot / ConnectSyncRoot / DisconnectSyncRoot
OnFetchData / OnCancelFetchData
```
除了这两个 `On*`，没有任何其它 `Cf*` 回调处理器。

**指令级证据** **[已确认]**：`qcConnectSyncRoot`（`QsyncCloudFile.dll@0x1000ffd0`）在堆对象 `+0x28` 处硬编码回调表：
```
[+0x28] type = 0  CF_CALLBACK_TYPE_FETCH_DATA         fn = 0x1000a0e0
[+0x30] type = 2  CF_CALLBACK_TYPE_CANCEL_FETCH_DATA  fn = 0x1000a1e0
[+0x38] type = -1 CF_CALLBACK_TYPE_NONE（结束）
```
随后 `CfConnectSyncRoot(SyncRootPath, &表, CallbackContext, flags=6, &ConnectionKey)`，其中
`flags = 6 = CF_CONNECT_FLAG_REQUIRE_PROCESS_INFO(2) | CF_CONNECT_FLAG_REQUIRE_FULL_FILE_PATH(4)`。

> 一处不一致：`QsyncLib.dll` 的 `CloudFileMan::ConnectSyncRoot` 传给 `qcConnectSyncRoot` 的**处理函数表**
> （`QsyncLib.dll` `.data` `0x1062ad00`）里除了 `type=0 → CloudFileMan::OnFetchData`，
> 还有 `type=1 → 0x10009790`（即 `VALIDATE_DATA`）；但 `QsyncCloudFile.dll` 向 OS 注册的只有 0 和 2。
> 因此 **`VALIDATE_DATA` 处理器在 QsyncLib 侧存在但不会被系统调用**（历史遗留或预留）。

**`OnFetchData` → `CloudFileCopy` 的调用边已由指令级确认** **[已确认]**：
`QsyncLib.dll@0x10009540`（`CloudFileMan::OnFetchData`）在 `QsyncLib.dll@0x1016875f` 处
`call [0x1050869c]`（`QsyncSync.dll!QBackCloudFileCopy`，取数据），随后 `@0x101687e6 call 0x100123a0`
（→ 表 `[+0x5c]` = `qcExecuteAction`，写回占位符）—— 取数据与写回在同一函数体内。

`OnFetchData` 读到的是 `CF_CALLBACK_INFO+0x40` 的 `FileIdentity`，**当作宽字符串**（路径）使用：
```
0x100095f5  mov edx,[edi+0x40]        ; FileIdentity
0x10009619  call 0x10009140           ; wstring::assign
0x1000962b  push 0x10546458           ; "CloudFileMan::OnFetchData(%s)"
```
**[未确认]** `FileIdentity` 里是 NAS 路径还是本地相对路径（只确认它是宽字符串并被当作路径拼接/打印）。

**没有**实现 `VALIDATE_DATA`、`NOTIFY_DELETE`、`NOTIFY_RENAME`、`FETCH_PLACEHOLDERS` 等 —— 说明 Qsync 采用**极简策略**：只做「读时水合」，其余一致性判断全部靠客户端自己的日志轮询（03 篇）。

> 💡 这让 Linux 实现大幅简化：FUSE 只需在 `open()`/`read()` 时判断「未水合 → 触发下载 → 阻塞至完成或返回部分数据」。

---

## 5.2 占位符的创建

**[已确认]** `CfCreatePlaceholders`（批量创建）与 `CfConvertToPlaceholder`（把真实文件就地转成占位符）。
日志：
```
Creating placeholder for %sx                                  QsyncCloudFile.dll@0x00015eac
Failed to create placeholder for %s with %08x                 QsyncCloudFile.dll@0x00015ee8
QsyncSession::CreateUnpinnedFileThread(%s) CreateCloudFile(%s) failed(%d)
QsyncSession::CreateUnpinnedFileThread(%s) CreateCloudFile(%s) QBackOpenFile3(%s) failed(%d)
CQsyncSession::CreateUnpinnedFileThread(%s) CreateCloudFile failed(%d)
```

`CreateCloudFile(path, ...)` 是引擎侧的统一入口，在多个场景被调用：

| 调用点 | 日志证据 | 语义 |
|---|---|---|
| 扫描到 NAS 新增文件（on-demand 模式下） | `CQsyncSession::CreateUnpinnedFileThread` | **创建"未固定"占位符**（不下载内容） |
| 把已有本地文件转占位符 | `ConvertToCloudFile(%s)`（QsyncLib / QFileSync） | 脱水 |
| 备份/恢复期间的排除 | `CQsyncSession::BackupJobDirEnterAction(%s) ConvertToCloudFile(Path=%s)(QCF_PIN_STATE_EXCLUDED)`<br>`CQsyncSession::BackupJobFileStartAction(%s) ConvertToCloudFile(Path=%s)(QCF_PIN_STATE_UNSPECIFIED)` | 备份中禁止脱水（EXCLUDED），备份后恢复 UNSPECIFIED |
| 硬/软链接跳过 | `CQsyncSession::CheckWaitSetPinFile(%s) ConvertToCloudFile(hardlink/softlink) (%s)(%d)` | 链接不转占位符 |
| 错误文件处理 | `CQsyncSession(%s)::ProcessErrorFileInDB ConvertToCloudFile(%s) failed(%d)` | |

**[已确认]** 占位符元数据（FileIdentity 等）由 `QFileUpdatePlaceholderInfo` / `QFileCreatePlaceholder` 维护：
```
QsyncSync.dll: copy_file QFileUpdatePlaceholderInfo Cloud File(%s) Failed(%d)
QsyncSync.dll: copy_file QFileUpdatePlaceholderInfo Cloud File(%s) successfully
QsyncSync.dll: copy_file: SyncFilePinState(%s) SYNC_FILE_PIN_STATE_EXCLUDED
```
（`QsyncSync.dll` 的 `copy_file` 是 C 风格的内部函数名，说明这一层用 C 实现。）

### `CreateCloudFile` 的完整状态机 **[已确认]**
`QFileSync.dll` 的日志串序列就是它的执行顺序（全部来自同一模块字符串表）：
```
CreateCloudFile GetFileAttributesEx FAILED(%s)(%d)               → 先探测本地是否已有实体文件
    ├─ 已存在 → CreateCloudFile qcConvertToPlaceholder FAILED(%s)(%d)(%d)    就地转占位符
    └─ 不存在 → 新建
CreateCloudFile qcUpdatePlaceholderByPath FAILED(%s)(%d)(%d)(%d) → 写元数据（FileIdentity / 大小 / 时间戳）
CreateCloudFile qcSetPinStateByPath FAILED(%s)(%d)               → 设 pin state
CreateCloudFile qcDehydratePlaceholder FAILED(%s)(%x)(%d)        → 立即脱水（只留元数据）★
CreateCloudFile Delete cloud file(%s)(size=%lld)                 → 清理实体文件
CreateCloudFile FAILED(%s)(%d)(%d)(%d)
```
`QFileCreatePlaceholder`（`QFileSync.dll` 导出 19，`@0x1000f8a0`）会先用
`GetTempFileNameW(dir, L"qsync", 0, buf)` 造临时名，再走上面的序列。

> **注意最后一步**：Qsync 新建占位符后会**立即脱水** —— 所以"刚同步下来的文件"在 on-demand 模式下磁盘占用为 0。
> 这是 Linux 实现必须对齐的关键行为（否则用户会发现新文件立刻被下载）。

**[未确认]** `CF_PLACEHOLDER_CREATE_INFO.FileIdentity` 里具体塞了什么（被当作宽字符串路径使用，见 §5.1）。
Linux 端可自定义该字段。

---

## 5.3 Pin 状态（固定/释放）语义

**[已确认]** 客户端自定义的枚举值（与 Windows `CF_PIN_STATE` 一一对应）：

| Qsync 常量 | CF_PIN_STATE | 含义 |
|---|---|---|
| `QCF_PIN_STATE_UNSPECIFIED` | 0 | 未指定（默认，跟随父目录） |
| `QCF_PIN_STATE_PINNED` | 1 | **固定** —— 始终保持已下载，不自动释放 |
| `QCF_PIN_STATE_UNPINNED` | 2 | **释放** —— 允许系统/客户端回收其内容 |
| `QCF_PIN_STATE_EXCLUDED` | 3 | **排除** —— 永不脱水（备份中、符号链接等） |
| （`INHERIT`=4 未出现） | 4 | 继承父目录 |

**[已确认]** 另有 `QCF_IN_SYNC_STATE_IN_SYNC`（对应 `CF_IN_SYNC_STATE_IN_SYNC=1`）与 `NOT_IN_SYNC=0`。

**[已确认]** 对外公开 API（`QsyncLib.dll` 导出）：
```
CQsyncSyncDll::IsCloudFile(LPCWSTR path, QSYNCSYNCDLL_PIN_STATE* pPin, QSYNCSYNCDLL_IN_SYNC_STATE* pInSync)
CQsyncSyncDll::SyncPairUseSpaceSaving(handle)      → 该配对是否启用
CQsyncSyncDll::SupportSpaceSaving()                → 本机/本版本是否支持
CQsyncSyncDll::IsRegisteredSyncRoot(path, int*)
CQsyncSyncDll::RegisterSpaceSavingSyncFolder(path)
CQsyncSyncDll::RevertPlaceholderFolder(path)       → 关闭空间节省：整目录还原为真实文件
CQsyncSyncDll::UpdateSpaceSavingSettingBySharePath(handle, bool*, path, bool, int, bool*)
CQsyncSyncDll::FreeupSpace()                       → 手动触发回收
```
**注意 `QSYNCSYNCDLL_PIN_STATE` / `QSYNCSYNCDLL_IN_SYNC_STATE` 是 Qsync 自己的公开枚举**（在 `Qsync.exe` 与 `QsyncLib.dll` 中都出现），供 UI 与外壳扩展使用。

**[已确认]** `QFileSync.dll` 侧的枚举命名不同：`QCF_PIN_STATE`、`QFILE_FILE_PIN_STATE_UNPINNED`；`QsyncSync.dll` 侧叫 `SYNC_FILE_PIN_STATE_EXCLUDED`。三套别名指同一语义。

---

## 5.4 水合（Hydrate）：用户读取未下载文件时 ★

### 触发链 **[已确认]**（指令级）
```
Explorer / 应用 read 一个未水合占位符
   │   （过滤管理器发现数据缺失，不自己下载）
   ▼
cldapi → QsyncCloudFile.dll@0x1000a0e0   CF_CALLBACK_TYPE_FETCH_DATA
          日志 "OnFetchData %s callback."（%s = VolumeDosName + NormalizedPath）
   ▼
QsyncCloudFile.dll@0x1000a2e0   按 CallbackContext 的 map 分发 type=0
   ▼
QsyncLib.dll@0x10009540         CloudFileMan::OnFetchData   （__stdcall (CF_CALLBACK_INFO*, CF_CALLBACK_PARAMETERS*)）
   │   读 CF_CALLBACK_INFO+0x40 FileIdentity（宽串路径）
   ▼
异步线程（_beginthreadex，任务对象 0x78 字节，完整拷贝 CF_CALLBACK_INFO）
   ▼
QsyncLib.dll@0x10168120 → CQsyncSession::CloudFileCopy
   ├─ QsyncSync.dll!QBackCloudFileCopy   （IAT 0x1050869c）—— 真正从 NAS 取数据
   ├─ qcExecuteAction → CfExecute(CF_OPERATION_INFO.Type = 5 = TRANSFER_DATA)
   │     把 [Offset, Offset+Length) 的数据写回占位符
   └─ qcReportTransferState → CfReportProviderProgress（上报进度）
```

### ★ 关键：水合是**按需区间**拉取，单次上限 128 KiB
**[已确认]** `QsyncLib.dll@0x100096ca` 解析回调参数：
```
0x100096cd  mov eax,[edx+0x08]     ; FetchData.RequiredFileOffset (64 位，+0x08/+0x0c)
0x100096d9  mov ecx,[edx+0x14]     ; FetchData.RequiredLength   (64 位，+0x10/+0x14)
0x100096e5  cmp eax, 0x20000       ; 0x20000 = 131072 = 128 KiB
0x100096ec  mov eax, 0x20000       ; 超过 128 KiB → 截断
```
即：**每一次 FETCH_DATA 只下载 `[RequiredFileOffset, +RequiredLength)`，且长度被截断到 128 KiB。**
写回时用同一组 Offset/Length（`QsyncLib.dll@0x101687c8/0x101687c2` 把 `task+0x60..0x6c` 压栈给 `qcExecuteAction`）。

> 💡 这修正了一个常见误解：不是"打开文件就整文件下载"。读 1 MB 文件的开头，只会拉前面若干个 128 KiB 分片。

### `qcExecuteAction` 内部 **[已确认]**
`QsyncCloudFile.dll@0x100105d0` 是一个 **11 参数、按操作类型做 4 路跳表分派**的 `CfExecute` 包装
（跳表 `@0x100107e4`，键 = `[ebp+0x18]`）。**水合（下载回写）走分支 0**：
```
0x10010687  mov dword ptr [esp+0x58], 0x28   ; sizeof(CF_OPERATION_INFO)，所有分支共用
0x10010698  jmp dword ptr [eax*4 + 0x100107e4]
; 分支 0（CloudFileCopy 走这条）@0x10010751：
0x10010751  mov ecx,[esi+0x24] / eax,[esi+0x20]  ; ConnectionKey ← 已连接同步根对象
0x1001075e  mov [esp+0x6c],ebx / [esp+0x68],edi  ; TransferKey ← CF_CALLBACK_INFO+0x50/+0x54
0x1001076a  mov dword ptr [esp+0x5c], 0          ; ★ Type = 0 = CF_OPERATION_TYPE_TRANSFER_DATA
0x10010772  mov dword ptr [esp+0x30], 0x28       ; CF_OPERATION_PARAMETERS 大小字段
0x1001077a  call 0x100109e0                      ; 取要写回的数据缓冲（参数=下载返回码）
0x10010782  mov [esp+0x3c], eax                  ; params: Buffer
0x10010795  ...                                  ; params: offset/length（≤128 KiB）
0x100107b1  call dword ptr [0x10014290]          ; cldapi.dll!CfExecute(&params, &info)
```
> ⚠️ 早期草稿把这里写成 `Type = 5` —— 那是**另一个分支**（`arg5==1`，`@0x100106ac`，参数布局 0x18）的值，
> 不是水合路径。**水合是 `Type = 0 = CF_OPERATION_TYPE_TRANSFER_DATA`。**
> 另外 3 个分支（类型 1/2/3）的具体 `CF_OPERATION_TYPE` 语义 **[未确认]**。

### 取消 **[已确认]**
`CANCEL_FETCH_DATA` → `QsyncCloudFile.dll@0x1000a1e0` → `QsyncLib.dll` 的 `CloudFileMan::OnCancelFetchData`，
中止该分片下载（用户在 Explorer 取消，或 60 秒超时）。

### ★ 未水合文件上的读/取大小：**透传，不做拦截** **[已确认]**
```
QFileSync.dll@0x10005b70  QFileGetFileSize   → 取连接对象 → [[obj]+0xc] → call [[impl vtbl+0x84]]
QFileSync.dll@0x10005bb0  QFileReadFile      → 同样纯转发，函数体内无任何 Cf*/占位符判断
```
- `QFileGetFileSize` 对"仅占位符"的文件返回**真实大小**（逻辑大小来自
  `CF_PLACEHOLDER_CREATE_INFO.FsMetadata.FileSize`），**不触发下载** —— 这正是 `ls -l` 能显示真实大小的原因。
- `QFileReadFile` 最终落到普通 `ReadFile`，由过滤管理器发现数据缺失 → 触发 §5.1 的 `FETCH_DATA`。
- 需要 pin/in-sync 状态时走显式查询：`QFileGetFilePinState[ByPath]`（`QFileSync.dll@0x1000feb0`/`@0x1000fee0`）
  → `qcGetPlaceholderInfo` → `CF_PLACEHOLDER_STANDARD_INFO` → `ConvertPinState()` 转成 Qsync 自己的枚举
  （`ConvertPinState(QCF_PIN_STATE) UNKNOWN PIN STATE(%d)`）。

### 下载用什么协议？**[强推断]**
静态分析可确认 `QBackCloudFileCopy` 是 `QsyncSync.dll` 的引擎入口，其下层经
`QFileSync.dll → QsyncAPI.dll (WFM*)` 访问 `/cgi-bin/qsync/qsyncsrv.cgi` 或旧
`/cgi-bin/filemanager/utilRequest.cgi`。**具体的 `func=` 名称未在反汇编层直接观测到**
（本机无 NAS 凭据，无法动态验证）。按 03 篇 §3.4，应为带 `Range` 的 `func=download`。

---

## 5.5 脱水（Dehydrate）：空间回收

### 主动脱水的三条路径 **[已确认]**（字符串级证据）

| # | 路径 | 触发者 | 证据 |
|---|---|---|---|
| 1 | **扫描完成后按状态收敛**（主路径） | `CQsyncSession::ScanCompleteAction` | `ScanCompleteAction(%s) qcSetPinState(QCF_PIN_STATE_UNPINNED) failed(%s)(%d)` → `qcDehydratePlaceholder failed(%s)(%d)` → `qcSetInSyncStateByPath` |
| 2 | **按文件标志/类型转换** | `CQsyncSession::SyncFileWithFlag`、`CQWin32Connection::ConvertFileByType`、`QsyncUtils::ConvertToCloudFile` | `SyncFileWithFlag(%s) qcDehydratePlaceholder Skipped(%s)` / `ConvertFileByType(%s) qcDehydratePlaceholder FAILED(%d)(%d)` |
| 3 | **新建占位符时立即脱水** | `CreateCloudFile` | `CreateCloudFile qcDehydratePlaceholder FAILED(%s)(%x)(%d)`（见 §5.2） |

**标准动作序列**：`qcSetPinState(path, UNPINNED=2)` → `qcDehydratePlaceholder(path)` → `qcSetInSyncStateByPath(path, …)`。

### 自动/手动「Free up space」的触发条件 **[已确认]**
（`CQsyncDllManager::GetCheckFreeUpSpaceMSTime` 日志）：

```
TriggerFreeUpSpace Check FREE_UP_SPACE_BY_DISK_SIZE              ← ① 按磁盘占用百分比
TriggerFreeUpSpace Check FREE_UP_SPACE_BY_DISK_SIZE(Trigger)     ←    超阈值 → 触发
TriggerFreeUpSpace Trigger (Day=%d)(diff=%d)                     ← ② 按计划时间
TriggerFreeUpSpace ignored (Day=%d)(diff=%d)                     ←    未到点 → 忽略
Unknown Mode(%d)                                                  ← ③ 手动/其他
CQsyncDllManager::GetCheckFreeUpSpaceMSTime m_bDuringFreeUpSpace(%d)||m_bTriggerFreeUpSpace(%d)
CQsyncDllManager::UpdateFreeUpSpaceSize !m_bDuringFreeUpSpace
CQsyncDllManager::FreeUpSpaceFinished Free up space finished(%s)
CQsyncDllManager::FreeUpSpaceFinished SetTimer(TIMER_CHECK_FREE_UP_SPACE) Next trigger time(%s)
```

对应注册表设置（09 篇）：
```
QSYNC_SETTINGS_SPACE_SAVING_FREE_UP_SPACE           开关
QSYNC_SETTINGS_SPACE_SAVING_FREE_UP_SPACE_MODE      模式（DISK_SIZE / 定时）
QSYNC_SETTINGS_SPACE_SAVING_DISK_PERCENTAGE         磁盘占用阈值 %
QSYNC_SETTINGS_SPACE_SAVING_ENABLE_FREE_UP_SPACE_TIME  定时触发时刻
QSYNC_FOLDERPAIR_USE_SPACE_SAVING                   该配对是否启用
QSYNC_FOLDERPAIR_SPACE_SAVING_SETTING
```

**[已确认]** 执行链：
```
CQsyncSession::AddFreeUpSpaceAction(strPath)(bIsDir)(bDuringRestore)   ← 入队（带去重/跳过判定）
CQsyncSession::AddFreeUpSpaceAction(%s) Skip (...)(bIsSlientRelaunch=%d)(bIsDuplicate=%d)
   ↓
CQsyncSession::FreeUpSpaceThread
   ├─ "Ignore(%s)" / "Retry(%s) error file" / "Retry(%s) error ignore file"
   ├─ "FreeUpSpaceThread delete data from DB(1..4)(%s)"
   ├─ "FreeUpSpaceThread(%s) ConvertFileDataList(%d)"
   └─ qcDehydratePlaceholder("Dehydrating file %s")   ← QsyncCloudFile.dll@0x00015fa0
```

### 手动 vs 自动 **[已确认]**（归纳）
- **手动**：UI「Free Up Space Now」→ `CQsyncSyncDll::FreeupSpace()` → `FreeUpSpaceThread`
  （`m_bDuringFreeUpSpace` 防重入）→ 对每个 session 的候选文件 `SetPinState(UNPINNED)` + `Dehydrate`。
- **自动**：`TIMER_CHECK_FREE_UP_SPACE` 周期检查；
  `FREE_UP_SPACE_BY_DISK_SIZE` 模式按磁盘占用百分比（`QSYNC_SETTINGS_SPACE_SAVING_DISK_PERCENTAGE`）触发；
  `QSYNC_SETTINGS_SPACE_SAVING_ENABLE_FREE_UP_SPACE_TIME` 记录上次执行时间。
- **只对启用了空间节省的 folder pair 生效**（`QSYNC_FOLDERPAIR_USE_SPACE_SAVING` / `SyncPairUseSpaceSaving`）。
- **另有平台侧脱水**（低磁盘 / 空闲超时）：cldapi 的 `NOTIFY_DEHYDRATE` 回调 Qsync **未注册**，
  因此这部分完全交给系统自带的过滤管理器，Qsync 不干预。

**保护规则** **[已确认]**：
- `QCF_PIN_STATE_EXCLUDED` 的文件永不脱水（备份中、硬/软链接）
- 传输中的文件（`IsProcessingFile`）跳过
- `bDuringRestore` 期间跳过
- 失败重试受限（`Retry(...) error file` / `error ignore file`）

---

## 5.6 「空间节省模式」的开关语义

**[已确认]** UI 上有明确的三种文件夹图标，佐证状态机：
```
Res/QsyncFolder.ico
Res/QsyncFolder_space_saving_mode.ico
Res/QsyncFolder_space_saving_mode_win11.ico
Res/QsyncFolder_win11.ico
Res/QsyncShare.ico / QsyncShare_win11.ico
```

**[已确认]** 切换流程（`CQsyncSession`）：
```
启用：RegisterSyncRoot → ConnectSyncRoot → 扫描现有文件 → CreateCloudFile(UNPINNED) 转占位符
      日志: CQsyncSession::ConnectSyncRoot(%s) RegisterSyncRoot Failed
            CQsyncSession::ConnectSyncRoot(%s) ConnectSyncRoot Failed(%d)
            CQsyncSession(%s)::CheckStopAction RegisterSyncRoot failed
            CQsyncSession(%s)::SetValidSession m_bSpaceSavingChange ignore ConnectSyncRoot
禁用：DisconnectSyncRoot → RevertPlaceholderFolder → 全部水合回真实文件
      日志: CQsyncSession::DisonnectSyncRoot(%s) DisconnectSyncRoot Failed(sessionID=%d)(hr=%x)
            CQsyncSession::UnRegisterSyncRoot
            CQsyncSyncDll::RevertPlaceholderFolder(path)
```
`m_bSpaceSavingChange` 标志用于在切换过程中抑制重复的 sync root 操作。

---

### ⚠️ 一个值得注意的部署细节：随包分发的 `cldapi.dll`

**[已确认]** 安装目录里的 `cldapi.dll` **是正版 Microsoft x64 系统 DLL**
（版本 `10.0.22621.2506`，CompanyName=Microsoft，51 个导出），而使用者 `QsyncCloudFile.dll` 是 **x86**。

两种可能，静态分析无法定论：

| 假设 | 说明 |
|---|---|
| A. 该副本对 x86 进程无效 | 若 `cldapi.dll` 属于 Windows **KnownDLLs**（系统 DLL 清单），加载器强制从 `SysWOW64` 解析，忽略应用目录 —— 那么随包的 x64 副本是打包残留（或给 x64 组件用） |
| B. 该副本会导致加载失败 | 若它不是 KnownDLL，则应用目录优先级最高，x86 进程会尝试加载 x64 DLL 而**架构不符失败** |

**已确认的一点**：`QsyncCloudFile.dll` 的 **PE 导入表直接按名字导入 `cldapi.dll`**（不是 `GetProcAddress` 动态解析），所以走的是标准加载器路径。
（它同时导入了 `LoadLibraryW`/`GetProcAddress`，但用于其它目的。）

**对你的意义**：纯 Windows 加载器细节，对 Linux 实现无影响。记录在此是为了解释目录里那个"位数不匹配"的 DLL。

### 进程模型与 IPC 闭环 **[已确认]**
```
Qsync.exe / QsyncLib.dll (x86)  ── 命名管道服务端 ──►  \\.\Pipe\QNAPQsyncCache
   · KERNEL32: CreateNamedPipeW / ConnectNamedPipe / PeekNamedPipe / DisconnectNamedPipe
   · 另有 CreateFileMappingW（共享内存回传大数据，如缩略图）
   · 互斥体 QNAPQsyncCacheMutex 串行化访问
        ▲
        │ 请求-应答
        ▼
QsyncExt.dll (x64, 由 explorer.exe 加载) ── 命名管道客户端 ──►  WaitNamedPipeW / TransactNamedPipe /
                                                              SetNamedPipeHandleStateW
   · 提供: IShellExtInit / IShellIconOverlayIdentifier / IThumbnailProvider
   · CLSID: {17affcaf-...} (图标覆盖类) / {DB2717F9-CAD3-4516-9BB5-2A93C2D4AAB9} (缩略图)
```
**闭环证据**：x86 侧写进 `SyncRootManager\<id>\ThumbnailProvider` 的 CLSID
`{DB2717F9-CAD3-4516-9BB5-2A93C2D4AAB9}` 与 `QsyncExt.dll` 注册的缩略图 COM 类**完全相同**。

`\\.\Pipe\QsyncExtCOMCache` 与 `\\.\Pipe\QNAPQsyncCacheCommand` 只在 `QsyncExt.dll` 中出现，
其归属方向（谁建谁连）**[未确认]**。

---

## 5.7 缩略图/外壳集成（次要但需注意）
**[已确认]** `QsyncCloudFile.dll` 会注册缩略图提供者：
```
EnsureThumbnailProviderRegistered: RegSetValueEx ThumbnailProvider failed for %s, error %ld
RegSetValueEx ThumbnailProvider failed, error %ld
SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Desktop\NameSpace
```
`QsyncExt.dll`（x64，跑在 explorer.exe 内）提供 `Qsync Thumbnail Provider`（CLSID `{DB2717F9-CAD3-4516-9BB5-2A93C2D4AAB9}`）与 4 个图标覆盖（`{17affcaf-…}` 等，见 `Config/Main.ini`）。
**关键**：`QsyncExt` 需要判断某文件是否为占位符 → 通过 `\\.\Pipe\QNAPQsyncCache` 向 x86 进程查询。缩略图日志：`[Thumbnail] Provider::isPlaceholderPath path=%s attrs=0x%08lX placeholder=%s`。

---

## 5.8 Linux 等价设计建议

Windows Cloud Files API 在 Linux 没有对应物。推荐方案（**FUSE + 私有元数据**）：

### 方案 A（推荐）：FUSE 直通 + 稀疏本地缓存
```
挂载点 /mnt/qs
  ├─ 目录树：由 NAS get_list/get_tree 元数据构建（内存缓存 + SQLite 持久化）
  ├─ 每个"未水合"文件：
  │     表现为一个 0 字节或"存根"文件，xattr 或 sidecar 记录：
  │       user.qsync.state = placeholder | hydrated
  │       user.qsync.pin   = unspecified | pinned | unpinned | excluded
  │       user.qsync.size / mtime / fileid
  ├─ open()/read() 时：若 state=placeholder
  │       → 触发 func=download（Range 分段）到 cache/
  │       → 完成后把 cache 内容作为该文件内容返回（或 rename 到目标）
  │       → 更新 state=hydrated
  └─ 定时/阈值触发脱水：删除本地内容，state→placeholder
```
**优点**：完全不依赖内核新特性，可在任何发行版运行；语义与 Windows 版一一对应。
**注意**：
- `read()` 阶段的下载必须支持**阻塞直至可用**，否则应用（如播放器）会读到 0 字节。建议先返回数据到临时文件再 `splice`。
- 需要处理「下载中再次 open」（等价于 `IsProcessingFile` 去重）。
- 脱水前必须检查文件未被打开（等价于 `CfOpenFileWithOplock` 的锁语义），否则会删除正在使用的数据。

### 方案 B：Linux 6.x `fuse` + `FUSE_HAS_IOCTL_DIR` / 或使用 `EROFS`/overlayfs
不推荐——没有现成的"reparse point / 占位符"抽象，overlayfs 的 `metacopy` 是最接近的（`metacopy=on` + 数据文件在 lower 层按需拉取），但需要在 overlay 上再叠一层网络层，复杂度更高。

### 方案 C：借鉴 rclone / OneDrive 客户端的成熟做法
`rclone mount --vfs-cache-mode=full` + 自研 pin 策略，或直接参考 **OneDrive for Linux 的 `onedriver`** 项目（FUSE + 类似占位符模型）。可节省大量边缘 case 处理。

### 与 Windows 版的语义映射表
| Windows (CF_PIN_STATE) | Linux 实现 |
|---|---|
| `UNSPECIFIED` (0) | `user.qsync.pin=unspecified`，跟随目录默认策略 |
| `PINNED` (1) | 不参与脱水扫描；`open` 前可预水合 |
| `UNPINNED` (2) | 参与脱水扫描（按磁盘阈值/定时） |
| `EXCLUDED` (3) | 永不脱水；备份/链接等场景 |
| `IN_SYNC` (1) | 本地内容与 NAS 的 size/mtime/hash 一致 |
| `NOT_IN_SYNC` (0) | 待同步或冲突 |

### 对 Explorer 特定能力的替代
| Windows 能力 | Linux 替代 |
|---|---|
| 图标覆盖（overlay icon） | 无直接等价；可用 sidecar `.qsstate` 或 `ls` 颜色前缀 / 扩展属性展示 |
| 缩略图提供者（ThumbnailProvider） | 可选：为未水合文件生成缩略图需调用 `get_thumb`（NAS 端已有端点） |
| `StorageProviderItemProperties`（Explorer 自定义列） | 无等价；可用 `getfattr` 或自研 CLI |
| 同步根管理器（SyncRootManager） | 无需等价：直接在配置里登记挂载点 |

---

## 5.9 待验证清单（on-demand 专项）

| 项 | 方法 |
|---|---|
| `OnFetchData` 里下载是否用 `get_detail` 或分块 Range | 动态抓包（需 NAS） |
| 水合时的**预读窗口**（是否顺带下载相邻文件） | 动态观察 |
| 脱水是否有「最小文件大小阈值」 | 反汇编 `AddFreeUpSpaceAction` 或动态观察 |
| `CF_PLACEHOLDER_CREATE_INFO.FileIdentity` 内容 | 反汇编 `qcCreatePlaceholder`（子任务已覆盖） |
| `FREE_UP_SPACE_BY_DISK_SIZE` 的默认阈值 | 注册表默认值 + UI 默认 |
| 定时模式的时间格式（`convert_file_time(Failed)(%d)` 提示是某种时间编码） | 反汇编 |
| 现代 vs 兼容注册路径的选择条件（Windows 版本判定） | 反汇编 `qcRegisterSyncRoot` |

---

## 5.10 附：Windows Cloud Files API 语义速查（平台知识，非逆向所得）

在阅读 §5.1–5.7 时需要这些平台常量作对照。以下来自 Microsoft 公开文档（Windows SDK `cfapi.h`），
列在这里是为了让你在读「`qc*` → `Cf*` 映射」时不必另查手册。

### `CF_PIN_STATE`（占位符固定状态）
| 值 | 常量 | 语义 |
|---|---|---|
| 0 | `CF_PIN_STATE_UNSPECIFIED` | 未指定，跟随父目录 |
| 1 | `CF_PIN_STATE_PINNED` | 固定，始终保持内容，不自动释放 |
| 2 | `CF_PIN_STATE_UNPINNED` | 释放，允许系统/提供程序回收内容 |
| 3 | `CF_PIN_STATE_EXCLUDED` | 排除，永不参与水合/脱水 |
| 4 | `CF_PIN_STATE_INHERIT` | 继承父目录（Qsync 未使用） |

### `CF_IN_SYNC_STATE`
| 值 | 常量 | 语义 |
|---|---|---|
| 0 | `CF_IN_SYNC_STATE_NOT_IN_SYNC` | 本地内容与服务端不一致 |
| 1 | `CF_IN_SYNC_STATE_IN_SYNC` | 一致 |

### `CF_CALLBACK_TYPE`（提供程序回调）
| 值 | 常量 | 语义 |
|---|---|---|
| 0 | `CF_CALLBACK_TYPE_FETCH_DATA` | **系统请求水合（Qsync 实现了）** |
| 1 | `CF_CALLBACK_TYPE_VALIDATE_DATA` | 校验数据范围有效 |
| 2 | `CF_CALLBACK_TYPE_CANCEL_FETCH_DATA` | **取消水合（Qsync 实现了）** |
| 3/4 | `FETCH_PLACEHOLDERS` / `CANCEL_FETCH_PLACEHOLDERS` | 批量占位符拉取（Qsync 未实现） |
| 5 | `CF_CALLBACK_TYPE_NOTIFY_DELETE` | 删除通知（Qsync 未实现） |
| 6 | `CF_CALLBACK_TYPE_NOTIFY_RENAME` | 重命名通知（Qsync 未实现） |
| 7 | `NOTIFY_DELETE_COMPLETION` | 删除完成 |
| 8 | `NOTIFY_RENAME_COMPLETION` | 重命名完成 |
| 9 | `NOTIFY_FILE_OPEN_COMPLETION` | 文件打开完成 |
| 10 | `NOTIFY_FILE_CLOSE_COMPLETION` | 文件关闭完成 |
| 11 | `NOTIFY_HARDLINK` | 硬链接建立 |

→ **Qsync 只注册了 0 和 2 两个回调**，一致性完全靠自己的日志轮询（03 篇）。这是它设计上最"偷懒"也最省事的地方。

### 占位符文件属性（Win32 层可见）
| 属性 | 值 | 语义 |
|---|---|---|
| `FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS` | `0x400000` | 读数据时才回拉（典型 on-demand） |
| `FILE_ATTRIBUTE_RECALL_ON_OPEN` | `0x40000` | 打开时即回拉 |
| `FILE_ATTRIBUTE_PINNED` | `0x80000` | 对应 `PIN_STATE_PINNED` |
| `FILE_ATTRIBUTE_UNPINNED` | `0x100000` | 对应 `PIN_STATE_UNPINNED` |
| `FILE_ATTRIBUTE_SPARSE_FILE` | `0x200` | 稀疏 |

**QsyncExt.dll 正是靠 `GetFileAttributesW` 读这些位来判断"是否占位符"**（`[Thumbnail] Provider::isPlaceholderPath path=%s attrs=0x%08lX placeholder=%s`）。

### `CF_PLACEHOLDER_CREATE_INFO` 主要字段
| 字段 | 用途 |
|---|---|
| `RelativeFileName` | 占位符相对路径（相对同步根） |
| `FsMetadata` | 占位符的文件系统元数据（大小、时间、属性） |
| `FileIdentity` | **提供程序私有标识**（任意字节，Qsync 用它记录文件 ID/状态） |
| `FileIdentityLength` | 上者长度 |
| `Flags` | `CF_PLACEHOLDER_CREATE_FLAG_*`（如 `MARK_IN_SYNC`、`DISABLE_ON_DEMAND_POPULATION`） |
| `Result` | 出参：`S_OK` 或失败 HRESULT |

### Linux 侧对应关系（供 8 篇对照）
| CfAPI 概念 | Linux/FUSE 对应 |
|---|---|
| 占位符（placeholder） | 稀疏文件 + xattr 状态位 |
| `CfHydratePlaceholder` / `FETCH_DATA` 回调 | `open()`/`read()` 拦截 → 拉取 |
| `CfDehydratePlaceholder` | 删除本地内容、保留 `st_size` |
| `CfSetPinState` | xattr（不给内核看，纯客户端策略） |
| `CfReportProviderProgress` | 可选：写进度文件供 UI 读取 |
| `CfOpenFileWithOplock`（保证独占） | `flock()` / `fcntl(F_SETLK)` |
| SyncRootManager 注册 | 配置文件中登记挂载点 |
