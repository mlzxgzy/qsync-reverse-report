# 11 · API 规格书（可直接照此开发）

> 本文是**开发用的接口规格**：每个端点给出 **请求（方法、参数、类型、必填、含义）** 与
> **响应（格式、解析器、字段、置信度）**。置信度标注规则见 §0.6。
>
> 配套机器可读文件：[`out/api_endpoints.json`](out/api_endpoints.json)（208 条端点 × 参数）、
> [`out/parser_fields.json`](out/parser_fields.json)（43 个解析器的字段）、
> [`out/endpoints_clean.txt`](out/endpoints_clean.txt)（322 条原始 URL 模板）。

---

## §0 通用约定（**开发前必读**）

### 0.1 URL 构造
```
{scheme}://{host}:{port}/{prefix}{cgi_path}?{query}
  scheme  ∈ { "http://", "https://" }        // 明文模板里是字面量 "http://" / "https://"
  prefix  ∈ { "", "qsync/" }                 // 运行时决定，直连 NAS 通常为空
  cgi_path ∈ 见 §0.2
```
模板里 `%ls%ls:%d/%lscgi-bin/...` 的三段依次是 **scheme、host、port**，第 4 个 `%ls`（在 `/` 之后）就是 `prefix`。

### 0.2 两套命名空间（同一功能两条路径，必须都实现）
| 新版（QTS 5.x / Qsync QPKG） | 旧版（内建 WFM） |
|---|---|
| `/cgi-bin/qsync/qsyncsrv.cgi` | `/cgi-bin/filemanager/utilRequest.cgi` |
| `/cgi-bin/qsync/qsyncsrv.fcgi` | — |
| `/cgi-bin/qsync/qsyncsrvPrepare.cgi` | `/cgi-bin/filemanager/qsyncPrepare.cgi` |
| `/cgi-bin/qsync/qsyncsrv_login.cgi` | `/cgi-bin/filemanager/wfm2Login.cgi` |
| `/cgi-bin/qsync/qsyncsrv_logout.cgi` | `/cgi-bin/filemanager/wfm2Logout.cgi` |
| `/cgi-bin/qsync/upload.php` | `/cgi-bin/filemanager/upload.php` |

**探测顺序 [推]`△`**：先请求 `qsyncPrepare.cgi`（旧版 `qsyncPrepare.cgi`）。返回 404 → `bPrepareCGINotFound=1`
→ 之后所有请求走 `utilRequest.cgi` 家族。依据：`CQWebManConnection::NASLogin(...)(bPrepareCGINotFound=%d)`。

### 0.3 HTTP 方法与请求体 ★
| 端点类型 | 方法 | Body |
|---|---|---|
| 带完整 query 的 `func=*`（绝大多数） | **GET** | 无 |
| `authLogin.cgi` / `qsyncsrv_login.cgi` / `wfm2Login.cgi` | **POST** | `application/x-www-form-urlencoded` |
| 无 query 的 `func=rename` / `move` / `delete` / `qbox_share_to` / `qbox_set_share_member` / `qbox_team_folder_*` | **POST** | form-urlencoded（参数名见 §7、§11） |
| `upload.php` / `func=upload` / `func=upload_and_move` / `func=chunked_upload` / `func=versioning_upload_file` | **POST** | `multipart/form-data` |

**[已确认]** `Content-Type` 字面量（`QFileSync.dll`）：
```
application/x-www-form-urlencoded
application/x-www-form-urlencoded; charset=UTF-8
```
**[未确认]** `func=rename|move|delete` 等无 query 端点的 body 参数名（模板里没有 query，参数由 POST body 携带；
字符串区存在 `dest_folder` / `dest_name` / `filename` / `file_total` / `source_total` 等键，但未逐一定位到具体端点）。
**开发建议**：先按 GET + query 试，若服务端返回参数缺失再改 POST body，用 [probe](probe/README.md) 可 5 分钟内确认。

### 0.4 通用请求头 **[已确认]**
```
Accept: */*                         Cache-Control: no-cache
Connection: Keep-Alive              X-Forwarded-For: 127.0.0.1
User-Agent: <自定义>
Content-Type: application/x-www-form-urlencoded   ← POST 时
```
云账号（QID）侧另有：`X-QNAP-APP-ID`、`X-QNAP-SUBAPP-ID`、`X-QNAP-APP-VER`、`X-QNAP-TIME`、`X-QNAP-CHECK`、
`Authorization: Bearer <access_token>`、`Accept: application/json`。

### 0.5 ★★ 响应格式：**JSON 为主，少数 CGI 是 XML**（必须嗅探）

你会在 `C*Json` 和 `*Xml` 两套类名之间困惑 —— 结论是：**两套都是真的，两套解析库都在二进制里。**

| 事实 | 证据 |
|---|---|
| **jsoncpp 被静态链接进全部三个 WFM 模块** | 三个模块里都有 jsoncpp 的特征错误串：`Syntax error: value, object or array expected.`、`Missing ',' or '}' in object declaration`、`Value is not convertible to Int.`、`Bad escape sequence in string`、`additional six characters expected to parse unicode surrogate pair.`；以及 `true`/`false`/`null` 被截断的 `rue`/`alse`/`ull` 字面量 |
| **TinyXML 也被链接（仅 QFileSync / QsyncLib）** | RTTI：`TiXmlDocument@WFMXml`、`TiXmlElement@WFMXml`、`TiXmlAttribute@WFMXml`、`TiXmlNode@WFMXml`、`TiXmlText@WFMXml`、`QXmlParserBase@WFMXml` |
| WFM 层错误码统一叫 `WFM_PARSE_XML_*` | 属**历史命名**，对 JSON 解析失败也用这套码（不要据此判断格式） |
| 库分布 | `QFileSync.dll`：TinyXML + jsoncpp；`QsyncLib.dll`：TinyXML + jsoncpp；`QsyncAPI.dll`：**只有 jsoncpp**（无 TinyXML） |

#### 判定规则：看解析器类名后缀 **[已确认]**

**`*Xml` 类（共 8 个）→ 这些端点返回 XML**：
| 类 | 对应端点 |
|---|---|
| `CAuthLoginXml` | `authLogin.cgi`（含 `func=passwordless`、`send_mail`/`serviceKey` 二步验证） |
| `CSecurityQuestionXml` | `WFMGetSecurityQuestion` |
| `CSendSecurityCodeXml` | `WFMSendSecurityCode` |
| `CSysInfoXml` | `sysinfoReq.cgi?subfunc=info` |
| `CQsyncQPKGXml` | `appRequest.cgi?subfunc=qpkg`（`WFMCheckQsyncQPKG`） |
| `CWebFileManGetLinkXml` | `func=get_share_link` |
| `CWebFileManCreateLinkXml` | `func=share_file` / 创建分享链接 |

**其余全部 `C*Json` 类（约 70 个）→ 返回 JSON。**

#### ★ 实现建议（务必照做）
```
resp = http.request(...)
body = resp.text.lstrip()
if body.startswith(('{', '[')):
    data = json.loads(body)            # 覆盖 95% 的 func= 端点
elif body.startswith('<'):
    data = parse_xml(body)             # authLogin.cgi / sysinfoReq.cgi / 分享链接等
else:
    error("unexpected response")
```
不要写死某个端点的格式；按 `Content-Type` 或首字符嗅探最稳。
XML 侧的手写 CDATA 提取模式（`CAuthLoginXml` 用）：
```
<%s><![CDATA[ ... ]]>
```
XML 声明头为 `<?xml version='1.0' encoding='UTF-8' standalone='yes'?>`。

**云账号（QID/myQNAPcloud）侧统一是 JSON** —— `Qsync.exe` 使用 Qt5 的
`QJsonDocument` / `QJsonObject` / `QJsonArray` / `QJsonValue`。

### 0.6 置信度标注规则

| 标记 | 含义 |
|---|---|
| `✅` | 已确认：有字符串/导出表/导入表/反汇编直接证据；参数名与类型来自 printf 模板，不会错 |
| `△` | 较可信：多证据一致（如解析器字段簇），但归属或语义未经逐指令确认 |
| `?` | 未确认：仅推测，开发前必须用 [probe](probe/README.md) 验证 |

**参数表里**：类型来自 URL 模板的 printf 占位符 —— **这部分是确定的**（`%s`=字符串，`%d`/`%u`=整数，`%lld`=64 位整数）。
**响应字段表里**：字段名来自解析器在 `.rdata` 中的字面量簇，**归属与类型是推断的**。

### 0.7 通用响应信封 **[已确认]**
WFM 解析器普遍先读这几个字段：
```
status      整数，0 = 成功（非 0 = 失败）
success     布尔（部分端点）
result      布尔/整数（部分端点）
error       错误字符串
error_code  错误码整数
```
非 0 `status` 一般伴随 `error` / `error_code`。各端点另有自己的数据字段，见各组。

---

## §1 端点总览

### 1.1 分类统计（互斥，合计 123 个 `func=`）
| 组 | 个数 | 章节 |
|---|---|---|
| 登录 / 会话 | 5 | §3 |
| 鉴权（共享文件夹两步） | 4 | §13 |
| 会话状态 / 能力探测 | 23 | §4 |
| **变更发现（日志游标）** | **12** | §5 |
| 列举 / 元数据 | 8 | §6 |
| 写操作 | 10 | §7 |
| 上传 | 6 | §8 |
| 下载 | 2 | §9 |
| 版本化 / delta | 15 | §10 |
| 共享 / 团队文件夹 | 28 | §11 |
| 备份 | 8 | §12 |
| 其他（`qpkg`、`search_engine`） | 2 | §2.2 |
| **合计** | **123** | |

### 1.2 独立 CGI（非 `func=`）
`authLogin.cgi`、`authLogout.cgi`、`qsyncsrv_login.cgi`、`qsyncsrv_logout.cgi`、`qsyncsrv.fcgi?func=login|logout`、
`qsyncsrvPrepare.cgi`（`?user=` / `?func=activate&token=`）、`wfm2Login.cgi`、`wfm2Logout.cgi`、`qsyncPrepare.cgi`、
`upload.php`、`share.cgi`、`sysinfoReq.cgi`、`appRequest.cgi`，以及云侧 `/oauth/*`、`/v1.*`。

### 1.3 ★ 本机服务端（局域网对等直连）—— **不是 NAS 端点**
以下由 `QsyncLib.dll` 内嵌的 `QHttpServer` 提供，供同账号的其它 PC 直连查询/拉取（见 03 篇 §3.10）。
它们的字面量**没有主机前缀**，是相对 URL：
```
GET  /?func=search_engine&nas_uid=&share_folder_uid=&file_path=&file_size=&file_time=&local_user_uid=[&nas_cuid=]
GET  /?func=auth_1                      （WebSocket 服务另有 ws_service_callback）
GET  /?func=auth_2
```
`search_engine` 返回该路径在本机是否存在及元数据。**你的 Linux 客户端第一版可以不实现这组。**

---

## §2 参数速查表（89 个参数名）

| 参数 | 类型 | 必填 | 出现次数 | 含义 |
|---|---|---|---|---|
| `sid` | string | ✅ | 183 | **会话 ID**。除登录类接口外全部端点必带。来自 `authLogin.cgi` 的 `authSid` |
| `func` | string | ✅ | — | 功能名（本文各节的 func 值） |
| `path` | string | 视端点 | 18 | NAS 侧绝对路径（共享文件夹根开始，如 `/share/Photos`） |
| `source_path` | string | 视端点 | 24 | 版本化：源目录（相对共享文件夹） |
| `source_file` | string | 视端点 | 25 | 版本化：源文件名（与 `source_path` 分离，规避路径长度限制） |
| `dest_path` | string | 视端点 | 12 | 目标目录绝对路径 |
| `dest_folder` | string | 视端点 | 2 | 新建目录名（配合 `dest_path`） |
| `file_name` | string | 视端点 | 5 | 文件名（单文件操作） |
| `filename` | string | 视端点 | 2 | 文件名（分享相关） |
| `file_total` | int | ✅(单文件类) | 5 | 批量操作的文件总数；单文件操作固定 `1` |
| `source_total` | int | 视端点 | 2 | 同上（源侧计数） |
| `total` | int | ✅(properties) | 2 | `properties` 端点固定 `1` |
| `name` | string | ✅(properties) | 3 | 目标名 |
| `filesize` | string(64位) | 视端点 | 6 | 文件字节数（**字符串形式传 64 位**） |
| `offset` | string(64位) | 视端点 | 6 | 断点续传偏移字节 |
| `upload_id` | string | ✅(分块) | 6 | 分块上传会话 ID（由 `start_chunked_upload` 返回） |
| `upload_root_dir` | string | ✅(分块) | 10 | 服务端临时上传根目录 |
| `upload_name` | string | 视端点 | 2 | 上传临时文件名 |
| `rename_dest` | string | 可选 | 4 | 上传后重命名的目标名（原子落地用） |
| `overwrite` | int(0/1) | ✅(上传) | 8 | 是否覆盖已存在文件 |
| `settime` | const `1` | 可选 | 8 | 置 1 表示同时设置文件时间 |
| `mtime` | string | 配合 settime | 8 | 修改时间（**epoch 秒，字符串形式**） |
| `version_id` | string | 视端点 | 20 | 版本 ID（`versioning_lock&create_version=1` 返回） |
| `lockid` | string | 视端点 | 16 | 版本锁 ID（同上一起返回） |
| `versioning_version` | const `1` | ✅(版本化) | 4 | 协议版本，固定 1 |
| `create_version` | const `1` | 二选一 | 2 | **创建新版本** |
| `check_version` | const `1` | 二选一 | 2 | **校验/续用已有版本** |
| `lower` | int/string | ✅(日志) | 15 | **区间下界（已处理游标）** |
| `upper` | int/string | ✅(区间查询) | 12 | 区间上界 |
| `number` | int | ✅(日志) | 6 | 本次拉取条数（批量大小） |
| `max_log` | int | — | — | 响应字段：服务端最大日志号 |
| `syncing_folder` | string | 可选 | 2 | 限定某个同步文件夹 |
| `sub_folder` | string | 可选 | 3 | 限定子目录 |
| `get_detail` | const `1` | 可选 | 2 | 让日志返回详情（新版形参） |
| `folder` | string | 可选 | 5 | 限定文件夹（`qbox_get_max_log` 等） |
| `limit` | int | ✅(列举) | 5 | 分页大小 |
| `start` | int | ✅(列举) | 5 | 分页起始下标 |
| `dir` | string | 可选 | 4 | 排序方向 `ASC` / `DESC` |
| `sort` | string | 可选 | 4 | 排序键（如 `filename`） |
| `no_sort` | int | 可选 | 2 | 置 1 关闭排序 |
| `is_iso` | const `0` | ✅(列举) | 4 | 固定 0（ISO 时间格式开关） |
| `list_mode` | const `all` | ✅(列举) | 2 | 固定 `all` |
| `type` | const `4` | 可选 | 3 | `get_list` 的列表模式变体 |
| `hidden_file` | const `1` | 可选 | 2 | 包含隐藏文件（Qsync 用） |
| `node` | string | ✅(get_tree) | 2 | 树节点路径 |
| `get_privilege` | const `1` | 可选 | 3 | 返回权限信息 |
| `check_upload` | const `1` | ✅(权限预检) | 2 | 检查上传权限 |
| `check_detail` | int | 可选 | 1 | `qbox_get_nas_status` 返回详情 |
| `user` | string | 视端点 | 10 | 用户名 |
| `user_type` | int | ✅(成员列表) | 4 | 用户类型（本地/域/团队） |
| `all_user` | int | 可选 | 4 | 是否含全部用户 |
| `refresh` | int | 可选 | 4 | 强制刷新缓存 |
| `netbios` | string | 可选 | 4 | AD NetBIOS 域 |
| `domain` | string | 可选 | 4 | AD 域名 |
| `filter` | string | 可选 | 5 | 过滤关键字 |
| `share_id` | string | ✅(共享) | 10 | 共享/团队文件夹 ID |
| `share_policy` | int | ✅(策略) | 2 | 共享策略值 |
| `ssid` | string | ✅(分享) | 2 | 分享链接 ID |
| `ssids` | string | ✅(批量删) | 2 | 多个 ssid（逗号分隔） |
| `download_link` | string | 可选 | 2 | 直接下载链接 |
| `event_id` | int | ✅(事件) | 5 | 事件 ID（接受/拒绝共享邀请等） |
| `event_type` | int | 可选 | 2 | 事件类型过滤 |
| `event_status` | const `0` | ✅(团队) | 1 | 事件状态过滤 |
| `display_name` | string | ✅(接受团队共享) | 1 | 显示名 |
| `recycle_bin` | int | ✅(开关) | 2 | 回收站开关 |
| `config_number` | int | ✅(设备配置) | 2 | 配置条目序号 |
| `device_uid` | string | ✅(设备配置) | 6 | 设备唯一 ID |
| `apply` | const `1` / `10` | ✅ | 3 | `apply=1` 设备配置生效；`apply=10` QPKG 应用 |
| `mode` | int | 视端点 | 6 | 模式（`trash_recovery`/`repository_recovery` 的恢复模式） |
| `action` | int | 视端点 | 2 | 动作码（备份目录设置 / `qbox_write_log` 的文件动作） |
| `time` | string | ✅(备份) | 1 | 时间值 |
| `timestamp` | string | ✅(备份列表) | 1 | 时间戳过滤 |
| `show_deleted` | int | ✅(备份列表) | 1 | 是否包含已删除项 |
| `channel` | int | ✅(备份开始) | 3 | 备份通道号 |
| `pid` | int/string | ✅(进度) | 6 | 后台任务进程 ID |
| `no_fork` | int | 可选 | 1 | 置 1 让 `move` 同步执行（不 fork） |
| `subfunc` | string | ✅ | 4 | 子功能：`delete`（`daemon_list`）/ `qpkg`（`appRequest.cgi`）/ `info`（`sysinfoReq.cgi`） |
| `password` | string | ✅(管理口令) | 2 | 配置管理口令（`qbox_auth_config_password`） |
| `token` | string | ✅(激活) | 2 | 激活令牌（`qsyncsrvPrepare.cgi?func=activate`） |
| `access_token` | string | ✅(云) | 1 | QID access token |
| `logout` | const `1` | ✅(登出) | 4 | 固定 1 |
| `op` | const `8` | ✅(免密) | 1 | `authLogin.cgi?func=passwordless&op=8` |
| `file` | string | ✅ | 3 | 文件名/路径 |
| `filepath` | string | ✅ | 1 | 文件路径（`qbox_write_log`） |
| `size` | int | ✅(缩略图) | 1 | 缩略图边长 |
| `option` | const `3` | ✅(缩略图) | 1 | 缩略图选项 |
| `check_qbox_file_profile` | const `1` | 可选 | 2 | 上传前按 profile 校验 |
| `check_qbox_file_exist` | int | 可选 | 2 | 是否校验目标已存在 |
| `check_qbox_file_type` | const `0` | 可选 | 1 | 类型校验模式 |
| `check_qbox_file_path` | string | 可选 | 1 | 校验用的目标路径 |
| `check_qbox_file_size` | string | 可选 | — | 校验用的文件大小（另一变体） |
| `check_qbox_file_time` | string | 可选 | — | 校验用的文件时间（另一变体） |

> 说明：`filesize` / `offset` / `mtime` 用**字符串**承载 64 位值（模板是 `%s` / `%ls`），
> 开发时不要用定长整型格式化。

---

## §3 登录 / 会话

### 3.1 `POST /cgi-bin/authLogin.cgi` ✅
账号密码登录，拿到 **`authSid`**（后续所有端点的 `sid`）。

**请求体**（`application/x-www-form-urlencoded; charset=UTF-8`）
| 字段 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `user` | string | ✅ | 用户名 |
| `service` | string | ✅ | 服务标识，Qsync 传 `Qsync` |
| `client_app` | string | 推荐 | 客户端应用名，Qsync 传 `Qsync` |
| `client_agent` | string | 推荐 | 客户端代理标识串 |
| `client_id` | string | 推荐 | 客户端 ID（空串亦可） |
| `verify_code` / `code` | string | 二步验证时 | 验证码 / 授权码 |
| `security_answer` / `security_code` | string | 二步验证时 | 安全问题答案 / 安全码 |
| `qtoken` | string | 续期时 | 预置 QToken（免密续登） |
| `qid_user_id` / `qid_access_token` | string | QID 登录时 | QID 身份 |
| `duration` / `remme` | int | 可选 | 会话时长 / 记住我 |
| `func` / `approve` / `session` / `verification_code` / `qr_code` | — | 手机批准/QR 登录 | 子流程 |

**请求头**：额外带 `X-Forwarded-For`。
**响应**：**XML**，解析器 `CAuthLoginXml` ✅
| 字段 | 类型 | 含义 |
|---|---|---|
| `authPassed` | int/bool | **是否通过**（`1`/`true`） |
| `authSid` | string | **★ 会话 SID** |
| `error_code` | int | 错误码 |
| `access_token_ret` | string | QID access token 回流 |
| `remain` | int | 剩余天数/次数（密码有效期） |
| `pw_expiry` | int | 密码过期标志 |
| `permission_deny` | int | 权限拒绝 |
| `account_login_restricted` | int | 账号登录受限 |
| `username` | string | 用户名 |
| `suid` | string | 用户 UID |
| `cuid` | string | 用户 CUID |
| `displayModelName` / `modelName` | string | NAS 型号 |
| `firmware` → `name` | string | 固件版本（嵌套元素） |
| `number` | int | 集群节点数 |
| `passwordless_login` | int | 是否支持免密登录 |
| `function_support` | string/int | 功能位图 |
| `lost_phone` | int | 丢失手机流程 |
| `need_2sv` / `force_2sv` / `need_2_step_verification` | int | **二步验证需求** |
| `emergency_try_limit` / `emergency_try_count` | int | 紧急码尝试限制/已用 |
| `security_code_en` / `qrcode_en` / `vcode_en` / `approve_login_en` | int | 各二步方式是否启用 |
| `security_question_no` / `security_question_text` / `system_question_text` | int/string | 安全问题 |
| `admingroup` / `servername` | int/string | 是否管理员组 / 服务器名 |
| `home` / `home_folder_available` | string/int | 家目录 / 是否可用 |

> **典型错误分支**：`error_code` 非 0 + `need_2sv=1` → 走二步验证；`permission_deny=1` → 拒绝；
> `account_login_restricted=1` → 账号受限。`WFM_NEED_USER_NAME` 语义 = 需重新提供用户名（重试本端点）。

### 3.2 `POST /cgi-bin/authLogin.cgi?func=passwordless&op=8` △
免密登录（不使用密码，基于已信任设备/QID）。参数同 §3.1 的 `func`/`op`。响应同 `CAuthLoginXml`。

### 3.3 `POST /cgi-bin/qsync/qsyncsrv_login.cgi`（等价：`qsyncsrv.fcgi?func=login`、`wfm2Login.cgi`）✅
Qsync 层登录，拿到 **`q_token`**（Qsync 专用长效令牌，可持久化用于免密重连）。

**请求体**
| 字段 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `user` | string | ✅ | 用户名 |
| `qbox_user` | string | ✅ | 用户名（Qsync 专用字段名，与 `user` 同值） |
| `qbox_computer` | string | ✅ | 本机电脑名 |
| `qbox_device_type` | string | ✅ | 设备类型（Qsync 传 `"3"`） |
| `Qsync_client_version` | string | ✅ | 客户端版本号 |

**响应**：XML；解析器 `CQsyncLogin` ✅
| 字段 | 含义 |
|---|---|
| `q_token` / `qtoken` | **★ Qsyc 会话令牌**（客户端内部变量名 `strQToken`） |
| `authSid` / `sid` | 可能的 SID 回传 |
| `qbox_cgi` / `fcgi` | 是否支持新版 CGI 家族（决定后续用 `qsyncsrv.cgi` 还是 `utilRequest.cgi`）|
| `Qsync_version` / `Qsync_qpkg_version` | 服务端版本 |
| `enableACL` | 是否启用 ACL |
| `Max_File_List` | 单次列表上限 |
| `qbox_share_id` / `qbox_type` | 共享相关 |
| `mycloudnas_dn` / `ext_ip` / `ddns_dn` | 云/地址信息 |
| `home_section_fail` | 家目录段失败 |
| `qbox_slave_id` | 集群 slave id |
| `build` / `enable` / `readonly` | 其他 |

> 客户端判据字符串：`QsyncLogin strQToken.length() == 0 (bSupportQToken)` —— **`q_token` 为空即视为不支持 QToken**。

### 3.4 `GET /cgi-bin/qsync/qsyncsrvPrepare.cgi?user=%s`（旧版 `qsyncPrepare.cgi?user=%s`）✅
取 NAS 用户 UID / CUID / UserCUID。

| 参数 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `user` | string | ✅ | 用户名 |

**响应**：XML；解析器 `CShareGetUIDJson` △（簇内字段可能混入邻接解析器）
| 字段 | 含义 |
|---|---|
| `UID` / `SUID` / `CUID` | **用户 UID / SUID / CUID** |
| `MAC0` | NAS MAC |
| `is_booting` | NAS 是否正在启动 |
| `user_type` | 用户类型 |
| `Qsync_version` / `Qsync_qpkg_version` | 版本 |
| `is_migrating` / `is_recovering` / `is_backuping_restoring` | **NAS 状态**（迁移/恢复/备份还原中 —— 此时应暂停同步） |
| `qbox_cgi` / `fcgi` / `DisableFastCGI` | CGI 家族选择 |
| `versioning_version` | 版本化协议版本 |
| `volume_total_size` / `volume_free_size` | 卷容量 |

> 客户端日志：`CQWebManConnection::GetNASUID() QsyncLogin HBS backup/restoring | Migrating | Recoverying` ——
> **这三个状态会导致同步暂停**，必须处理。

### 3.5 `GET /{prefix}cgi-bin/qsync/qsyncsrvPrepare.cgi?func=activate&token=%s` ✅
激活 SID，返回 server name 与是否 admin 组。

| 参数 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `func` | const `activate` | ✅ | 固定 |
| `token` | string | ✅ | 激活令牌 |

**响应**：XML；解析器 `CActivateJson` △ → 字段 `server name`、`is admin group`（错误串：
`QsyncActivateSid2: WFM_PARSE_XML_FAIL(empty server name)` / `(empty is admin group)`）。
对应上层的 `CShift`：`QsyncActivateSid`（旧）/ `QsyncActivateSid2`（新，多返回集群信息）。

### 3.6 登出 ✅
| 端点 | 参数 |
|---|---|
| `GET /cgi-bin/authLogout.cgi?sid=&logout=1` | `sid`,`logout=1` |
| `GET /cgi-bin/qsync/qsyncsrv_logout.cgi?sid=&logout=1` | `sid`,`logout=1` |
| `GET /cgi-bin/qsync/qsyncsrv.fcgi?func=logout&sid=&logout=1` | 同上 |
| `GET /cgi-bin/filemanager/wfm2Logout.cgi?sid=&logout=1` | 同上 |

响应：XML，字段 `status` / `result`（`WFMLogout: WFM_PARSE_XML_FAIL Status(%d), Result(%d)`）。

### 3.7 会话保活 ✅
**没有专用端点** —— 客户端用 `get_list` 探 `share_root`：
```
GET /cgi-bin/qsync/qsyncsrv.cgi?func=get_list&sid=&is_iso=0&list_mode=all
    &path=/&dir=ASC&limit=1&sort=filename&start=0&no_sort=0
```
返回 `ERROR_ACCESS_DENIED` → SID 失效 → 重走 §3.1/§3.3。
证据：`CQWebManConnection::CheckSessionAlive() WFMGetFolderList failure(share_root)(%d)`。

---

## §4 会话状态与能力探测

> 这 23 个端点都是 `GET`，都需要 `sid`，响应都是 XML。它们是**启动时一次性探测**，
> 用于决定同步策略（是否支持版本化、配额、veto 文件、集群等）。

| # | 端点 | 参数 | 响应解析器 | 关键响应字段 |
|---|---|---|---|---|
| S1 | `func=qbox_get_qbox_info` | `sid` | `CShareToJson` △ | `qbox_versioning_enable`, `versioning_enable`, `access_control_mode`, `description`, `domain_name`, `organization_name` |
| S2 | `func=qbox_get_nas_status` | `sid`[,`check_detail=%d`] | `CGetNASStatusJson` ✅ | `device_db_exist`, `home_folder_enable`, `share_db_exist`, `log_db_exist`, `user_enable` |
| S3 | `func=qbox_get_static_information` | `sid` | `CQsyncGetNASStaticInfoJson` ✅ | `queue_num_limit`, `fw_version`, `msg_queue_num_limit`, `model` |
| S4 | `func=qbox_get_quota_info` | `sid` | `CGetUserQuotaJson` ✅ | `quota_enable`, `quota`, `quota_size`, `used_quota_size`, `avaiable_quota_size`(原文拼写), `vol_id` |
| S5 | `func=qbox_get_nas_uid` | `sid` | — | NAS 唯一 ID（用于配对校验 `QFILE_NAS_NOT_MATCH`） |
| S6 | `func=qbox_get_system_sid` | `sid` | — | 系统 SID |
| S7 | `func=qbox_get_policy` | `sid` | `CShareGetUserListJson` △ | `policy`, `share_policy`, `qsyncuser` |
| S8 | `func=qbox_get_config_acl` | `sid` | `CGetConfigACLInfoJson` ✅ | `section`, `config`, `all`（决定客户端可改哪些 NAS 配置） |
| S9 | `func=qbox_get_veto_files` | `sid` | — | **服务端排除文件列表**（veto = 永不同步的黑名单） |
| S10 | `func=qbox_get_recycle_bin_status` | `sid` | `CGetRecycleBinJson` △ | 回收站开关与状态 |
| S11 | `func=qbox_get_last_modify_time` | `sid` | — | 服务端配置最后修改时间 |
| S12 | `func=qbox_get_registry` | `sid` | — | 服务端注册表快照 |
| S13 | `func=get_domain_ip_list` | `sid` | `CGetDomainIPListJson` ✅ | 见 §4.1 |
| S14 | `func=get_sys_setting` | `sid` | — | 系统设置 |
| S15 | `func=qbox_get_cluster_node_list` | `sid` | — | 集群节点列表 |
| S16 | `func=qbox_get_syncing_folder_list` | `sid` | `CGetSyncingFolderListJson` ✅ | 见 §4.2 |
| S17 | `func=qbox_get_user_home` | `sid`,`user` | `CGetUserHomePathJson` ✅ | `home_folder_available`（+ 家目录路径） |
| S18 | `func=qbox_get_progress` | `sid`,`pid` | `CGetMoveStatusJson` △ | `percent`(或 `percentage`) |
| S19 | `func=get_move_status` | `sid`,`pid`(%d) | `CGetMoveStatusJson` ✅ | `percent`, `filename` |
| S20 | `func=daemon_list` | `sid`,`subfunc=delete`,`pid`(%d) | — | **取消后台任务**（搬运/复制） |
| S21 | `func=get_ad_info` | `sid` | `CShareGetAdInfoJson` ✅ | `netbios`, `TrustedDomainEnable` |
| S22 | `func=qbox_rename_device` | — | — | 重命名本设备（旧式 `utilRequest`） |
| S23 | `func=info` | — | — | 通用信息（出现在 `QFileSync`/`QsyncAPI`） |

### 4.1 `get_domain_ip_list` 响应 ✅（地址回退的核心数据）
解析器 `CGetDomainIPListJson`：
```
mycloudnas_hn          string    myQNAPcloud 主机名
ddns_hn / ddns_hn_list string    DDNS 主机名（列表）
host_ip                string    当前访问用的 host
myqnapcloud_link_status int      CloudLink 状态
myqnapcloud_ddns_status int      DDNS 状态
myqnapcloud_device_name string   设备名
qid                    string    QID
ip_list[]              array     { ip_addr, ip_type, external_ip, local_ip }
                                  ip_type ∈ { external_ip, local_ip }（见 Unknown IP type 日志）
local_ip_list          array     本地 IP 列表
ddns_list[]            array     { provider = "myQNAPcloud", ... }
port / sslPort         int
extPort / extSslPort   int       外网 HTTP / HTTPS 端口
qbox_function_enable   int       Qsync 功能开关
qbox_user_enable       int
home_is_exist          int
team_folder_is_exist   int
qbox_cluster_support   int       是否支持集群
qbox_cluster_status    int
qbox_cluster_slave_id  string
```

### 4.2 `qbox_get_syncing_folder_list` 响应 ✅
解析器 `CGetSyncingFolderListJson`：
```
folder          string   同步文件夹路径
permission      int      权限
read_deletable  int      可读/可删
realpath        string   实际路径
volume_id / vol_id string 卷 ID
volume_lock     int      卷锁定
volume_encrypt  int      卷加密
lock / enc      int      锁定/加密状态
fkey / client_key string 卷密钥 / 客户端密钥
capacity / capacity_unit  int/string  容量与单位
used_size / used_unit     容量已用
free_size                 剩余
slave / slave_id  集群从节点
pid               int
```
> `capacity_unit` / `used_unit` 取值 **[已确认]**：`Byte, KB, MB, GB, TB, PB, EB`。

---

## §5 变更发现（同步引擎的心脏）★

> 模型：**服务端三路递增日志 + 客户端三个持久化游标**。
> 完整流程见 [03 篇 §3.1](03-同步引擎与传输.md)。

### 5.1 `GET /cgi-bin/qsync/qsyncsrv.fcgi?func=qbox_get_max_log&sid=[&folder=]` ✅
**取服务端当前最大日志号**。这是轮询循环的入口。

| 参数 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `sid` | string | ✅ | 会话 |
| `folder` | string | 可选 | 只看某个同步文件夹的最大号（不带 = 全局） |

**响应**：XML；解析器 `CQsyncGetMaxLogJson` ✅
| 字段 | 含义 |
|---|---|
| `max_log` | **★ 最大日志号**（客户端与之比较决定是否拉取） |
| `notify` | 变更通知数 |
| `global_notify` | 全局通知数 |
| `sync_signal` | 同步信号（服务端要求客户端尽快同步） |
| `slowdown_seconds` | 服务端要求降低轮询频率的秒数（**限流反馈**） |

> 旧命名空间等价端点：`qsyncsrvPrepare.cgi?func=qbox_get_max_log`、`qsyncPrepare.cgi?func=qbox_get_max_log`。

### 5.2 `GET /cgi-bin/qsync/qsyncsrv.cgi?func=qbox_get_sync_log` ✅
**按区间拉取文件变更日志**。

| 参数 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `sid` | string | ✅ | 会话 |
| `lower` | string/int | ✅ | **区间下界 = 本地已处理游标** |
| `number` | int | ✅ | 本次拉取条数 |
| `syncing_folder` | string | 可选 | 限定同步文件夹 |
| `sub_folder` | string | 可选 | 限定子目录 |
| `get_detail` | const `1` | 可选 | 返回详情（新版 `fcgi` 形参） |

**响应**：XML；解析器 `CGetQsyncSyncLogJson` + 事件项 `CGetConfigNotifyItemInfoJson` △
| 字段 | 类型 | 含义 |
|---|---|---|
| `max_log` | int | 服务端当前最大号（可顺带更新） |
| `notify` | int | 通知数 |
| `global_notify` | int | 全局通知数 |
| `old_mtime` / `old_exist` | string/int | 变更前的时间与存在性（**用于判断是新增/修改/删除**） |
| `mtime` | string | 变更后时间 |
| **事件项数组** | — | 每项字段见下 |

事件项字段（解析器 `CGetConfigNotifyItemInfoJson`）△：
```
filename        string   变更的文件名
filepath        string   变更的文件路径
event           string   事件名
event_type      int      事件类型
event_user      string   触发事件的用户
event_time      string   事件时间
event_modifier  string   修改者
event_value     string   事件值
duid            string   设备 UID
device_name / device_uid  来源设备
share_member / share_path / share_id_status  共享相关
thumbnail       string   缩略图
msg / description        消息
action          int      动作码
log_id          int      日志 ID
old_filepath    string   变更前路径（重命名场景）
old_size        string   变更前大小
```

> **开发要点**：
> 1. `lower` 用**已处理游标**，返回事件处理完后才推进游标（先处理再提交）。
> 2. 服务端日志会**滚动删除**。收到 `WFM_QSYNC_LOG_MISSING` 或 `max_log` 回退 → **游标归零 + 全量重扫**。
> 3. 事件的粒度是「路径变了」，**不携带文件内容**，需要后续 `stat`/`get_list` 比对。

### 5.3 `GET ...?func=qbox_query_notify&sid=&lower=%d&upper=%d` ✅
**全局通知区间查询**（config log / global notify log 共用）。

| 参数 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `sid` | string | ✅ | 会话 |
| `lower` | int | ✅ | 区间下界（已处理游标） |
| `upper` | int | ✅ | 区间上界（= `max_log`） |

**响应**：XML；解析器 `CGetConfigNotifyItemInfoJson` △，字段同上（含 `device_name`/`device_uid`/`username` 校验：
`Parser deviceUID not match(%s)(%s)` / `Parser username not match(%s)(%s)` —— **必须校验归属，避免处理他人的事件**）。

### 5.4 设备配置日志
| 端点 | 参数 | 响应要点 |
|---|---|---|
| `func=qbox_get_device_config_list&sid=&user=&lower=&upper=` | `user`,`lower`,`upper` | 设备配置变更区间 |
| `func=qbox_get_device_config&sid=&device_uid=` | `device_uid` | 单设备配置；`CGetConfigItemInfoJson` ✅：`parent_id`, `receiver_number`, `original_path`, `target_name`, `team_folder` |
| `func=qbox_save_device_config&sid=&device_uid=&user=&apply=1[&config_number=%d]` | | **上报本设备配置** |
| `func=qbox_reset_device_config&sid=&user=&device_uid=&mode=1` | | 重置 |

### 5.5 ★ `GET ...?func=qbox_write_log&sid=&filepath=&action=%d` ✅
**客户端主动写日志** —— 本地改动后必须调用，否则其它设备看不到。

| 参数 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `sid` | string | ✅ | 会话 |
| `filepath` | string | ✅ | 发生变更的文件路径 |
| `action` | int | ✅ | 动作码 **[未确认具体取值]** |

> 这是唯一由 `QsyncLib.dll` 调用的 `qbox_write_log`（`@0x5d2fe0`）。**`action` 的枚举值需要动态确认**。

### 5.6 同步状态上报
| 端点 | 参数 | 含义 |
|---|---|---|
| `func=qbox_sync_start&sid=&channel=%d` | `channel` | 开始同步（告知服务端） |
| `func=qbox_sync_done&sid=&number=%d` | `number` | 同步完成，回传已处理条数 |

### 5.7 事件 / 我的事件
| 端点 | 参数 | 响应解析器 |
|---|---|---|
| `func=qbox_get_my_event&sid=&event_type=%d&lower=%d&upper=%d` | 事件类型 + 区间 | `CShareGetEventJson` △ |
| `func=qbox_remove_event&sid=&event_id=%d` | `event_id` | — |
| `func=qbox_team_folder_get_list&sid=&event_status=0&event_type=%d&lower=%d&upper=%d` | | `CShareGetTeamFolderJson` △ |

---

## §6 列举与元数据

> 全部 `GET`、需 `sid`、返回 **JSON**。

### 6.1 ★ `func=get_list` —— 列目录 ✅
| 参数 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `sid` | string | ✅ | 会话 |
| `path` | string | ✅ | 目录绝对路径例如 `/share/Photos` |
| `is_iso` | const `0` | ✅ | 固定 0 |
| `list_mode` | const `all` | ✅ | 固定 `all` |
| `dir` | string | ✅ | `ASC` / `DESC` |
| `limit` | int | ✅ | 分页大小 |
| `sort` | string | ✅ | 排序键，Qsync 用 `filename` |
| `start` | int | ✅ | 分页起始下标（0 基） |
| `no_sort` | int | ✅ | 置 1 关闭排序 |
| `type` | const `4` | 变体 | 附加形态（Qsync 某些场景用） |
| `hidden_file` | const `1` | 可选 | 包含隐藏文件。**出现在 `QFileSync.dll`（同步引擎）的模板里；`QsyncAPI.dll`（Qfile 客户端）的模板没有此参数** —— 建议始终带上，服务端通常忽略未知参数 |

**响应**：JSON；解析器 `CGetFolderInfoJson` / `CGetNodeInfoJson` △
```jsonc
{
  "status": 0,
  "datas": [                       // ★ 目录项数组
    {
      "filename":     "a.txt",     // 文件名
      "filesize":     "12345",     // 大小（字符串承载 64 位）
      "isfolder":     0,           // 0=文件 1=目录
      "epochmt":      1712345678,  // 修改时间（epoch 秒）
      "have_child":   0,           // 目录是否有子项
      "exist":        1,           // 是否存在
      "privilege":    3,           // 权限位
      "qbox_type":    0,           // Qsync 类型
      "qbox_share_id":"",          // 共享 ID
      "thumbnail":    ""           // 缩略图
    }
  ],
  "total":           123,          // 条目总数（分页用）
  "Max_File_List":   1000,         // 单次列表上限
  "epochmt":         1712345678,
  "exist":           1,
  // 以下为服务端能力位（各端点可能都带）
  "home_folder_enable": 1, "recycle_bin_enable": 1,
  "device_db_exist": 1, "log_db_exist": 1, "share_db_exist": 1,
  "qbox_versioning_enable": 1, "versioning_enable": 1, "versioning_version": 1,
  "user_enable": 1, "is_recovering": 0, "home_folder_available": 1,
  "qbox_function_enable": 1, "qbox_user_enable": 1,
  "home_is_exist": 1, "team_folder_is_exist": 0,
  "qbox_cluster_support": 0, "qbox_cluster_status": 0, "qbox_cluster_slave_id": "",
  "max_log": 100, "notify": 0, "global_notify": 0, "sync_signal": 0
}
```
**分页**：`start += len(datas)` 直到 `len(datas) < limit` 或 `start >= total`。
**LAN 优化**：连接类型会影响 `limit`（`SetGetNodeListLimit` / `GetNodeListLimit`）—— 局域网可一次拉更多。

### 6.2 `func=get_tree` —— 树形列举 ✅
| 参数 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `sid` | string | ✅ | |
| `is_iso` | const `0` | ✅ | |
| `node` | string | ✅ | 起始节点路径（懒加载子树） |

响应 JSON，结构同 §6.1 的 `datas`，但只含直属子节点。

### 6.3 ★ `func=stat` —— 单文件/目录状态 ✅
三种形态：

**(a) 查询状态（最常用）**
```
func=stat&sid=&path=&file_total=1&file_name=[&get_privilege=1]
```
| 参数 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `sid` | string | ✅ | |
| `path` | string | ✅ | 所在目录绝对路径 |
| `file_name` | string | ✅ | 文件名 |
| `file_total` | const `1` | ✅ | 单文件固定 1 |
| `get_privilege` | const `1` | 可选 | 返回权限信息 |

**(b) 设置修改时间**
```
func=stat&sid=&settime=1&mtime=%s&path=&file_total=1&file_name=
```
| 参数 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `settime` | const `1` | ✅ | 启用设时间 |
| `mtime` | string | ✅ | **epoch 秒（字符串）** |
| 其余 | | | 同上 |

**(c) 旧版 `/qsyncsrv.fcgi?func=stat`** 形态相同。

**响应**：JSON；解析器 `CGetPathInfoJson` ✅
```jsonc
{
  "status": 0,
  "total": 1,
  "exist": 1,                    // 是否存在
  "epochmt": 1712345678,         // 修改时间
  "versioning_support": 1,       // 是否支持版本化 ★
  "privilege_ex": 3,             // 扩展权限
  "datas": [ /* 同 §6.1 的条目结构 */ ],
  "error_code": 0,
  "auth_pass": ""                // 需要二次鉴权时的凭据
}
```
> `versioning_support` 是**决定是否走 delta 的关键位**（配合 `versioning_stat_delta`）。

### 6.4 `func=properties` ✅
```
func=properties&sid=&path=&total=1&name=
```
响应 JSON，含文件属性（大小、时间、类型、EXIF 等）。

### 6.5 `func=get_thumb` —— 缩略图 ✅
```
func=get_thumb&sid=&path=&name=&size=%u&option=3
```
| 参数 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `path` | string | ✅ | 目录 |
| `name` | string | ✅ | 文件名 |
| `size` | uint | ✅ | 边长像素 |
| `option` | const `3` | ✅ | 选项，固定 3 |

响应为**图片二进制**（非 JSON/XML）。

### 6.6 `func=qbox_check_permission` —— 上传前权限预检 ✅
| 参数 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `sid` | string | ✅ | |
| `path` | string | ✅ | 目标目录 |
| `file_name` | string | 可选 | 目标文件名（新版模板有，旧版无） |
| `check_upload` | const `1` | ✅ | 检查上传权限 |

响应 JSON；解析器 `CWFMPermissionCheckJson` △。返回无权时对应错误
`WFMDownloadFileToHandle: WFMQsyncCheckPermission(%s) WFM_PERMISSION_DENY`。

### 6.7 `func=check_file_present` / `func=check_permission` △
`QFileIsPathPresent` / `QFileCheckAuth` 的底层。参数与 `stat` 类似。**响应字段未确认** —— 用 probe 确认。

---

## §7 写操作

> 这些端点模板**没有 query**，参数在 **POST body**。响应统一为 JSON，含 `status`（0=成功）。

| # | 端点 | 参数（body） | 响应/备注 |
|---|---|---|---|
| W1 | `func=createdir` | `sid`, `dest_folder`(新目录名), `dest_path`(父目录)；旧版仅 `sid`+body | JSON `{status}` |
| W2 | `func=rename` | `sid` + body：`path`, `filename`, `dest_name` △ | JSON `{status}` |
| W3 | `func=move` | `sid`[,`no_fork=%d`] + body：`path`, `filename`, `dest_path`, `dest_name` △ | `no_fork=1` 时同步执行（不 fork 后台进程）；异步时返回 `pid` 用 §4 S19 查询 |
| W4 | `func=delete` | `sid` + body：`path`, `file_name`/`file_total` △ | JSON `{status}` |
| W5 | `func=trash_recovery` | `sid`, `source_file`, `mode=%d`, `source_total=1`, `source_path` | 从回收站恢复；解析器 `CGetTrashRecoveryJson` ✅：`recycle_bin_enable`, `event_action`, `event_duid` |
| W6 | `func=repository_recovery` | `sid`, `source_file`, `mode=%d`, `source_path`, `version_id`, `dest_path`, `versioning_version=1` | 从**版本库**恢复指定版本 |
| W7 | `func=qbox_fix_team_folder_link` | `sid`, `path`[, `type=4`] | 修复团队文件夹链接；`CShareGetPathJson` ✅：`share_path`, `auth_result` |
| W8 | `func=qbox_set_recycle_bin` | `recycle_bin=%d`, `sid` | 开关回收站 |
| W9 | `func=qbox_set_policy` | `share_policy=%d`, `sid` | 设置共享策略 |
| W10 | `func=qbox_rename_device` | 见 §11 设备 | 旧式 `utilRequest` 专用 |

**[未确认]** W2/W3/W4 的 body 字段名 —— 字符串区存在 `dest_name`、`filename`、`file_total`、`source_total` 等键，
但未逐一定位。**开发时先用 probe 抓一次**（一次 `rename` 请求即可确定全部 body 字段）。

---

## §8 上传

### 8.1 ★ 一次性上传 + 原子改名：`func=upload_and_move` ✅（**推荐主路径**）
```
POST func=upload_and_move&sid=&settime=1&mtime=%s&filesize=%s&dest_path=%s
     &overwrite=%d[&rename_dest=%s]&upload_root_dir=%s[&check_qbox_file_profile=1
     &check_qbox_file_exist=%d&check_qbox_file_type=0&check_qbox_file_path=%s]
```
| 参数 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `sid` | string | ✅ | 会话 |
| `settime` | const `1` | ✅ | 设 1 表示同时设置 mtime |
| `mtime` | string | ✅(settime=1) | **epoch 秒** |
| `filesize` | string | ✅ | 本次上传字节数（64 位字符串） |
| `dest_path` | string | ✅ | 目标目录绝对路径 |
| `overwrite` | int | ✅ | 0/1 |
| `rename_dest` | string | 可选 | 落地后的目标文件名（**先传临时名再原子改名，避免中间态被其它设备看到**） |
| `upload_root_dir` | string | ✅ | 服务端临时上传根目录 |
| `check_qbox_file_profile` | const `1` | 可选 | 启用 profile 校验 |
| `check_qbox_file_exist` | int | 可选 | 是否校验目标已存在 |
| `check_qbox_file_type` | const `0` | 可选 | 类型校验模式 |
| `check_qbox_file_path` | string | 可选 | 校验用路径 |

**Body**：`multipart/form-data`（文件字段由 `upload.php` / libcurl `curl_formadd` 提交）。

### 8.2 ★ 分块上传（大文件 / 断点续传）✅
```
① POST func=start_chunked_upload&sid=&upload_root_dir=[&check_qbox_file_*]
   → 响应 JSON，解析器 CGetUploadIDJson ✅：{ "status":0, "upload_id":"..." }

② POST func=chunked_upload&sid=&upload_id=&settime=1&mtime=%s&offset=%s
        &filesize=%s&dest_path=&overwrite=%d[&rename_dest=]&upload_root_dir=
   → 每片：offset=本片起始字节，filesize=本片字节数

③ GET  func=get_chunked_upload_status&sid=&upload_id=&upload_root_dir=
   → 响应 JSON，解析器 CGetUploadChunkResultJson ✅：{ "status":0, "files":[ ... ] }
     （files 里给出已接收的分片/字节，用于计算续传 offset）

④ 放弃：GET func=delete_chunked_upload_file&sid=&upload_id=&upload_root_dir=
```
**辅助能力位**（客户端用于决定分片）：`CQsyncSyncDll::GetMaxFileSize()`、`MultiPartFileSize`、
`WFMQsynGetChunkFileSize`。**[未确认]** 分片大小与 multipart 阈值（需抓包）。

### 8.3 简单上传 `func=upload` / `upload.php` ✅
```
POST func=upload&sid=&dest_path=&overwrite=%d      （无 rename_dest）
POST /cgi-bin/{qsync,filemanager}/upload.php
```
适合小文件；无原子改名保证。

### 8.4 上传前预检顺序 **[推] △**
```
1. func=qbox_check_permission&check_upload=1     → 权限
2. 若文件已存在 → func=stat 取 mtime/size → 决定走 delta(§10) 还是整文件
3. 大文件 → 8.2 分块；小文件 → 8.1 upload_and_move
4. 完成后 func=stat&settime=1&mtime=     对齐时间戳
```

---

## §9 下载

### 9.1 ★ `func=download` ✅
```
GET /cgi-bin/qsync/qsyncsrv.cgi?func=download&sid=&path=&file_name=   (旧式: utilRequest.cgi)
Header: Range: bytes=<start>-<end>          ← 分段/续传
```
| 参数 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `sid` | string | ✅ | 会话 |
| `path` | string | ✅ | 文件所在目录 |
| `file_name` | string | ✅ | 文件名 |

**响应**：**文件二进制流**（非 JSON/XML）。响应头含
```
Content-Range: bytes <start>-<end>/<total>
```
（**[已确认]** 字面量 `Content-Range: bytes %llu-%llu/%llu`）
校对：客户端会校验 `Content-Length` 与预期一致，否则报
`WFMDownloadFileToHandle: response size mismatch(...)`。

### 9.2 `func=download_file` ✅
`QFileSync` 中出现的等价变体（`/func=download_file`），参数与 §9.1 相同。**建议两个都试。**

### 9.3 局域网快路径（WebSocket）△
不走 HTTP：`CQWebSocketConnection` 在 `ws://` / `wss://` 上用自定义二进制命令
`LANDownloadFile` / `LANCheckAlive` / `LANCheckFilePresent` / `LANCheckPermission`，
握手 `Auth1` + `Auth2`。**第一版不必实现**。

### 9.4 下载完成动作 ✅
```
GET func=stat&sid=&settime=1&mtime=<epoch>&path=&file_total=1&file_name=
```
（若目标连接支持，改用 WebDAV `PROPPATCH` 写入 `Win32LastModifiedTime` 等，见 01 篇 §1.4c）

---

## §10 版本化 / delta

> 完整时序见 [06 篇 §6.5](06-增量传输与版本化.md)。**注意：`source_path` 与 `source_file` 必须分开传。**

### 10.1 端点表 ✅
| # | 端点 | 参数 | 响应解析器 |
|---|---|---|---|
| V1 | `func=versioning_lock&create_version=1` | `sid`, `source_path`, `source_file` | `CGetVersioningLockResultJson` ✅ |
| V2 | `func=versioning_lock&check_version=1` | `sid`, `source_path`, `source_file`, `version_id`, `lockid` | 同上 |
| V3 | `func=versioning_unlock` | `sid`, `source_path`, `source_file`, `lockid` | JSON `{status}` |
| V4 | `func=versioning_gen_sig` | `sid`, `source_path`, `source_file`, `lockid`, `version_id` | `CGenVersioningSigJson` ✅ |
| V5 | `func=versioning_get_sig` | `sid`, `source_path`, `source_file`, `lockid`, `version_id` | **signature 二进制** |
| V6 | `func=versioning_stat_delta` | `sid`, `source_path`, `source_file`, `version_id`（**无 lockid**） | `CStatDeltaJson` ✅ |
| V7 | `func=versioning_gen_delta` | `sid`, `source_path`, `source_file`, `lockid`, `version_id` | JSON `{status}` |
| V8 | `func=versioning_get_delta` | `sid`, `source_path`, `source_file`, `lockid`, `version_id`, `offset` | **delta 二进制** |
| V9 | `func=versioning_upload_file` | `sid`, `dest_path`, `overwrite`, `version_id`, `versioning_version=1`, `source_file`, `offset`, `upload_name`, `filesize` | JSON `{status}` |
| V10 | `func=versioning_commit_upload` | `sid`, `settime=1`, `mtime`, `source_path`, `source_file`, `lockid`, `version_id` | JSON `{status}` |
| V11 | `func=versioning_clean_version` | `sid`, `source_path`, `source_file`, `lockid`, `version_id` | JSON `{status}` |
| V12 | `func=versioning_probe` | `sid` | JSON（**同步引擎不用，仅 Qfile 客户端**） |
| V13 | `func=versioning_stat` | `sid` 或 `sid`+`source_path`+`source_file` | JSON |
| V14 | `func=versioning_gen_file` | `sid` | JSON |
| V15 | `func=versioning_delete_all` | `sid` | JSON |

### 10.2 关键响应字段 ✅
```jsonc
// V1/V2  versioning_lock
{ "status":0, "lockid":"...", "version_id":"..." }        // ★ 后续步骤都依赖这两个

// V4      versioning_gen_sig
{ "status":0, "versioning_version":1 }

// V6      versioning_stat_delta
{ "status":0, "<标志位>":1, "<64位量A>":..., "<64位量B>":... }
// ★ 客户端判定：标志位非 0 且 A 严格大于 B 才走 delta（字段名未确认，见 06 篇 §6.6）
```
**signature / delta 文件格式**（librsync 原生，全大端）：
```
signature : 0x72730136 | block_len(u32) | strong_sum_len(u32) | [ weak(u32) | MD4(strong_sum_len) ]*
delta     : 0x72730236 | 命令流
            0x00 = END
            0x41..0x44 = LITERAL_{1,2,4,8}  + 大端长度 + 原始字节
            0x45..0x54 = COPY_{where{1,2,4,8}}{len{1,2,4,8}} + 大端 where + 大端 len
```
参数固定 **block_len = 1 MiB（0x100000）**、**strong_sum_len = 16**。

### 10.3 版本浏览 ✅
| 端点 | 参数 |
|---|---|
| `func=get_backup_file_list` | `sid`, `source_path`, `filter`, `timestamp`, `show_deleted=%d`, `limit`, `start` |
| `func=get_list ... &get_versioning=1` | 列目录时顺带返回版本化标志 |

---

## §11 共享 / 团队文件夹（28 个）

> 参数已全部确定（见下表）。响应解析器列在最后一列；字段归属多为 △。

### 11.1 分享链接
| # | 端点 | 参数 | 解析器 |
|---|---|---|---|
| H1 | `func=get_share_link` | `sid` | `CWebFileManGetLinkXml` → **XML** |
| H2 | `func=get_share_list` | `sid`, `dir=ASC`, `limit`, `sort=filename`, `start` | `CShareLinkListJson` △ |
| H3 | `func=share_file` | `sid` + body | `CWebFileManCreateLinkXml` → **XML** |
| H4 | `func=update_share_link` | `sid` + body | JSON |
| H5 | `func=update_link` | `sid` + body | JSON |
| H6 | `func=delete_share` | `sid`, `ssids`, `file_total=%d`（批量）<br>`sid`, `filename`, `download_link`, `file_total=%d`（单个） | JSON |
| H7 | `func=send_share_mail` | `sid` + body | JSON |
| H8 | **独立 CGI**（非 func） | `POST share.cgi?ssid=<ssid>` 或 `GET /share.cgi?func=get_list&ssid=<ssid>` | **无需登录**（公开分享） |
| — | 分享链接响应字段（`CGetFolderInfoJson`/`CWebFileManGetLinkXml` 簇）△ | `ssid`, `link_url`, `protocol`, `link_name`, `expire_time`, `multiple`, `links`, `download_type`, `addressee`, `subject`, `content`, `access_enabled`, `include_access_code`, `network_type`, `valid_duration`, `mail_content_pwd`, `internet`, `local`, `new_share`, `create_download_link`, `email_download_link`, `forever`, `specific_time`, `period_of_time`, `datetime`, `ssl`, `user_number`, `folder_number`, `target_number`, `option`, `template` | |

### 11.2 共享成员
| # | 端点 | 参数 |
|---|---|---|
| H9 | `func=qbox_get_share_member` | `sid`, `user_type`, `share_id`, `lower`, `upper`, `all_user`, `refresh`, `netbios`, `domain`, `filter` |
| H10 | `func=qbox_get_user_list` | `sid`, `user_type`, `all_user`, `refresh`, `lower`, `upper`, `netbios`, `domain`, `filter` |
| H11 | `func=qbox_set_share_member` | `sid` + body |
| H12 | `func=qbox_share_to` | `sid` + body |
| H13 | `func=qbox_unshare` | `sid`, `share_id` |
| H14 | `func=qbox_get_share_info` | `sid`, `file` |
| H15 | `func=qbox_get_share_path` | `sid`, `share_id` |
| H16 | `func=qbox_find_share` | `sid`, `file`, `lower`, `upper` |
| H17 | `func=qbox_accept_share` | `sid`, `event_id` |
| H18 | `func=qbox_deny_share` | `sid`, `event_id` |
| H19 | `func=qbox_leave_share` | `sid`, `event_id` |
| H20 | `func=qbox_kickout_share` | `sid`, `share_id`（qsyncsrv 版；utilRequest 版用 `event_id`） |

### 11.3 团队文件夹
| # | 端点 | 参数 |
|---|---|---|
| H21 | `func=qbox_team_folder_get_list` | `sid`, `event_status=0`, `event_type`, `lower`, `upper` |
| H22 | `func=qbox_team_folder_get_info` | `sid`, `path` |
| H23 | `func=qbox_team_folder_get_member` | `sid`, `user_type`, `share_id`, `lower`, `upper`, `all_user`, `refresh`, `netbios`, `domain`, `filter` |
| H24 | `func=qbox_team_folder_set_member` | `sid` + body |
| H25 | `func=qbox_team_folder_share_to` | `sid` + body |
| H26 | `func=qbox_team_folder_accept_share` | `sid`, `display_name`, `share_id` |
| H27 | `func=qbox_team_folder_deny_share` | `sid`, `share_id` |
| H28 | `func=qbox_team_folder_leave_share` | `sid`, `share_id` |
| H29 | `func=qbox_team_folder_unshare_ex` | `sid`, `share_id` |

### 11.4 共享文件信息 / ACL
| 端点 | 参数 | 解析器 |
|---|---|---|
| `func=qbox_get_config_acl` | `sid` | `CGetConfigACLInfoJson` ✅：`section`, `config`, `all` |
| `func=qbox_auth_config_password` | `sid`, `password` | `CAuthConfigPasswordJson` ✅：`time_error`, `email_error` |
| `func=get_ad_info` | `sid` | `CShareGetAdInfoJson` ✅：`netbios`, `TrustedDomainEnable` |

### 11.5 设备配置
| 端点 | 参数 |
|---|---|
| `func=qbox_get_device_config_list` | `sid`, `user`, `lower`, `upper` |
| `func=qbox_get_device_config` | `sid`, `device_uid` |
| `func=qbox_save_device_config` | `sid`, `device_uid`, `user`, `apply=1`[, `config_number`] |
| `func=qbox_reset_device_config` | `sid`, `user`, `device_uid`, `mode=1` |

---

## §12 备份（8 个）

| # | 端点 | 参数 |
|---|---|---|
| B1 | `func=qbox_backup_start` | `sid`, `channel=%d` |
| B2 | `func=qbox_backup_done` | `sid`, `number=%d` |
| B3 | `func=qbox_check_backup_folder` | `sid`, `path` |
| B4 | `func=qbox_set_backup_folder` | `sid`, `path`, `action=%d` |
| B5 | `func=qbox_clean_backup_folder` | `sid`, `path` |
| B6 | `func=qbox_remove_backup_folder` | `sid`, `path` |
| B7 | `func=qbox_set_backup_finish_time` | `sid`, `path`, `time` |
| B8 | `func=get_backup_file_list` | `sid`, `source_path`, `filter`, `timestamp`, `show_deleted=%d`, `limit`, `start` |

响应统一 JSON，`{status}`；`get_backup_file_list` 返回文件+版本列表。

---

## §13 鉴权（共享文件夹两步验证，4 个）

> 涉及 AES 封装（`auth_data` + `iv`），**细节未完全还原**（见 02 篇 §2.4）。普通用户主目录不使用这组。

| # | 端点 | 参数 | 解析器 |
|---|---|---|---|
| A1 | `func=auth_1` | body：`auth_data=%s`, `iv=%s`(+ `file_path`, `local_user_uid`, `nas_uid`, `share_folder_uid`, `file_time`, `file_size`, `digest`) | `CAuth1Json` ✅：`server_busy`, `auth_data`, `iv` |
| A2 | `func=auth_2` | body：同上 + `share_folder_sid` | `CAuth2Json` ✅：`share_folder_sid` |
| A3 | `func=sharefolder_auth_1` | 同上 | 同 A1 |
| A4 | `func=sharefolder_auth_2` | 同上 | 同 A2 |

**两步含义**：`auth_1` 用本地凭据换 `auth_data`/`iv`（AES 密文），`auth_2` 用其换 `share_folder_sid`（共享文件夹会话）。
**开发建议**：Linux 客户端第一版**只支持用户主目录**，绕过这组；共享文件夹留待动态验证后再做。

---

## §14 云账号（QID / myQNAPcloud）—— **JSON**

> 与 NAS API 完全独立。**第一版可以不做**（用户手填 NAS 地址即可）。

### 14.1 OAuth2 取 token ✅
```
POST {account}/oauth/token
Content-Type: application/x-www-form-urlencoded
```
| grant | Body |
|---|---|
| 授权码（**主路径，带 PKCE**） | `grant_type=authorization_code&client_id=&client_secret=&code=&code_verifier=&redirect_uri=` |
| 刷新 | `grant_type=refresh_token&client_id=&client_secret=&refresh_token=` |
| 客户端凭据 | `grant_type=client_credentials&client_id=&client_secret=` |
| 密码 | `grant_type=password&client_id=&client_secret=&username=&password=`（**属 DCS 打点服务，非账号站登录**） |

**响应（JSON）** ✅
```jsonc
{ "access_token":"...", "refresh_token":"...", "token_type":"Bearer",
  "expires_in":3600, "error":"", "error_description":"" }
```
固定凭据：`client_id=593a4f08d6b82f791bacd7db`；`client_secret` 公开版已掩码（见下方说明）

> ⚠️ **公开版掩码说明**：`client_secret` 的完整值已从报告中移除，以免在公开仓库散布第三方凭据
> （GitHub secret scanning 也会因此报警）。完整值可从**你自己合法获得的** Qsync 安装包直接提取：
> ```bash
> ./tools/reveal-credentials.sh "/path/to/Qsync/Qsync.exe"
> # 或按文件偏移查看：Qsync.exe 偏移 0x002f0e98 附近
> ```
> `client_id` 是客户端标识（非密钥），保留原文。

### 14.2 授权入口 ✅
```
GET {account}/oauth/auth?response_type=code&client_id=&redirect_uri=&code_challenge_method=S256&code_challenge=
GET {account}/signin?create=0&state=&hide_signup=true&hide_social=true&hide_forget_password=true
                    &hide_activation_mail=true&switch_account=true
本地回调: http://127.0.0.1:{4300|4343|14300|14343}/oauth2/callback?code=
```

### 14.3 用户 / 设备 ✅
```
GET {account}/oauth/tokeninfo?access_token=<token>
    → { user, email, id, display_name }
GET {core2}/v1.1/me
    → { result, user, email, display_name, first_name, last_name,
        organization_id, organization_name, organization_site_name, limit, offset }
GET {core2}/v1.1/device          → { code, result, info, error, <设备数组> }
GET {core2}/v1.1/device/search?device_name=
GET {core2}/v1.1/device/count
GET {core2}/v1.1/device/{id}/network
GET {core2}/v1.1/utility/geo/search
GET {core2}/v1.2/device
GET {core2}/v1.2/device/sharedtome
GET {core2}/v1/services/vlink/{linkId}
GET {core2}/v1/devices/services/portMapping/{deviceId}
GET {core2}/api/v1/authorizes/q_token
Headers: X-QNAP-APP-ID / X-QNAP-SUBAPP-ID / X-QNAP-APP-VER / X-QNAP-TIME / X-QNAP-CHECK
         Authorization: Bearer <access_token>   Accept: application/json
```
**设备对象字段** ✅（解析器 `CQIDGetAllDeviceInfoJson`）：
```jsonc
{
  "device_id":"", "device_name":"", "host_name":"", "device_type":"",
  "model_name":"", "fw_model_name":"", "mac_address":"", "cluster_uid":"",
  "firmware_version":"", "firmware_number":"", "firmware_build_number":"",
  "firmware_patch_version":"", "latest_fw_version":"", "agent_version":"",
  "fw_serial_number":"", "hw_serial_number":"", "region":"", "domain_name":"",
  "lan_ips":[{"ipv4":"","ipv6":""}], "lan_gateway":"",
  "wan_ips":[{"ipv4":""}],
  "local_services":[{"service_name":"WebAdministration","internal_port":8080,
                     "external_port":0,"published":1}],
  "local_users":[...], "model_info":{...},
  "permissions":..., "nickname":"", "user_name":"",
  "remote_access":..., "public_ip":"", "token":"", "uri":"",
  "passwordless_en":..., "password_en":...,
  "public_local_service":..., "private_local_service":...,
  "public_package_services":..., "private_package_services":...,
  "protected_package_services":...
}
```
`service_name` 取值示例 ✅：`WebAdministration`、`Secured WebAdministration`。

### 14.4 登出 ✅
```
{account}/oauth/signout
```

---

## §15 错误码与失败处理

### 15.1 WFM 解析/传输错误（**历史命名，JSON 解析失败也用这套**）✅
```
WFM_PARSE_XML_EMPTY_RESPONSE              响应体为空
WFM_PARSE_XML_FAIL                        解析失败
WFM_PARSE_XML_INVALID_PARAMETER           参数非法
WFM_PARSE_XML_CGI_NOT_FOUND               端点不存在（→ 切换命名空间 / 版本过旧）
WFM_PARSE_XML_INSUFFICIENT_BUFFER         缓冲不足
WFM_PARSE_XML_BUFFER_NOT_ENOUGH           
WFM_PARSE_XML_HTTPTRAN_QUERY_HTTP_HEADER_FAIL   HTTP 头解析失败
WFM_PARSE_XML_HTTPTRAN_CONNECT_FAIL       TCP 连接失败
WFM_PARSE_XML_HTTPTRAN_RECEIVE_FAIL       接收失败
WFM_PARSE_XML_HTTPTRAN_SERVICE_UNAVAIL    服务不可用（NAS 忙/Qsync 未启用）
WFM_PARSE_XML_HTTPTRAN_PROXY_AUTH_REQ     代理需要认证
WFM_FORCE_HTTPS_REDIRECT                  ★ 服务端要求改用 HTTPS（客户端应自动切换）
WFM_NEED_USER_NAME                        需要重新提供用户名（口令过期/为空）
WFM_QSYNC_DISABLED                        NAS 上 Qsync 服务未启用
WFM_QSYNC_LOG_MISSING                     ★ 日志已滚动删除 → 游标归零 + 全量重扫
WFM_QSYNC_DB_OPEN / WFM_QSYNC_SQL_EXEC    NAS 端数据库错误 → 强制重登
WFM_QSYNC_QPKG_NOT_EXIST                  未安装 Qsync QPKG
WFM_CONFIG_FILE_TYPE_DEFAULT_ALL
WFM_OUT_OF_RANGE / WFM_OPEN_FILE_FAILED
WFM_FILE_NAME_TOO_LONG                    ★ 路径过长（不可重试，需改名或跳过）
WFM_CHUNK_UPLOAD_CONTINUE                 分块上传可续传
WFM_STATUS_FAILED
WFM_PERMISSION_DENY                       权限不足
```

### 15.2 业务状态
- JSON/XML 顶层 `status`：**0 = 成功**，非 0 = 失败（配合 `error` / `error_code`）。
- 账号侧：`authPassed` 为假、`permission_deny`、`account_login_restricted`、`pw_expiry`。
- HTTP 侧：`471`/`403`/`404`/`5xx` 分别映射上面的 HTTPTRAN 系列。

### 15.3 客户端应实现的失败动作 **[推] △**
| 情况 | 动作 |
|---|---|
| `WFM_FORCE_HTTPS_REDIRECT` | 切 `https://` 重试同一请求 |
| `WFM_NEED_USER_NAME` | 重走 §3.1 登录 |
| `WFM_QSYNC_LOG_MISSING` / `max_log` 回退 | 游标归零 + 全量重扫 |
| `WFM_QSYNC_DB_OPEN` / `SQL_EXEC` | 重登（`ForceReLogin`） |
| `ERROR_ACCESS_DENIED`（`get_list`） | SID 失效 → 重登 |
| `WFM_FILE_NAME_TOO_LONG` | 跳过该文件并报错（**不要重试**） |
| `WFM_PARSE_XML_CGI_NOT_FOUND` | 切换 `qsyncsrv.cgi` ↔ `utilRequest.cgi` |
| 网络类错误 | 指数退避重试（客户端有 `retry(%d)` 计数上限） |

---

## §16 响应字段总表（按解析器）

完整机器可读清单见 [`out/parser_fields.json`](out/parser_fields.json)（43 个解析器）。
下面是开发最常用的 12 个：

| 解析器 | 主要字段 | 置信度 |
|---|---|---|
| `CGetPathInfoJson` | `status`,`total`,`exist`,`epochmt`,`versioning_support`,`privilege_ex`,`datas`,`error_code`,`auth_pass` | ✅ |
| `CGetFolderInfoJson` | `filename`,`filesize`,`isfolder`,`epochmt`,`have_child`,`exist`,`privilege`,`qbox_type`,`qbox_share_id`,`thumbnail`,`datas`,`total`,`Max_File_List` | ✅ |
| `CAuthLoginXml` | `authSid`,`authPassed`,`error_code`,`access_token_ret`,`remain`,`pw_expiry`,`permission_deny`,`account_login_restricted`,`username`,`suid`,`cuid`,`need_2sv`,`force_2sv`,`need_2_step_verification`,`security_code_en`,`qrcode_en`,`vcode_en`,`approve_login_en`,`home`,`home_folder_available` | ✅ |
| `CQsyncLogin` | `qbox_cgi`,`fcgi`,`enableACL`,`Qsync_version`,`Max_File_List`,`qbox_share_id`,`qbox_type`,`mycloudnas_dn`,`ext_ip`,`ddns_dn`,`home_section_fail`,`qbox_slave_id`,`build`,`enable`,`readonly` | △ |
| `CShareGetUIDJson` | `UID`,`SUID`,`CUID`,`MAC0`,`is_booting`,`user_type`,`is_migrating`,`is_recovering`,`is_backuping_restoring`,`DisableFastCGI`,`versioning_version`,`volume_total_size`,`volume_free_size` | △ |
| `CQsyncGetMaxLogJson` | `max_log`,`notify`,`global_notify`,`sync_signal`,`slowdown_seconds` | ✅ |
| `CGetConfigNotifyItemInfoJson` | `filename`,`filepath`,`event`,`event_type`,`event_user`,`event_time`,`event_modifier`,`event_value`,`duid`,`device_name`,`device_uid`,`share_member`,`share_path`,`thumbnail`,`action`,`log_id`,`old_filepath`,`old_size` | △ |
| `CGetSyncingFolderListJson` | `folder`,`permission`,`read_deletable`,`realpath`,`volume_id`,`slave_id`,`lock`,`enc`,`fkey`,`capacity`,`used_size`,`free_size`,`client_key` | ✅ |
| `CGetUserQuotaJson` | `quota_enable`,`quota`,`quota_size`,`used_quota_size`,`avaiable_quota_size`,`vol_id` | ✅ |
| `CGetVersioningLockResultJson` | `lockid`,`version_id` | ✅ |
| `CGetUploadIDJson` / `CGetUploadChunkResultJson` | `upload_id` / `files` | ✅ |
| `CQIDGetAllDeviceInfoJson` | 见 §14.3 | ✅ |
| `CGetDomainIPListJson` | 见 §4.1 | ✅ |

---

## §17 开发自检清单

动手前请按顺序确认这 8 项（每项都能用 [probe](probe/README.md) 在几分钟内定论）：

| # | 待确认 | 为什么重要 |
|---|---|---|
| 1 | **响应是 JSON 还是 XML**（首字符嗅探） | 决定解析器；写错则全部失败 |
| 2 | `authLogin.cgi` 的口令字段名与是否 AES 封装 | 决定登录能否跑通 |
| 3 | 两套命名空间（`qsyncsrv.cgi` vs `utilRequest.cgi`）哪套可用 | QTS 版本差异 |
| 4 | `rename`/`move`/`delete` 的 POST body 字段名 | 写操作正确性 |
| 5 | `qbox_get_sync_log` 的 `number` 批量值与轮询间隔 | 实时性与性能 |
| 6 | `func=download` 的分片大小与 `Range` 语义 | 大文件下载正确性 |
| 7 | 分块上传的分片大小与 `upload_root_dir` 取值 | 大文件上传正确性 |
| 8 | `qbox_write_log` 的 `action` 枚举 | 其它设备能否看到你的改动 |

**建议的编码顺序**：§3 登录 → §6 列举/stat → §9 下载 → §8 上传 → §5 变更发现 → §10 delta（可选）→ §11/§12（按需）
