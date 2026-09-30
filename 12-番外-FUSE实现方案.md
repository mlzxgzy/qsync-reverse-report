# 12 · 番外：从 Qsync 到 FUSE —— on-demand 客户端实现方案

> 本文把前面 11 篇的逆向结论落到「**我要在 Linux 上做一个 FUSE 版 Qsync 客户端，需要实现哪些功能、怎么做才不容易错**」。
> 只讲设计与施工，不重复协议细节 —— 协议查 [11-API规格书.md](11-API规格书.md)。

---

## §0 一句话结论

> **CfAPI 给了 Qsync 一个「内核替我盯着数据是否缺失」的机制；FUSE 没有。**
> 因此 FUSE 方案的核心不是「怎么挂载」，而是**「在没有内核兜底的前提下，如何保证任何一次 read 都不会返回假数据，任何一次脱水都不会丢数据」**。
> 其余功能（占位符、pin、水合、脱水）都是在这个前提下重新发明的。

**可行性**：✅ 完全可行。服务端零 on-demand 配合需求（[05 篇](05-OnDemand按需同步.md) 已证），协议层只需 `stat` / `get_list` / `download` / `upload_and_move` + 三个日志游标。

---

## §1 根本差异：CfAPI 是「内核回调你」，FUSE 是「你接管内核」

| 维度 | Windows CfAPI（Qsync 用的） | Linux FUSE |
|---|---|---|
| 命名空间归属 | **OS 拥有**，你的文件是 NTFS 上的 real file + reparse point | **你拥有**，`readdir`/`getattr` 全部由你回答 |
| 数据缺失的感知 | 内核 minifilter 发现 reparse point → 回调 `FETCH_DATA` | ❌ **没有等价物**。你必须在 `read()` 里自己判断 |
| 文件「逻辑大小」 | `CF_PLACEHOLDER_CREATE_INFO.FsMetadata.FileSize` → `GetFileSize` 直接返回真实大小 | 你在 `getattr` 里返回 `st_size`，但**文件内容是自己造的** |
| 读未水合数据 | 内核拦截，阻塞并回调 | ⚠️ **内核不会拦**。你返回什么，应用就拿到什么 |
| 独占/一致性 | `CfOpenFileWithOplock` 由系统保证 | 自己用 `flock`/`fcntl` + 打开计数 |
| 脱水后缓存失效 | 系统统一管理 | ⚠️ **必须自己 `inval_inode`**，否则 page cache 里的旧页会造成数据错乱 |
| 与 Explorer/文件管理器集成 | SyncRootManager + COM 扩展（图标/缩略图） | 无；只能靠 xattr / 自研 CLI / `getfattr` |
| pin 状态 | `CfSetPinState` 内核字段 | 自造，存 xattr（内核不参与） |

### 最关键的一条推论

Qsync 的策略是「**只注册 2 个回调**（FETCH_DATA / CANCEL_FETCH_DATA），其余一致性全靠客户端自己的日志轮询」（[05 篇 §5.1](05-OnDemand按需同步.md)）。
**Linux 上连这 2 个回调都没有**，所以要把它做进 FUSE 的 `read()` 路径里 —— 这反而更简单：逻辑集中在一处，不用跨内核/用户态调试。

---

## §2 核心设计决策：占位符在 Linux 上怎么表示

这是整个项目**第一个也是最重要的决策**。四种方案：

| 方案 | 做法 | `ls -l` 正确 | 应用能读 | 风险 |
|---|---|---|---|---|
| **A. 稀疏文件 + xattr 状态**（推荐） | 真实 `st_size` + 内容区为 hole，xattr 记 `placeholder/hydrated` | ✅ | ✅（靠 `read()` 供数） | 必须自己保证 read 不返回假数据 |
| B. 0 字节占位文件 | `st_size=0` | ❌ 显示 0 | ❌ 应用当空文件 | 破坏 `ls`/同步工具/应用 |
| C. 符号链接指向 cache | `st_size` = 链接长度 | ❌ | ⚠️ | `stat` 语义全乱，`open` 行为不一致 |
| D. overlayfs `metacopy` | lower=网络层 | ✅ | ⚠️ | 需要 overlay + 自研 lower 层，复杂度翻倍，权限/rename 语义受限 |

### 推荐方案 A 的具体做法

```
每个占位符文件：
  ① 普通文件，ftruncate(fd, real_size)          ← 逻辑大小正确，磁盘占用≈0（稀疏）
  ② 内容区不写任何数据（保持 hole）
  ③ xattr 记录状态：
       user.qsync.state  = "placeholder" | "hydrated" | "dirty"
       user.qsync.pin    = "unspecified"|"pinned"|"unpinned"|"excluded"
       user.qsync.fid    = "<NAS file id / path hash>"     ← 等价 CfAPI FileIdentity
       user.qsync.vsize  = "<真实大小>"                     ← 冗余一份，避免依赖 st_size
       user.qsync.etag   = "<服务端 mtime+size>"            ← 免 resync 的快速判等
```

**为什么建议用 xattr 而不是 sidecar 文件**：`rename()` 时 sidecar 不会跟着走（会导致状态与文件脱节），而 xattr 在 `rename` 时由内核自动随文件搬运。

**一个关键便利**：✅ **FUSE 挂载点上的 xattr 是"虚拟"的** —— 内核只是把 `getxattr`/`setxattr` 转发给你的进程，
值存在哪里完全由你决定（最省事：直接存进你的 SQLite，键 = 路径或 inode）。
所以**不依赖底层文件系统是否支持 `user_xattr`**，也不受挂载参数影响。
（若你后面改成"先把文件落盘到某目录再 bind-mount"的形态，才需要关心底层 FS 的 xattr 支持。）

> 副作用提醒：xattr 通过 `getfattr`/`setfattr` 对外可见，这正好可以作为 pin 状态的**用户操作接口**（见 §3.2），
> 但也意味着不能让 xattr 成为"必需才能工作"的唯一状态源 —— 建议 xattr 与 SQLite **双写**，以 SQLite 为准。
> 理由：某些工具（rsync、归档程序）复制文件时会丢 xattr，此时若只信 xattr 就会丢失占位符状态。

### ⚠️ 致命陷阱：**不要指望内核用 hole 触发任何东西**

方案 A 有个诱人的错误想法：「文件是稀疏的，读 hole 会出错/会触发回调，我就能在那里水合」。
**不会。** 读 hole 会**静默返回全 0 字节**，应用拿到的就是一堆 0 —— 数据静默损坏，且极难排查。

所以：**水合判断必须在 `read()` 里显式做**，依据是 xattr 状态，不是文件内容。
（这一点跟 CfAPI 完全相反 —— 那里确实是内核在用 reparse point 拦你。别把 Windows 的直觉搬过来。）

---

## §3 必须实现的 FUSE 操作（逐项清单）

### 3.1 必修（缺一个就会出错）

| FUSE 操作 | 必须做什么 | Qsync 对应 | 关键陷阱 |
|---|---|---|---|
| `getattr` | 从**元数据缓存**返回真实 `st_size` / `st_mtime` / 权限；**绝不触发下载** | `func=stat` | 报了真实 size 却不供数 → read 必须自己补齐（见 §7.1） |
| `readdir` | 从元数据缓存返回目录项；必须包含 `.` `..` | `func=get_list` | 分页：`get_list` 有 `limit`/`start`，大目录要翻页或懒加载 |
| `lookup` | 路径存在性判断；返回正确 `st_mode`（目录/文件区分 `isfolder`） | `get_list`/`stat` | 大小写：NAS 可能大小写不敏感，需做大小写归一查找 |
| `open` | 决定是否水合：`O_RDONLY`→按需；`O_WRONLY/O_RDWR`→**必须先完整水合**（否则 read-modify-write 会丢数据） | `func=download` | `O_TRUNC` 要单独处理（见 §7.6） |
| `read` | ★ **水合的唯一入口**：state=placeholder → 拉取所需区间 → 返回真实数据，**返回长度必须等于请求长度**（不足则返回错误，不能短读） | `func=download` + `Range` | 短读会被内核当 EOF 并**零填充缓存整页** → 后续读到 0（§7.1） |
| `write` | 先确保水合 → 写入 → 置 `state=dirty` → 入上传队列 | `upload_and_move` | 写到 hole 上会**隐式**把文件变成非稀疏，状态必须同步更新 |
| `release` | 关闭计数递减；`dirty` 且无其它打开者 → 触发上传 | `IsProcessingFile` 去重 | 不能每个 write 都上传 |
| `flush` | 上传前的对齐点（可选，用于 `close()` 语义） | — | `flush` 可能被调多次 |
| `fsync` | 强制把该文件的上传排到前面并等待完成（可选，建议实现为「尽力」） | — | 不实现会导致编辑器保存后长时间没上云 |
| `create` | 新建文件 → 记为 `dirty`，**不需要先下载**（服务端不存在） | `upload_and_move` | 大小写冲突：NAS 上已有同名的不同大小写文件（§7.5） |
| `mkdir` / `rmdir` | 本地创建/删除 → 入动作队列 → 上报 | `createdir` / `delete` | 删除非空目录要在服务端递归 |
| `unlink` | 记录删除意图 → **上报 `qbox_write_log`** → 从元数据移除 | `delete` + `qbox_write_log` | 不能本地删完就算了（§5.2） |
| `rename` | 本地改名 → 入队列 → 服务端 `rename` | `rename` | **改名到未水合的占位符上**（§7.4） |
| `setattr` | `mtime` 变更要上报；`truncate`/`size` 变更必须先水合（或特殊处理） | `stat&settime=1` | 对 placeholder 做 `truncate` 会把文件"实体化"（§7.6） |
| `statfs` | 返回配额 | `func=qbox_get_quota_info` | 不返回真实配额，同步工具会误判空间不足 |

### 3.2 强烈建议实现

| 操作 | 作用 |
|---|---|
| `getxattr` / `setxattr` / `listxattr` | ★ **pin 状态的用户接口**：`setfattr -n user.qsync.pin -v pinned <file>` 等价于 Windows 的「始终保留在此设备上」；也是 UI/CLI 读状态的通道 |
| `access` | 权限判断；避免应用因 EACCES 提前放弃 |
| `opendir` / `releasedir` | 目录句柄生命周期（用于目录级预读/批量 stat） |
| `lock` / `flock` | 需要支持应用的 `flock`/POSIX 锁；同时是你自己实现「oplock 等价物」的基础（§8） |
| `lseek`（`SEEK_HOLE`/`SEEK_DATA`） | 让文件看起来真的是稀疏的（`cp --sparse`、备份工具会用到）；**注意别把 placeholder 的 hole 暴露成"数据缺失"** |
| `fallocate` / `copy_file_range` | 大文件拷贝/预分配优化；`copy_file_range` 可实现服务端/本地快速复制 |
| `readlink` / `symlink` | Qsync 对硬/软链接有特殊处理（`ConvertToCloudFile(hardlink/softlink)`），建议：**链接不转占位符**，直接实体化 |

### 3.3 可以延后 / 明确不支持

| 操作 | 建议 |
|---|---|
| `mknod` / 设备文件 | 返回 `ENOSYS` |
| `ioctl` | 除通用之外返回 `ENOTTY` |
| `bmap` | 不需要 |
| `poll` | 一般不需要 |
| `link`（硬链接） | 建议返回 `ENOSYS` 或转为「复制」，因为 NAS 侧不一定支持，且 Qsync 自己对硬链接是跳过的 |
| `chown` / `chmod` | 视 NAS 是否有对应能力；最简做法是本地记录、不回传（对应 Qsync 的 `WFMGetConfigACL` / `privilege_ex`） |

---

## §4 状态机（照搬 Qsync 的语义，但存到 xattr）

```
                    ┌──────────────────────────────┐
        getattr     │  placeholder                 │   ← NAS 有、本地无内容
        （不触发）   │  state=placeholder           │      st_size=真实, 内容=hole
                    │  pin=unpinned/pinned/excluded│
                    └───────┬──────────────┬───────┘
                            │ read()       │ write()/truncate()
                            ▼              ▼
                    ┌──────────────────────────────┐
                    │  hydrated                    │   ← 本地内容完整
                    │  state=hydrated              │
                    └───────┬──────────────┬───────┘
             本地写/删除/改名│              │ 脱水（§8）
                            ▼              ▼
                    ┌──────────────┐   （回到 placeholder）
                    │  dirty       │   ← 本地已改，待上传
                    └──────┬───────┘
                           │ 上传成功 + 服务端确认 mtime
                           ▼
                    （hydrated）

  冲突：上传时服务端 mtime 与本地基线不符 → state=conflict → 生成冲突副本
```

**pin 状态映射**（与 Windows 一一对应，[05 篇 §5.3](05-OnDemand按需同步.md)）：

| xattr 值 | 语义 | 对行为的影响 |
|---|---|---|
| `unspecified` | 跟随目录默认 | 参与脱水扫描 |
| `pinned` | 固定 | **不参与脱水**；open 前可主动预水合 |
| `unpinned` | 释放 | 参与脱水扫描（默认值） |
| `excluded` | 排除 | **永不脱水**（备份中、链接、正在传输） |

> 💡 **重要简化**：Windows 上 pin 状态是内核字段（`CfSetPinState`），需要处理"继承/传播"。
> Linux 上没有内核参与，pin 就是**你纯客户端的一条策略**，不需要考虑与内核的一致性 —— 这反而更简单。

---

## §5 同步引擎侧（复用 Qsync 的逻辑）

### 5.1 变更发现：三个游标，一个字都不能改

严格照 [03 篇 §3.1](03-同步引擎与传输.md) 实现：

```python
loop every T:                              # T 需实测（见 08 篇 §8.7）
    maxlog = GET func=qbox_get_max_log&sid
    if maxlog < last_maxlog:               # 服务端日志被截断/重置
        full_scan(); cursors = 0; last = maxlog; continue
    if maxlog > cfg_cursor:
        apply( GET func=qbox_get_device_config_list&lower=cfg_cursor&upper=maxlog )
        cfg_cursor = maxlog
    while notify_cursor < maxlog:
        batch = GET func=qbox_get_sync_log&lower=notify_cursor&number=B
        for e in batch: enqueue_scan(e.filepath)
        notify_cursor = batch.last
        persist(cursors)                   # ★ 每批提交
    if global_changed:
        handle( GET func=qbox_query_notify&lower=&upper= )
        global_cursor = max
        persist(cursors)
```

**三条铁律**（照搬 Qsync 的行为）：
1. **先处理事件，再推进游标** —— 崩溃时宁可重放，不可丢失。
2. **游标原子持久化**（临时文件 + `rename()` + `fsync` 父目录）。
3. `WFM_QSYNC_LOG_MISSING` 或 `max_log` 回退 → **游标归零 + 全量重扫**。

### 5.2 本地上行：FUSE 给了你一个 Qsync 没有的便利

| Windows Qsync | FUSE 实现 |
|---|---|
| `ReadDirectoryChangesW` 三线程流水线（收/解析/派发）来捕获本地改动 | ✅ **不需要**。所有本地改动都经过你的 FUSE 回调（`write`/`create`/`unlink`/`rename`/`setattr`），**直接记入队列即可** |
| 仍需处理"幽灵事件"（大小写重命名、临时文件） | 大幅减少；但 `*.crdownload`、`~$*`、`.goutputstream-*` 等**临时文件过滤仍要做**（对照 Qsync 的 `IsArchiveFilter` / `SyncIgnorePath`） |

**但有一件事绝对不能省**：本地改动必须调用
```
GET func=qbox_write_log&sid=&filepath=<path>&action=<动作码>
```
否则**其它设备永远看不到你的改动**（[11 篇 §5.5](11-API规格书.md)）。
`action` 的枚举值需要你抓包确定一次 —— 这是 [11 篇 §17](11-API规格书.md) 自检清单第 8 项。

### 5.3 三视图（Src/Dest/View）要不要照搬？

Qsync 有 `ScanFileInfo` 表里的 `pSrcPathInfo`/`pDestPathInfo`/`pViewPathInfo` 三套状态（[09 篇](09-本地状态与配置布局.md)）。
**建议简化**：

```
你的模型（两视图足够）：
  local   = 挂载点里的真实状态（xattr state + 内容）
  remote  = 服务端元数据（stat/get_list 的结果 + etag）
  baseline= 上次同步成功时的 {size, mtime, etag}   ← 存在 SQLite
```
判定：
- `local == baseline` 且 `remote != baseline` → **下载**
- `local != baseline` 且 `remote == baseline` → **上传**
- 两者都变 → **冲突**（生成 `<name>.conflict-<device>-<time>` 副本，两边都保留）
- `local` 被删且 `baseline` 存在 → 删除（但要接**智能删除保护**，见下）

保留 Qsync 的这两个保护（都是踩过坑才有的）：
- **智能删除保护**（`SYNC_FOLDERPAIR_SMART_DELETE`）：本地整个目录/大量文件消失时先告警而非直接删云端
- **veto 文件**：`func=qbox_get_veto_files` 返回的黑名单要落地为忽略规则

### 5.4 传输队列要跟 Qsync 对齐分片

**照搬 Qsync 的 128 KiB 水合粒度**（[05 篇 §5.4](05-OnDemand按需同步.md)）：

```python
def read(path, offset, size):
    want = size
    limit = 128 * 1024                       # 对齐 Qsync 的 FETCH_DATA 上限
    # 已有区间直接返回；缺的区间按 128 KiB 分块补齐
    while need_more(offset, size):
        chunk = min(remaining, limit)
        download_range(path, offset, chunk)  # func=download + Range
    return data_or_error(offset, want)       # ★ 长度必须 == want
```
理由：① 与服务端已有的对齐方式一致，少踩坑；② 避免一次 read 触发整文件下载（Qsync 都不这么干）。

---

## §6 架构与并发

### 6.1 推荐：**单进程**（FUSE + 引擎同一进程）

```
┌──────────────────── qsyncd (单进程) ────────────────────┐
│                                                          │
│  FUSE 线程池（多线程挂载，-o max_threads=N）              │
│    getattr/readdir/read/write/... ──┐                    │
│                                      │ 共享              │
│  ┌───────────────────────────────────▼─────────────────┐ │
│  │ MetaCache   （内存 LRU + SQLite 持久化，路径↔属性）  │ │
│  │ StateStore  （xattr 读写 + 本地 DB：baseline/队列）  │ │
│  │ HydrationMgr（区间下载、去重、等待队列、进度）        │ │
│  │ UploadQueue （脏文件、合并、重试）                    │ │
│  │ Poller      （三游标轮询）                            │ │
│  │ Dehydrator  （磁盘阈值/定时；安全检查）               │ │
│  └──────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

**为什么不要拆成两个进程**：FUSE 的 `read()` 是同步阻塞的，跨进程 IPC 会让水合路径变成长链路，调试成本高。单进程 + 线程池足够。
（如果你要用 Go，`go-fuse` 天然多 goroutine，更省事。）

### 6.2 水合阻塞与去重

```python
hydrating = {}                  # path -> Future/CondVar   ← 对应 Qsync 的 IsProcessingFile 去重
def ensure_range(path, off, ln):
    key = path
    with lock:
        if key in hydrating:
            f = hydrating[key]
        else:
            f = hydrating[key] = Future(); f.set_result(None)  # 真正的下载任务已入队
    f.wait(timeout=...)          # ★ 必须有超时
    if failed: raise EIO
```
- **必须有超时**：否则一个卡住的下载会让应用永久挂起（对应 Qsync 的 `CANCEL_FETCH_DATA`/60 秒超时）。
- **取消**：应用关掉文件（`release`）且无人等待时，放弃该下载（对应 `OnCancelFetchData`）。

### 6.3 挂载参数建议（libfuse 3 语义）

```
-o default_permissions        # 让内核做权限检查，减少一次回调
-o attr_timeout=0.5           # 属性缓存时间：太长会看不到远端变更，太短会放大 stat 次数
-o entry_timeout=0.5
-o negative_timeout=0
-o max_read=131072            # 与 128 KiB 分片对齐
-o max_write=131072
-o big_writes                （libfuse3 已默认）
-o writeback_cache           # ⚠️ 用它会显著改变写语义，见 §7.2 —— 建议先不开
-o auto_unmount
-o allow_other               （按需）
```
**`writeback_cache` 的取舍**：开启后内核会聚合写、延迟回写，性能好但**写路径不再立即经过你**，`state=dirty` 的时机变晚，且 `O_TRUNC`/`truncate` 语义更绕。**第一版不要开**。

---

## §7 ★ 八个致命坑（按踩坑代价排序）

### 7.1 短读 = 数据静默损坏（最高危）

FUSE 走 page cache 路径填充页时，若 `read()` 返回的字节数少于请求量，
**内核会把不足部分按 0 处理、并把该页标记为已就绪（uptodate）后缓存下来**。
之后应用再读同一页，会直接从 page cache 拿到 0 —— **你的 `read()` 再也不会被调用**。
结果是"数据静默损坏"：文件看起来读成功了，内容却是零。

✅ 正确做法：
```python
def read(path, size, offset):
    ensure_range(path, offset, size)     # 确保区间完整；失败则抛异常
    data = cached(path, offset, size)
    if len(data) != size:                # ★ 长度必须精确
        raise OSError(errno.EIO)         # 宁可直接失败，绝不短读
    return data
```
（例外：`offset + size > 真实文件末尾` 时，返回实际可用长度是合法的 —— 但仍不要少返回文件内的字节。）

### 7.2 写路径的 read-modify-write

应用对 placeholder 做 `O_RDWR` 打开、写中间 100 字节 → 你只水合了那 100 字节就落盘，
**文件其余部分仍是 hole（全 0）** → 上传后云端文件被清空。

✅ 正确做法：
- `open(O_WRONLY|O_RDWR)` 时**完整水合**（除非 `O_TRUNC`）
- `O_TRUNC` 时**不需要水合**，直接记 `dirty` 并上传新内容
- `truncate(size)` 变大时要注意：**变大部分是 hole，上传时服务端可能不认**（`filesize` 校验），建议上传前先 `fallocate` + 写 0，或改用分块上传

### 7.3 mmap（最容易被忽略）

大量程序用 `mmap` 读文件（编辑器、`grep -r`、播放器）。
FUSE 支持 mmap（缺页走 `readpage` → 你的 `read()`），但：
- 若 `read()` 失败，内核给进程发 **SIGBUS** → 应用崩溃（不是返回 EIO）
- 若文件是稀疏的而你又没在 `read()` 里供数 → 应用 mmap 到 0 页，看到全 0

✅ 建议：**检测到 mmap 时强制完整水合**。
实现上可在 `open` 时观察 `O_` 标志无直接帮助；可行做法是把 `readpage` 之外的风险降下来 —— **最简单可靠的是：对任何 `open()` 都先完整水合**（代价是失去"只读一部分就够"的优化）。
折中：默认按需，但对**小于阈值（如 8 MiB）**的文件直接在 open 时整文件水合；大文件按需 + 文档说明 mmap 大文件可能失败。

### 7.4 改名的两个方向都可能出事

- `rename(A, B)`，**B 是未水合的 placeholder**：内核会先 `unlink(B)` 再链接 A。你必须确保 B 的 metadata 正确移除，且**不要**因为 B 的"内容缺失"而误判。
- `rename(A, A')` **仅大小写不同**：NAS 可能大小写不敏感。Qsync 专门有 `CCaseConflict` / `ProcessCaseRenamePath` 处理"case-only rename ghost"（[03 篇 §3.6](03-同步引擎与传输.md)）。你必须：
  - 检测 NAS 是否大小写不敏感
  - 大小写改名实现为「两阶段」：`A → A.tmp → A'`（否则服务端可能认为是同一个文件而忽略）

### 7.5 冲突与特殊字符

Qsync 踩过的坑，你都要接（[03 篇 §3.6](03-同步引擎与传输.md)）：
- **类型冲突**：同名一文件一目录
- **非法字符**：NAS 侧不接受的名字（`SpecialCharInfo`），Qsync 的做法是改名并记账
- **超长路径**：`WFM_FILE_NAME_TOO_LONG` —— **不可重试**，直接报错跳过
- **删除保护**：本地批量消失时不要直接删云端

### 7.6 `truncate` / `setattr(size)`

对 placeholder 做 `truncate`：
- `ftruncate(fd, 0)` → 等价于"清空并写入"，此时**不该**触发完整水合
- `ftruncate(fd, bigger)` → 会产生 hole；上传时要么补零要么用分块上传
- **绝不要**在 placeholder 上直接 `ftruncate` 而不更新 `user.qsync.vsize`，否则 `getattr` 会与内容不一致

### 7.7 属性缓存导致的"看不到远端变更"

`attr_timeout` 期间，即使远端文件变了，`getattr` 也返回缓存值。
- 太长 → 同步慢/看不到变化
- 太短 → `ls -l` 都会放大成大量 `stat` 请求

✅ 建议：`attr_timeout=0.5~2s`；**远端检测到变更时主动 `inval_inode`** 强制失效（这也是唯一的正确做法）。

### 7.8 卸载时的数据丢失

`fusermount -u` 时若有 `dirty` 文件未上传 → **数据可能永久丢失**。
✅ 建议：
- `destroy()` 里先冲刷上传队列（带超时）
- 启动时做「恢复扫描」：把 `state=dirty` 的文件重新入队
- 提供 `--lazy-umount` 与显式的 `qsyncctl flush` 命令

---

## §8 脱水：整个系统最危险的操作

CfAPI 用 `CfOpenFileWithOplock` 保证「没人正在读」才允许释放；FUSE 里**没有任何类似保护**，
你必须自己证明「此刻删掉内容不会有人受害」。做错的后果是**应用读到 0 或崩溃**。

### 8.1 脱水前的完整检查清单

```python
def can_dehydrate(path) -> bool:
    if xattr(path, "user.qsync.pin") in ("pinned", "excluded"): return False
    if state(path) != "hydrated":                        return False
    if path in dirty_queue:                              return False   # 未上传
    if open_count(path) > 0:                             return False   # ★ 有打开的 fd
    if is_mmaped(path):                                  return False   # ★ 有 mmap
    if recently_modified(path, 300):                     return False   # 5 分钟内改过
    if in_progress(path):                                return False   # 正在传输
    return True
```

**`is_mmaped` 怎么判断**（Linux 没有直接 API）：
- 扫描 `/proc/*/maps` 里是否含该路径（够用但慢，建议只在脱水批次开始时扫一次）
- 或更简单：**用 `flock(LOCK_EX|LOCK_NB)` 试锁 + 自己维护 `open()` 计数** ——
  注意 Linux 的 `flock` **不阻止 mmap**，所以 flock 只能覆盖普通读写，mmap 仍需 `/proc` 扫描或接受风险

### 8.2 脱水 + page cache 失效（**顺序错了就丢数据**）

```
错误顺序：删内容 → 之后才让内核失效   ← 期间应用从 page cache 读旧数据，看似没事，但一旦 cache 被换出再读就是 0
正确顺序：
  ① 确认 can_dehydrate()
  ② 让内核对这个 inode 失效：inval_inode(path, offset=0, len=0)   # fuser: Notifier::inval_inode
     （这一步同时会丢弃 page cache 中的页）
  ③ 然后把文件内容清零（ftruncate 保留 size 或  punching hole)
  ④ 更新 xattr state = placeholder
```
> 如果你开了 `writeback_cache` 或依赖 page cache，② 是**必须**的；否则宁可**不脱水**。

### 8.3 更保守但更稳的替代：`direct_io`

对**所有**文件在 `open()` 时返回 `FOPEN_DIRECT_IO` → 完全绕过 page cache。
- ✅ 脱水变得绝对安全（内核里没有你的数据副本），`inval_inode` 也不需要
- ✅ 短读风险消失（每次 read 都进你的代码）
- ❌ 性能下降明显（无缓存、无 readahead、mmap 不可用）

**建议**：把它做成运行时可切换的策略：
```
--cache-mode=pagecache   （默认：性能好，脱水需严格按 §8.2）
--cache-mode=direct      （保守：脱水绝对安全，mmap 不可用）
```

### 8.4 脱水触发条件（照搬 Qsync）

对应 [05 篇 §5.5](05-OnDemand按需同步.md) 与 [09 篇](09-本地状态与配置布局.md)，Qsync 的注册表项直接映射为你的配置：

| Qsync 注册表项 | 你的配置 |
|---|---|
| `QSYNC_FOLDERPAIR_USE_SPACE_SAVING` | 每个同步目录的 `space_saving = on/off` |
| `QSYNC_SETTINGS_SPACE_SAVING_FREE_UP_SPACE` | `dehydrate.enabled` |
| `QSYNC_SETTINGS_SPACE_SAVING_FREE_UP_SPACE_MODE` | `dehydrate.mode = disk_size \| scheduled` |
| `QSYNC_SETTINGS_SPACE_SAVING_DISK_PERCENTAGE` | `dehydrate.disk_percent` |
| `QSYNC_SETTINGS_SPACE_SAVING_ENABLE_FREE_UP_SPACE_TIME` | `dehydrate.schedule_time` |

**只在启用了空间节省的目录里脱水**，并且提供手动命令 `qsyncctl free-up-space`（对应 `CQsyncSyncDll::FreeupSpace()`）。

---

## §9 分阶段实施计划（每阶段都有可验收标准）

| 阶段 | 内容 | 验收标准 | 预计 |
|---|---|---|---|
| **M0** 协议打通 | 登录 + `stat`/`get_list` + `download`（无 FUSE） | 能用 CLI 列出并下载 NAS 文件 | 1 周 |
| **M1** 只读 FUSE | `getattr`/`lookup`/`readdir`/`open`/`read`（**全部整文件水合**） | `ls -l` 显示真实大小；`cat` 任意文件可自动拉取 | 1–2 周 |
| **M2** 区间水合 | 128 KiB 分块 + 区间状态 + 短读防护 | `head -c 100 big.iso` **不触发整文件下载** | 1 周 |
| **M3** 双向同步 | `write`/`create`/`unlink`/`rename`/`setattr` + 上传队列 + `qbox_write_log` | 本地建/改/删文件能同步到 NAS，且**其它设备能看到** | 2–3 周 |
| **M4** 变更发现 | 三游标轮询 + 冲突处理 + 智能删除保护 | 两端互改能同步；断网重连不漏事件 | 2–3 周 |
| **M5** 脱水 | §8 的完整安全检查 + 磁盘阈值/定时 + `inval_inode` | 磁盘占用可控；`cat` 已脱水文件能重新拉取且**数据正确** | 1–2 周 |
| **M6** 打磨 | 选择性同步、veto、特殊字符、限速、代理、增量 delta | — | 持续 |

**强烈建议 M1 就上 FUSE（而不是先做完整引擎）**：FUSE 的坑（短读、mmap、page cache）只有真跑起来才暴露，
越晚发现返工越大。M1 用"整文件水合"虽然笨，但能把所有 FUSE 语义问题一次性暴露。

---

## §10 技术选型

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| **Rust + `fuser`** | 性能好；`Notifier::inval_inode` 等低层控制完整；内存安全 | 学习曲线 | ✅ **首选**（尤其你重视 §7/§8 的正确性） |
| **Go + `hanwen/go-fuse`** | goroutine 天然适配并发阻塞读；开发快；单二进制 | 低层控制略少（但 `inval_inode` 有） | ✅ 次选，适合快速出 MVP |
| **Go + `bazil.org/fuse`** | 简单 | 维护不活跃 | ❌ |
| **Python + `fusepy`** | 最快原型 | GIL + 性能差；不适合长期运行 | ⚠️ 只用于验证协议 |
| **C + libfuse3** | 控制力最强 | 工程量与风险最高 | ⚠️ 除非有特殊需求 |

**共通要求**：libfuse API 3.x（`FUSE_USE_VERSION >= 31`），必须能拿到 inode 失效通知接口。

---

## §11 测试矩阵（FUSE 特有的坑必须专门测）

| # | 测试 | 期望 |
|---|---|---|
| 1 | `ls -l` 未水合文件 | 显示**真实大小**，磁盘占用 ≈ 0 |
| 2 | `head -c 64 big.bin` | 只下载首个 128 KiB 分片 |
| 3 | `cat big.bin \| wc -c` | 字节数正确（**不得有 0 填充**） |
| 4 | `dd if=placeholder of=/dev/null bs=1M` | 全量正确 |
| 5 | `python -c "mmap 文件并读"` | 不 SIGBUS，数据正确 |
| 6 | `echo x >> placeholder; sync` | 原内容**未丢失**（read-modify-write 正确） |
| 7 | `truncate -s 0 placeholder` | 上传后云端为空 |
| 8 | `mv placeholder other` / 仅改大小写 | 服务端正确改名 |
| 9 | 脱水后立刻 `cat` | 重新水合且数据正确（**page cache 没残留**） |
| 10 | 脱水时另一进程正在读 | 脱水被跳过（不崩溃） |
| 11 | 拔网线再恢复 | 游标恢复；不漏事件；dirty 文件最终上传 |
| 12 | `fusermount -u` 时有 dirty | 不丢数据（阻塞或恢复扫描） |
| 13 | 本地删大量文件 | 智能删除保护生效 |
| 14 | 磁盘接近满 | 按 `disk_percent` 触发脱水 |
| 15 | 两端同时改同一文件 | 生成冲突副本，两边都不丢 |

---

## §12 与 CfAPI 的能力差距：哪些必须自研、哪些可以放弃

| CfAPI 能力 | FUSE 方案 | 是否影响功能 |
|---|---|---|
| `FETCH_DATA` 回调 | ✅ 自己实现（`read()`） | 不影响 |
| `CANCEL_FETCH_DATA` | ✅ 自己实现（超时 + 取消） | 不影响 |
| `CfCreatePlaceholders` / `CfConvertToPlaceholder` | ✅ 稀疏文件 + xattr | 不影响 |
| `CfHydratePlaceholder` / `CfDehydratePlaceholder` | ✅ 自己实现 | 不影响 |
| `CfSetPinState` / `CfGetPlaceholderInfo` | ✅ xattr | 不影响（可能更好用，`setfattr` 就能操作） |
| `CfOpenFileWithOplock`（独占保证） | ⚠️ `flock` + 打开计数 + `/proc/*/maps` 扫描 | **需要额外小心**（§8） |
| `CfReportProviderProgress` | ⚠️ 自研（进度文件 / D-Bus / CLI） | 不影响功能，只影响体验 |
| `CfGetPlatformInfo` 能力探测 | 不需要 | — |
| SyncRootManager 注册 | ❌ 不需要（无等价物） | 不影响 |
| 图标覆盖（overlay icon） | ❌ 无等价物 | ⚠️ 只能靠 `getfattr` / CLI / 自研文件管理器扩展（如 Dolphin/Nautilus 插件） |
| Explorer 缩略图提供者 | ⚠️ 可用 `func=get_thumb` + 桌面环境缩略图插件 | 可选 |
| Explorer 自定义列 | ❌ 无等价物 | 可选 |

**结论**：真正需要额外工程量的只有 **① 独占/一致性保证（oplock 等价物）** 和 **② 文件管理器集成**。
前者是正确性问题，必须在 M5 前解决；后者是体验问题，可以永远不做。

---

## §13 一页速查：动手前先决定这 7 件事

| # | 决策 | 推荐 |
|---|---|---|
| 1 | 占位符表示 | **稀疏文件 + `user.qsync.*` xattr** |
| 2 | 缓存模式 | 默认 page cache；提供 `--cache-mode=direct` 兜底 |
| 3 | 水合粒度 | **128 KiB**（与 Qsync 对齐） |
| 4 | 进程模型 | **单进程**，FUSE 多线程 + 共享状态 |
| 5 | 状态存储 | xattr（文件级）+ SQLite（baseline/队列/游标） |
| 6 | 脱水安全 | 必须 `inval_inode` → 再清内容；默认只对 `unpinned` 且未打开/未 mmap 的文件 |
| 7 | 语言/库 | Rust + `fuser`；或 Go + `hanwen/go-fuse` |

**如果只记一句话**：
> **每一次 `read()` 都必须返回真实数据或明确报错，绝不返回 0；每一次脱水都必须先让内核失效缓存，绝不先删内容。**
> 这两条守住，项目就不会出现"数据静默损坏"这种最难查的 bug。
