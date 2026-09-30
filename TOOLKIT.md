# Qsync 逆向分析工具箱（共享）

## 工作目录
`/home/aaaa/.wine/drive_c/Program Files (x86)/QNAP/Qsync`（= session workspace）

## 已准备好的资产
- `qsync-analysis/.venv/bin/python` —— 已装 `pefile` + `capstone`
- `qsync-analysis/out/pe_dump.json` —— 全部模块的导出/导入表（JSON）
- `qsync-analysis/out/str_<模块名>.txt` —— 每个二进制去重后的 ASCII+UTF16 字符串（每行一条，已过滤 base64/SVG）
- `qsync-analysis/out/func_inventory.txt` —— 全部 `func=` 端点（123 个）及出现模块
- `qsync-analysis/out/url_inventory.txt` —— 全部 URL 模板（431 条）
- `qsync-analysis/strdump.py <文件> [正则...]` —— 打印带文件偏移的字符串
- `qsync-analysis/xref.py <正则...>` —— 跨模块字符串交叉引用（UTF-16 感知）

## 关键事实（Lead 已确认，勿重复推翻）
- 目标版本：Qsync 6.1.0.0831 Windows（PE 构建时间 2026-08-31），Qt5 + MSVC 原生，非 .NET。
- 模块架构：
  - `Qsync.exe` (x86, Qt5 GUI) —— UI + QID 云账号 API (`CCloudHttpService_V1/V2`, `DCSAuthToken`) + `QCloudHttp`
  - `QsyncLib.dll` (x86) —— 会话/连接/同步调度层，含 `CloudFileMan::*`
  - `QsyncSync.dll` (x86) —— `QBack*` 备份/版本化引擎，依赖 `QFileSync.dll` + `RdiffDll.dll`
  - `QFileSync.dll` (x86) —— `QFile*` 远端文件抽象（类 POSIX over WFM CGI）
  - `QsyncAPI.dll` (x86) —— `WFM*` 底层 WFM/qsyncsrv CGI 客户端
  - `QsyncCloudFile.dll` (x86) —— on-demand 占位符层，直接 `LoadLibrary("cldapi.dll")` 调 `Cf*`
  - `QsyncExt.dll` (x64) —— Explorer 外壳扩展（图标覆盖、缩略图 COM）
  - `QsyncSvc.exe` (x64) —— VSS 卷影服务（`\\.\pipe\QsyncServicePipe`），与同步无关
  - `RdiffDll.dll` —— rsync 滚动校验 delta（librsync 风格）
- 命名管道：`\\.\Pipe\QNAPQsyncCache` / `\\.\Pipe\QNAPQsyncCacheCommand` / `\\.\Pipe\QsyncExtCOMCache`
- NAS 端有两套 CGI 命名空间（新的 `/cgi-bin/qsync/qsyncsrv.cgi`，旧的 `/cgi-bin/filemanager/utilRequest.cgi`），代码内二选一；`%ls` 前缀位对应 QTS5 的 `/qsync/cgi-bin/...` 形态。

## 硬性要求
- **所有结论必须有证据**：给出模块名 + 文件偏移（如 `QsyncAPI.dll@0x000ea788`）或导出名 + 字符串原文。没有证据就明确写"未确认"。
- **不要修改其他人负责的输出文件**。
- 不要运行 Qsync 程序本身，不要联网抓包（本机无 NAS 凭据）。
- 写文件时避免把超长 base64/SVG 内容写进文档。
