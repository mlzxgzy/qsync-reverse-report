# 08 · Linux 三方客户端实现建议

> 目标：在 Linux 上实现一个支持 **on-demand** 的 Qsync 兼容客户端。
> 本文基于 01–10 篇的逆向结论，给出架构选型、模块划分、实现顺序与验证计划。

---

## 8.0 可行性结论

| 问题 | 结论 |
|---|---|
| 协议是否可复刻？ | ✅ **可以**。全部是标准 HTTP/HTTPS + 已知参数；无私有加密通道（除共享文件夹的 `auth_data` AES） |
| 是否需要逆向服务端？ | ❌ 不需要。端点与参数已全部还原（04 篇，322 条） |
| on-demand 是否需要服务端支持？ | ❌ **不需要**（05 篇已证：服务端零 on-demand 端点） |
| 是否有服务端鉴权硬门槛？ | ⚠️ 普通用户主目录上传下载只需 `sid`；**共享文件夹**需要 `auth_data`+`iv` 的 AES（未完整还原，见 8.6 风险） |
| 是否需要 TLS 客户端证书？ | ❓ 安装目录有 `Cert/cert.pem` + `key.pem`，用途未确认 —— 建议先按普通 HTTPS 试 |
| 是否要实现局域网 PC↔PC 直连？ | ❌ **不需要**。全部功能都能通过 NAS 完成；LAN Sync 只是加速（见 03 篇 §3.10）|

---

## 8.1 推荐总体架构

```
┌──────────────────────────────────────────────────────────────┐
│  qsync-fuse  (FUSE 进程，实现 on-demand)                      │
│    · 目录树来自元数据缓存                                       │
│    · open/read 未水合文件 → 通知 daemon 下载                    │
│    · 脱水：定时/阈值 → 删除本地内容，保留占位符元数据             │
└───────────────────────┬──────────────────────────────────────┘
                        │ (unix socket / D-Bus)
┌───────────────────────▼──────────────────────────────────────┐
│  qsyncd  (同步守护进程)                                        │
│  ┌────────────┬────────────┬────────────┬─────────────────┐  │
│  │ AuthMgr    │ Poller     │ TransferQ  │ StateStore      │  │
│  │ 登录/续期   │ 日志轮询    │ 上传/下载   │ SQLite + 配置   │  │
│  └────────────┴────────────┴────────────┴─────────────────┘  │
│  ┌──────────────────────────┬───────────────────────────────┐ │
│  │ Watcher (inotify)        │ DeltaEngine (rsync 兼容)       │ │
│  └──────────────────────────┴───────────────────────────────┘ │
└───────────────────────┬──────────────────────────────────────┘
                        │ HTTPS
┌───────────────────────▼──────────────────────────────────────┐
│  QNAP NAS: /cgi-bin/qsync/qsyncsrv.cgi  (fallback: utilRequest.cgi)│
└──────────────────────────────────────────────────────────────┘
```

**语言建议**：Go 或 Rust。
- Go：`net/http` + `bazil.org/fuse` 或 `hanwen/go-fuse`；单二进制；并发模型简单。
- Rust：`reqwest` + `fuser`；性能与内存更优；错误处理更严格。

---

## 8.2 模块实现顺序（建议里程碑）

### M1 —— 会话与元数据（1–2 周）
1. `authLogin.cgi` POST → 解析 XML 拿 `authSid`（02 篇 2.2 的字段表）
2. `qsyncsrv_login.cgi` → 拿 `q_token`，持久化
3. `qsyncPrepare.cgi?user=` → NAS UID，写入连接配置
4. `stat` / `get_list` / `get_tree` → 目录列举
5. **验收**：能列出 NAS 上指定文件夹的全部文件与属性

### M2 —— 双向传输（2–3 周）
1. 下载：`func=download` + `Range: bytes=` 分段、断点续传
2. 上传（小）：`func=upload_and_move`
3. 上传（大）：`start_chunked_upload` → `chunked_upload`(offset) → `get_chunked_upload_status`
4. `stat&settime=1&mtime=` 对齐时间戳
5. **验收**：能完整下载/上传大文件并在中断后续传

### M3 —— 变更发现与同步循环（2–3 周）
1. `qbox_get_max_log` 轮询
2. `qbox_get_sync_log(lower, number)` 拉事件
3. `qbox_query_notify` / `qbox_get_device_config_list`（config / global notify）
4. 三游标持久化（原子写）
5. `qbox_write_log` 上报本地上行变更（关键！）
6. inotify 监听本地目录（对应 `ReadDirectoryChangesW`）
7. 三方对比 → 动作队列 → 执行
8. **验收**：两端互改能同步；断线重连后不漏事件

### M4 —— On-demand（FUSE）（3–4 周）
1. 元数据挂载（M1 的缓存）
2. 占位符状态机（`placeholder` / `hydrated` + pin 状态）
3. `open`/`read` 触发水合
4. 脱水（定时 + 磁盘阈值）
5. **验收**：`ls -l` 显示全部文件大小，但磁盘只占已下载的部分；`cat` 未下载文件能自动拉取

### M5 —— 增量传输 / delta（可选优化，2 周）
> 格式已完全还原（06 篇），可直接用 librsync，**块 1 MiB + 强校验 16B MD4**。
> 注意两个方向不对称：上传增量走 `gen_sig → get_sig → rdiff_delta → 上传 delta → commit`；
> 下载增量必须先 `rdiff_sign` 本地旧文件并**上传签名**，再 `gen_delta → get_delta → rdiff_patch`。
1. 接入 librsync（显式设置 block_len=1MiB、strong_sum_len=16）
2. 先做**上传增量**（收益最大）
3. 再做**下载增量**
4. **验收**：改大文件末尾几个字节后，实际传输字节数远小于文件大小

### M6 —— 健壮性（持续）
冲突处理、特殊字符、大小写、智能删除保护、重试、限速、代理、选择性同步。

---

## 8.3 变更发现协议的正确实现（最容易出错的部分）

```
state: { cfg_cursor, notify_cursor, global_cursor }   # 三个 int64

loop every T:
    maxlog = GET qbox_get_max_log(sid)
    if maxlog < last_maxlog:            # 服务端日志被截断/重置
        full_scan(); cursors = 0; last_maxlog = maxlog; continue
    if maxlog > cfg_cursor:
        events = GET qbox_get_device_config_list(sid, user, lower=cfg_cursor, upper=maxlog)
        apply_config(events); cfg_cursor = maxlog      # 先处理再提交游标
    if maxlog > notify_cursor:
        while notify_cursor < maxlog:
            batch = GET qbox_get_sync_log(sid, lower=notify_cursor, number=B)
            for e in batch: enqueue_scan(e.path)
            notify_cursor = batch.last_index
            persist(cursors)                            # 每批提交
    if global_notify_changed:
        ev = GET qbox_query_notify(sid, lower=global_cursor, upper=max)
        handle_share_events(ev); global_cursor = max
        persist(cursors)
```

**三条铁律**：
1. **先处理事件、再推进游标**。崩溃时宁可重放，不可丢失。
2. **游标原子持久化**（写临时文件 + `rename()` + `fsync` 父目录）。
3. 遇到 `WFM_QSYNC_LOG_MISSING` 或 `maxlog` 回退 → **游标归零 + 全量重扫**（对应 `PollingThread` 的 `UpdateProcessedLogIndex(0)`）。

**本地上行必须写日志**：本地改文件后除了上传，还要 `func=qbox_write_log&sid=&filepath=&action=%d`，否则其它设备看不到（03 篇 N13）。

---

## 8.4 On-demand 的 FUSE 实现要点

### 状态存储
每个占位符用一个 sidecar 或 xattr：
```
user.qsync.state  = "placeholder" | "hydrated"
user.qsync.pin    = "unspecified" | "pinned" | "unpinned" | "excluded"
user.qsync.fid    = <NAS 文件 ID / path hash>
user.qsync.size   = <真实大小>
```
**注意**：`ls -l` 必须显示真实大小 → `getattr()` 从元数据返回 `st_size`，而实际磁盘占用为 0（稀疏文件）。

### `open()` / `read()` 水合
```c
read(path, offset, size):
    if state(path) == placeholder:
        if not transferring(path):        # 对应 IsProcessingFile 去重
            start_download(path)          # 异步；本线程阻塞等待
        wait_until_hydrated(path, timeout)
        if failed: return -EIO            # 对应 qcSetErrorStatus
    return cached_content(path, offset, size)
```
**关键陷阱**：
- 阻塞期间应用可能已经超时。建议**先返回已经下载的部分**（`offset < downloaded` 时立即返回），而不是整体阻塞。
- 需要处理 `O_RDONLY` 之外的写模式（写操作要求先水合，否则数据会被覆盖丢失）。
- `mmap` 场景（很多程序用 mmap 读）必须保证不会因 SIGBUS 崩溃 → 建议在 `mmap` 前强制完整水合。

### 脱水
```c
dehydrate_candidates():
    for f in all_files:
        if pin(f) in (pinned, excluded): continue
        if is_open(f): continue                       # 对应 CfOpenFileWithOplock 的锁语义
        if is_transferring(f): continue
        if recently_modified(f, 5min): continue
        yield f

# 触发条件（对应 GetCheckFreeUpSpaceMSTime）
if (used_percent(disk) > QSYNC_SETTINGS_SPACE_SAVING_DISK_PERCENTAGE):
    run_dehydrate()
if (now >= scheduled_time):
    run_dehydrate()
```
脱水 = 删除本地内容 + 保留 `st_size`（用 `truncate(path, size)` + 稀疏 + xattr 标记即可）。

### 「关闭空间节省」= 全部水合
对应 `RevertPlaceholderFolder`：把 state 全部置 hydrated 并后台下载。

---

## 8.5 传输层实现细节

| 项 | 做法 |
|---|---|
| HTTP 库 | Go `net/http`（自动 HTTP/2、连接池、代理）；Rust `reqwest` |
| TLS | 默认系统根证书。NAS 自签证书时需 `--insecure` 或导入 CA（对应 `SSL_CTX_load_verify_locations`） |
| 超时 | 参考 `WFM_FORCE_HTTPS_REDIRECT` — 若 HTTP 返回重定向到 HTTPS，自动切换（Qsync 有这个逻辑） |
| 分块上传 | `upload_id` 需持久化以支持续传；每片失败重试整片 |
| 分片大小 | **待测量**（03 篇 3.8）。建议从 4 MiB 起步并按吞吐自适应 |
| 多文件并发 | 建议 2–4 个并发传输（Qsync 有 `SetDownloadEngineList` / `GetDownloadEngineList`，说明也是多引擎） |
| 代理 | 复用 `QSYNC_SETTINGS_PROXY_INFO_*` 语义：支持 HTTP/SOCKS + 自动代理脚本 |
| 时间戳 | 上传后必须 `func=stat&settime=1&mtime=`，否则会被判定为"未同步" |
| 重试 | 指数退避；区分「可重试」（网络）与「不可重试」（权限/路径过长 `WFM_FILE_NAME_TOO_LONG`） |

**一个重要的优化**：如果与 NAS 同网段，Windows 版走 WebSocket（`ws://` + `LANDownloadFile`）。**首版不必实现** —— HTTP 已足够功能完整；后续可加二进制通道提速。

---

## 8.6 已知风险与不确定项

| 风险 | 影响 | 应对 |
|---|---|---|
| **`auth_data` + `iv` 的 AES 方案未完整还原** | 共享文件夹 / 部分 file-level 授权路径无法工作 | ① 先只做用户主目录（不受影响）② 动态抓包对比明文/密文 ③ 反汇编 `QFileGetAuthentication` |
| `Cert/cert.pem` + `key.pem` 用途不明 | 可能是 TLS 客户端证书或载荷签名密钥 | 先按普通 HTTPS；若被拒则调查 |
| 轮询间隔 / 批量大小 / 分片阈值未知 | 性能与实时性调优 | 抓包测量（见 8.7） |
| `q_token` 有效期与续期策略 | 长期运行可能掉线 | 实现 `qsyncsrv_login.cgi` 重登 + QID `refresh_token` 续期 |
| QTS 版本差异（`/qsync/cgi-bin` vs `/cgi-bin`） | 部分 NAS 端点路径不同 | 启动时探测 `qsyncPrepare.cgi`，404 则切换命名空间 |
| 服务端 XML/JSON 响应字段未 100% 枚举 | 解析可能不全 | 用 02/04 篇已还原的字段表；对未知字段宽容忽略 |
| ~~delta 格式未知~~ | ✅ **已解决** | signature/delta 是 **librsync 原生格式**，magic `0x72730136` / `0x72730236`，大端；块 1 MiB、强校验 16B MD4。可直接用 librsync 库（见 06 篇） |
| `X-QNAP-CHECK` 校验和算法未知 | 仅影响云账号（QID）路径；手动填 NAS 地址不受影响 | 抓包对比；或先不做 QID |
| `_WFM_VERSIONING_DELTA_INFO` 两个 64 位量语义未知 | delta 开关判定可能过于保守/激进 | 抓包观察 `versioning_stat_delta` 返回值与实际决策 |

### ✅ 已消除的不确定性（本次专项深挖后）
- **on-demand 是否需要服务端配合** → 不需要（服务端零 on-demand 端点）
- **delta/signature 二进制格式** → librsync 原生，已完整还原
- **QID OAuth 的 client_id/secret 与 flow** → 已提取，主路径是授权码+PKCE+本地回调
- **地址候选优先级** → GatewayIP → LANIP → DDNS → WANIP
- **普通用户主目录的上下传需要什么凭据** → 只需 `sid`

---

## 8.7 验证计划（需要一台真实 NAS）

静态分析已到达极限，以下必须动态确认。**建议在动手写代码前先做这一步**：

### 抓包环境
在 PC 与 NAS 之间做透明代理（`mitmproxy` + 自签 CA，把 CA 装进 Windows 的受信任根），或直接在 NAS 上抓（`tcpdump`）。过滤 `host <nas> and (port 8080 or port 443)`。

### 必测清单
| # | 操作 | 要抓的信息 |
|---|---|---|
| 1 | 首次登录 | `authLogin.cgi` 完整 POST body（重点找 `pwd`/`pass` 的编码形式）、响应 XML 全文 |
| 2 | 登录 Qsync | `qsyncsrv_login.cgi` body 与 `q_token` 返回 |
| 3 | 空闲 5 分钟 | `qbox_get_max_log` 的**请求间隔** |
| 4 | NAS 端改一个文件 | `qbox_get_sync_log` 的 `number` 值、事件 JSON 结构 |
| 5 | 本地改一个文件 | 是否调用 `qbox_write_log`，`action` 取值 |
| 6 | 下载 100 MB 文件 | `Range` 头的分片大小、并发数、`func=download` 的完整 query |
| 7 | 上传 100 MB 文件 | `chunked_upload` 的 `offset` 步进、`upload_root_dir` 取值 |
| 8 | 修改大文件（已存在）| 是否走 `versioning_*` delta，`lockid`/`version_id` 流转 |
| 9 | 开启空间节省模式 | `register/connect sync root`、占位符创建的 FileIdentity |
| 10 | 在 Explorer 里打开未下载文件 | `OnFetchData` 触发的下载请求特征 |
| 11 | 磁盘将满 | 脱水触发的阈值与顺序 |
| 12 | 断网 1 分钟再恢复 | 重连与游标恢复行为 |

### 静态分析的补充手段
- **导出函数符号** 已在 `out/exports_flat.txt`（414 条），可用 Ghidra/IDA 加载后按 `QFile*` / `QBack*` / `WFM*` 分层阅读。
- **本报告未做**：完整反汇编控制流图。若需精确到指令级（如 AES 密钥来源），建议用 Ghidra 做自动分析，配合本报告的字符串与偏移作为入口锚点。
- 光有字符串不足以确定**加密参数**。建议优先用「动态 + 静态对照」而非纯静态。

---

## 8.8 最小可用路径（MVP）

如果目标是尽快跑通，建议按此裁剪：

```
MVP = 单向下载 + on-demand
  1. authLogin.cgi → sid          （不做 QID，直接用 NAS 账号密码）
  2. qsyncsrv_login.cgi → q_token
  3. get_list/get_tree → 目录树
  4. FUSE 挂载，全部文件显示为 placeholder
  5. open/read → func=download（整文件下载，不分片）
  6. 本地改文件 → 跳过（只读模式）
```
**验证标准**：能在 Linux 上 `ls` 出 NAS 全部文件，`cat` 任意文件都能自动拉取。
这已经覆盖了你「Linux 缺 on-demand」这个痛点的 80%。

之后逐步加：上传 → 变更轮询 → 冲突 → delta → 双向。
