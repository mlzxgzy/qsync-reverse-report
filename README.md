# QNAP Qsync for Windows 逆向分析（v6.1.0.0831）

> ### ⚠️ 免责声明（摘要，全文见 [DISCLAIMER.md](DISCLAIMER.md)）
>
> **非官方**：与 QNAP Systems, Inc. 无任何关联，未获授权、未受委托、未受资助。
> **无利益**：纯个人兴趣的技术学习，无商业目的、无经济利益、不含广告与付费内容。
> **分析边界**：**仅静态阅读**——未运行该程序、未抓包、未连接任何 NAS、未绕过任何技术保护措施、
> 未修改或再分发任何 QNAP 二进制文件。
> **权利归属**：QNAP / Qsync / myQNAPcloud / QID 等为 QNAP 商标；被分析软件的全部权利归 QNAP 所有。
> 本仓库**不分发**其二进制、安装包或原始字符串转储。
> **通知即删**：若认为内容侵权，请开 Issue 告知，**收到有效通知后立即删除相关内容或整个仓库，不寻求法律对抗**。
>
> 本材料按「现状」提供，无任何担保；请仅对自己拥有或获授权管理的设备使用，并自行承担合规责任。

---

## 分析对象

| 项 | 值 |
|---|---|
| 软件名称 | QNAP Qsync Client for Windows |
| **产品版本** | **6.1.0.0831**（取自 `Qsync.exe` 的 PE VERSIONINFO `FileVersion`） |
| 构建时间 | **2026-08-31 07:06 UTC**（`Qsync.exe` PE `TimeDateStamp`；其余模块 06:50–07:06 UTC） |
| 安装路径 | `C:\Program Files (x86)\QNAP\Qsync` |
| 架构 | **x86 主体**（`Qsync.exe` / `QsyncLib` / `QsyncAPI` / `QFileSync` / `QsyncSync` / `QsyncCloudFile`）<br>**x64 外壳扩展**（`QsyncExt.dll`、`QsyncSvc.exe`） |
| 获取渠道 | 官方 Qsync Client 安装包（作者自行安装的副本） |
| 编译器 | MSVC（非 .NET，无 IL 可反编译） |

### 各模块版本（PE VERSIONINFO）

| 模块 | FileVersion | ProductName | PE 构建时间 (UTC) |
|---|---|---|---|
| `Qsync.exe` | **6.1.0.0831** | QNAP Qsync Client | 2026-08-31 07:06 |
| `QsyncSvc.exe` | 1.0.0.0826 | NetBak Replicator（VSS 服务，**与同步无关**） | 2026-08-31 06:52 |
| `QsyncLib.dll` | *(无 VERSIONINFO)* | — | 2026-08-31 06:57 |
| `QsyncAPI.dll` | 1.0.2.0502 | QsyncAPI | 2026-08-31 06:59 |
| `QFileSync.dll` | 1.0.0.1 | Qsync（Qsync QFile Library） | 2026-08-31 06:55 |
| `QsyncSync.dll` | 1.0.0.1 | Qsync（Qsync sync Library） | 2026-08-31 06:55 |
| `QsyncCloudFile.dll` | *(无 VERSIONINFO)* | — | 2026-08-31 06:50 |
| `QsyncExt.dll` | 1.0.0.49 | QsyncExt Module | 2026-08-31 06:55 |
| `Qfile.dll` | 1.0.2.0502 | Qfile | 2026-08-31 06:59 |
| `QsyncBackupDll.dll` | 1.0.2.0502 | QsyncBackupDll | 2026-08-31 06:59 |
| `QSystemLib.dll` | 1.0.0.0831 | QSystemLib | 2026-08-31 07:01 |
| `QUiLib.dll` | 1.0.0.0831 | QUiLib | 2026-08-31 07:01 |
| `RdiffDll.dll` | *(无 VERSIONINFO)* | — | **2020-05-06**（旧第三方库，librsync 封装） |
| `cloudlinkP2P.dll` | *(无 VERSIONINFO)* | — | —（Go 编译） |

### 随附的第三方组件版本

| 组件 | 版本 |
|---|---|
| Qt5（`Qt5Core` / `Qt5Network` / `Qt5Gui` / `Qt5Widgets`） | 5.15.17 |
| libcurl | 8.21.0 |
| OpenSSL（`libssl-3` / `libcrypto-3`） | 3.5.7 |
| Windows Cloud Files API（`cldapi.dll`，随包副本，x64） | 10.0.22621.2506 |
| C++/WinRT | 2.0.230511.6 |
| TinyXML（命名空间 `WFMXml`）/ jsoncpp / libwebsockets | 静态链接，未暴露版本号 |

## 分析环境

| 项 | 值 |
|---|---|
| 主机系统 | CachyOS Linux（Arch 系），内核 `7.2.8-1-cachyos` x86_64 |
| 兼容层 | **Wine 11.18**（安装前缀 `~/.wine`，故路径呈现为 `C:\Program Files (x86)\...`） |
| 分析工具 | Python 3.14.7、pefile 2024.8.26、capstone 5.0.7；GNU binutils（`strings` / `objdump`） |
| 分析日期 | 2026-09-30 |
| 分析方法 | **纯静态**：PE 结构解析 → 导入/导出表还原 → 字符串提取 → x86 反汇编交叉引用 |
| 未执行的操作 | 未运行程序、未抓包、未连接 NAS、未绕过保护措施（详见 [DISCLAIMER.md](DISCLAIMER.md) §3） |

> 说明：分析对象是 Windows 版客户端；本机使用 Wine 仅为了获得一份**已安装的目录结构**供静态阅读，
> 分析过程**从未启动**其中的任何可执行文件。

---

## 文档索引

| 文档 | 内容 |
|---|---|
| [01-架构与模块.md](01-架构与模块.md) | 模块划分、进程模型、依赖图、传输通道、本地持久化 |
| [02-登录与鉴权.md](02-登录与鉴权.md) | NAS 登录全流程（含 QID 登录、2SV、QToken）、鉴权数据结构 |
| [03-同步引擎与传输.md](03-同步引擎与传输.md) | 变更发现（日志游标）、扫描、上传/下载、冲突处理 |
| [04-API-参考手册.md](04-API-参考手册.md) | 全部 URL 模板与 `func=` 端点、请求参数、响应字段 |
| [05-OnDemand按需同步.md](05-OnDemand按需同步.md) | ★ Windows Cloud Files API 占位符层语义（Linux 移植关键） |
| [06-增量传输与版本化.md](06-增量传输与版本化.md) | rdiff 滚动校验 delta 与 versioning_* 协议 |
| [07-云账号QID与设备发现.md](07-云账号QID与设备发现.md) | QID OAuth、myQNAPcloud 设备发现、地址回退策略 |
| [08-Linux实现建议.md](08-Linux实现建议.md) | 映射到 Linux 的架构建议、里程碑、验证计划 |
| [09-本地状态与配置布局.md](09-本地状态与配置布局.md) | 120 个注册表值 + SQLite 表结构（Linux 配置蓝本） |
| [10-客户端导出与端点映射.md](10-客户端导出与端点映射.md) | 414 个导出函数 → 服务端端点对照 |
| **[11-API规格书.md](11-API规格书.md)** | ★ **开发用规格**：每个端点的请求参数（类型/必填/含义）+ 响应字段（含置信度）+ 错误码 + 自检清单 |
| [DISCLAIMER.md](DISCLAIMER.md) | ⚠️ **免责声明全文**（中英双语）：非官方声明、分析边界、知识产权、无担保、通知即删 |
| **[12-番外-FUSE实现方案.md](12-番外-FUSE实现方案.md)** | ★ **番外**：要做 FUSE 版需要实现哪些功能、CfAPI↔FUSE 差异、8 个致命坑、脱水安全、分阶段计划、测试矩阵 |

### 专项证据（逐条附 `模块@偏移` + 反汇编/字符串原文）

| 文件 | 内容 |
|---|---|
| [cloudapi-evidence.md](cloudapi-evidence.md) | QID / 云账号专项 |
| [delta-evidence.md](delta-evidence.md) | 增量 / 版本化专项（signature & delta 格式完整还原） |
| [ondemand-evidence.md](ondemand-evidence.md) | on-demand 专项（`qc*` → `Cf*` 逐函数映射） |

### 派生数据（机器可读）

| 文件 | 内容 |
|---|---|
| `out/func_inventory.txt` | 123 个 `func=` 端点清单 |
| `out/url_inventory.txt` | 431 条 URL 模板 |
| `out/endpoints_clean.txt` | 322 条去重后的规范化端点 |
| `out/exports_flat.txt` | 414 个导出函数 |
| `out/api_endpoints.json` | **208 条端点的结构化参数规格** |
| `out/parser_fields.json` / `.txt` | 43 个响应解析器的字段表 |
| `out/pe_dump.json` | 所有模块的导出 / 导入表 |
| `out/versions.json` | 各模块 PE 版本信息（本文档头部表格的来源） |

### 分析脚本（可自行复现）

```
extract.py      从二进制批量提取字符串语料（生成 out/str_*.txt）
parsers2.py     按解析器切分 .rdata 字面量簇，还原响应字段表
spec.py         从 URL 模板自动抽取「端点 → 参数(类型)」结构化规格
categorize.py   对 123 个 func= 端点做互斥分类统计
strdump.py      带文件偏移打印字符串
xref.py         跨模块字符串交叉引用（UTF-16 感知）
findrefs.py     搜索字符串的代码引用点
disasm.py / disasm2.py   x86 反汇编辅助
tools/reveal-credentials.sh  从你自己合法获得的副本中提取报告已掩码的客户端凭据
```

## 仓库内容说明（发布相关）

本仓库**只包含分析文本、派生数据与脚本**：

- ✅ 分析文档、图表、脚本、从二进制中提取的**事实性接口信息**（URL 路径、参数名、符号名）
- ✅ 结构化派生数据（`out/*.json` / `out/*.txt`）
- ❌ **不包含** QNAP 的二进制文件、安装包、反编译产物
- ❌ **不包含**从二进制逐条抽取的**原始字符串转储** `out/str_*.txt`（11 MB，且属对原作品的实质性复制）——
  已由 `.gitignore` 排除

### 想自己复现原始字符串转储？

需要你自己**合法获得**一份 Qsync Client 安装包，解压后：

```bash
# 把 extract.py / parsers2.py / spec.py 与 Qsync 的 DLL/EXE 放在同一目录
python3 -m venv .venv && .venv/bin/pip install pefile capstone
.venv/bin/python extract.py       # → out/str_<模块>.txt
.venv/bin/python parsers2.py      # → out/parser_fields.json
.venv/bin/python spec.py          # → out/api_endpoints.json
```

### 报告中已掩码的内容

OAuth `client_secret` 在公开版本中已掩码（避免在公开渠道散布第三方凭据）。
用 `tools/reveal-credentials.sh <你的 Qsync.exe 路径>` 可从**你自己的副本**中提取。

## 实用工具

- [`probe/`](probe/README.md) —— **协议动态验证脚本**（`qs_probe.py`）。
  静态分析无法回答的问题（密码字段名、响应字段、事件结构）用它对自己的 NAS 跑一遍即可确认。
  建议在动手写客户端之前先做这一步。
- [`tools/reveal-credentials.sh`](tools/reveal-credentials.sh) —— 提取报告中掩码的客户端凭据（需你自己的副本）。

---

## 一页速览

**目标程序是原生 x86 Qt5 + MSVC 程序**，不是 .NET，不存在可反编译的 IL。核心逻辑分布在 6 个关键 DLL 中，通过 **5 种传输**通信：① HTTP CGI（libcurl / Qt5Network）② WebSocket 二进制（libwebsockets）③ Windows WinHTTP/WinINet ④ **WebDAV**（自定义 `QBack` 命名空间，保真 Windows 文件时间/属性）⑤ **局域网对等直连**（`QsyncLib` 内嵌 HTTP/WebSocket 服务，同账号 PC 之间不经 NAS 直接传文件）。

**NAS 侧协议本质**：QNAP 的 **WFM（Web File Manager）CGI**。Qsync 在 WFM 之上叠了一层 Qsync 专用 CGI（`qsyncsrv.cgi`），并把「状态同步」建模为**服务端三路递增日志（config log / notify log / global notify log）+ 客户端本地游标**。客户端用 `qbox_get_max_log` 取服务端最新日志号，用 `qbox_query_notify` / `qbox_get_device_config_list` 拉取 `[已处理游标, 最新号]` 区间的变更事件，处理完把游标写进注册表。**文件内容传输不靠日志**：日志只告知「哪个路径变了」，真正的比对与传输由客户端对每个变化路径做 `stat` / `get_list` 后按需上传下载。

**On-demand** 由 `QsyncCloudFile.dll` 直接调用 Windows Cloud Files API（`cldapi.dll` 的 `CfCreatePlaceholders` / `CfConnectSyncRoot` / `CfHydratePlaceholder` / `CfDehydratePlaceholder` / `CfSetPinState`）实现；同步根 ID 为 `QNAPQsyncCloudProvider`。这是 **Windows 专有机制**，Linux 上需要 FUSE + 私有 xattr/元数据文件等价重造（见 05、08 两篇）。

**没有服务端协同的占位符协议**：占位符的「已下载/未下载」状态由客户端本地维护（占位符 FileIdentity + 本地 SQLite/注册表），服务端 API 里**不存在** "dehydrate"/"pin" 概念。这意味着 Linux 实现只需复刻 HTTP API，on-demand 语义可完全自造。

---

## 直接回答三个问题

### ① 登录流程清楚了吗？→ 清楚
`authLogin.cgi`（QTS 账号密码 → `authSid`）→ **二步验证**（如需）→ `qsyncsrv_login.cgi`（→ `q_token`）→
`qsyncsrvPrepare.cgi?user=`（→ NAS UID）→ `qsyncsrvPrepare.cgi?func=activate`（激活 SID）→ `get_list(share_root)` 探活。
完整字段表、错误码分支、QID 登录路径见 **[02 篇](02-登录与鉴权.md)**。
唯一未还原的是**口令的 AES 封装细节**（`auth_data` + `iv`，用于共享文件夹与 file-level 授权；用户主目录不受影响）。

### ② 同步 / 下载流程清楚了吗？→ 清楚
**变更发现**：服务端三路递增日志 + 客户端三游标（`QSYNC_PROCESSED_MAX_*_LOG_INDEX_64`）。
`qbox_get_max_log` → 有增量则 `qbox_get_sync_log(lower, number)` → 事件转成本地扫描任务 → 三方对比（Src/Dest/View）→ 动作队列。
本地改动通过 `qbox_write_log` 上报给 NAS，让其它设备可见。
**下载**：`stat` 预检 → `func=download`（HTTP Range 分片）或局域网 WebSocket `LANDownloadFile` → 写入 CacheFileName → 完成后改名 + `settime=1&mtime=` 对齐。
**上传**：小文件 `upload_and_move`；大文件 `start_chunked_upload` → `chunked_upload(offset)` → 断点续传；大改动走 `versioning_*` delta。
见 **[03 篇](03-同步引擎与传输.md)**（含选择性同步、冲突/特殊字符/大小写等边界处理）。

### ③ 涉及的 API 清楚了吗？→ 清楚（且有开发用规格书）
**[11-API规格书.md](11-API规格书.md)** 按「端点 → 请求参数（名/类型/必填/含义）→ 响应字段（含置信度）→ 错误码」逐个列出，
并给出 8 项开发前自检清单。机器可读版：`out/api_endpoints.json`、`out/parser_fields.json`。

### ③-1 API 规模概览
**123 个 `func=` 端点 + 322 条 URL 模板 + 414 个客户端导出**，全部列出参数与用途，见 **[04 篇](04-API-参考手册.md)** 与 **[10 篇](10-客户端导出与端点映射.md)**。
云账号侧 QID OAuth 的 `client_id`/`client_secret` 已从二进制中提取，见 **[07 篇](07-云账号QID与设备发现.md)**。

### ④ 对 Linux on-demand 的关键结论
服务端**零** on-demand 端点 → 你的 Linux 实现**不需要 NAS 配合**，用 FUSE 自造占位符/水合/脱水语义即可。
架构与里程碑见 **[08 篇](08-Linux实现建议.md)**，Windows 侧语义到 Linux 的映射表见 **[05 篇 §5.8](05-OnDemand按需同步.md)**。
静态分析到极限的部分，用 **[probe/qs_probe.py](probe/README.md)** 对自己的 NAS 跑一遍即可补全。

---

## 发布前检查清单

若你要把本仓库推到 GitHub：

- [x] `out/str_*.txt`（原始字符串转储）已由 `.gitignore` 排除 —— **这是最主要的版权风险来源**
- [x] OAuth `client_secret` 已在文档中掩码（GitHub secret scanning 会拦截明文凭据）
- [x] `.venv/`、`__pycache__/`、`od-work/` 已排除
- [x] 仓库内**不含**任何 `.exe` / `.dll` / 安装包（`.gitignore` 已兜底）
- [x] [DISCLAIMER.md](DISCLAIMER.md) 中英双语，含「通知即删」承诺
- [ ] **建议**：为分析文本选一个许可证（如 CC BY-NC 4.0 或 MIT）。
      注意许可证**只能覆盖你自己的原创部分**，不能覆盖 QNAP 的软件或其商标
- [ ] **建议**：在仓库 Description 里写明「非官方 / Unofficial reverse-engineering notes」，
      进一步降低误认成官方项目的可能
- [ ] **建议**：确认你所在司法辖区对逆向工程的规定；如需，先咨询律师

> 提醒：`out/*.json`、`out/*.txt` 中的接口路径与符号名属于**事实性技术信息**，风险很低；
> 真正需要回避的是**大段复制原作品内容**（原始字符串转储、二进制、反编译产物），本仓库均已排除。

## 证据可信度约定

本报告每条结论标注证据等级：

- **[已确认]** —— 有明确字符串/导出表/导入表/反汇编证据，附 `模块@偏移`
- **[强推断]** —— 多个间接证据一致，但未经反汇编逐条确认
- **[未确认]** —— 有线索但证据不足，明确标出待验证

---

## 修订记录（交叉验证后的修正）

本报告在初稿之后又做了三轮专项深挖（见 `cloudapi-evidence.md` / `delta-evidence.md` / `ondemand-evidence.md`），
下列初期判断已被**纠正**：

| # | 初稿判断 | 修正后 | 出处 |
|---|---|---|---|
| 1 | `grant_type=password` 是 QID 登录路径之一 | ❌ 它属于 `CDCSCloudHttpService`（DCS 打点/问卷），**不是账号站登录**；主路径是授权码+PKCE+本地回调 | [07 篇 §7.3](07-云账号QID与设备发现.md) |
| 2 | 地址优先级「CloudLink 优先，再 LAN/WAN/DDNS」 | 普通模式顺序是 **GatewayIP → LANIP → DDNS → WANIP**；CloudLink 是独立模式，成功后回落 `127.0.0.1:<映射端口>` | [07 篇 §7.6](07-云账号QID与设备发现.md) |
| 3 | 下载增量「客户端不需要上传签名」 | ❌ 需要：客户端先 `rdiff_sign` 本地旧文件并**通过 `versioning_upload_file` 上传签名** | [06 篇 §6.5](06-增量传输与版本化.md) |
| 4 | delta 格式「未确认，需反汇编」 | ✅ **已完全还原**：librsync 原生格式（`0x72730136` / `0x72730236`，大端） | [06 篇 §6.2–6.3](06-增量传输与版本化.md) |
| 5 | 传输只有「两套 HTTP + 一套 WebSocket」 | 实际是 **4 种**：libcurl-CGI、libwebsockets、WinHTTP/WinINet、**WebDAV（`QBack` 命名空间）** | [01 篇 §1.4](01-架构与模块.md) |
| 6 | on-demand 的水合/脱水细节靠推断 | 已由指令级反汇编确认：`qc*`→`Cf*` 全表、仅 2 个 CfAPI 回调、同步根走 WinRT、水合按 **≤128 KiB 区间**拉取 | [05 篇](05-OnDemand按需同步.md) |
| 7 | 水合回写用 `CfExecute(Type=5)` | ❌ 修正为 **`Type = 0 = CF_OPERATION_TYPE_TRANSFER_DATA`**；`Type=5` 属另一个分派分支 | [05 篇 §5.4](05-OnDemand按需同步.md) |
| 9 | WFM 响应是 XML | ❌ 修正为 **JSON 为主（jsoncpp）+ 少数 CGI 用 XML（TinyXML）**，需按首字符嗅探 | [11 篇 §0.5](11-API规格书.md) |
| 8 | 未发现局域网对等直连 | ✅ `QsyncLib` 内嵌 HTTP/WebSocket 服务，同账号 PC 可直连传文件（`func=search_engine`） | [03 篇 §3.10](03-同步引擎与传输.md) |
