# 04 · API 参考手册

> 本文列出 Qsync Windows 客户端实际使用的**全部**远程 API。
> 数据来源：`out/endpoints_clean.txt`（322 条去重后的 URL 模板，从 `QsyncAPI.dll` / `QFileSync.dll` / `QsyncLib.dll` / `Qsync.exe` 的 `.rdata` 字面量提取）。
> 所有模板中的 `%ls`/`%s` 为 C `printf` 占位符；`%d`/`%u` 为整数。

## 4.0 通用约定

### URL 构造
```
{scheme}://{host}:{port}/{prefix}cgi-bin/...
  scheme  ∈ { http://, https:// }
  prefix  ∈ { "", "qsync/" }   ← 运行时决定：直连 NAS 为空；经 myQNAPcloud/反向代理时非空
```
**[已确认]** 模板中第 3 个 `%ls` 即该 prefix，例如：
```
%ls%ls:%d/%lscgi-bin/qsync/qsyncsrv.cgi?...
      ↑host ↑port ↑prefix
```

### 两套命名空间（同一功能的两条路径）
| 新版（QTS 5.x / Qsync QPKG） | 旧版（内建 WFM） |
|---|---|
| `/cgi-bin/qsync/qsyncsrv.cgi` | `/cgi-bin/filemanager/utilRequest.cgi` |
| `/cgi-bin/qsync/qsyncsrv.fcgi` | — |
| `/cgi-bin/qsync/qsyncsrvPrepare.cgi` | `/cgi-bin/filemanager/qsyncPrepare.cgi` |
| `/cgi-bin/qsync/qsyncsrv_login.cgi` | `/cgi-bin/filemanager/wfm2Login.cgi` |
| `/cgi-bin/qsync/qsyncsrv_logout.cgi` | `/cgi-bin/filemanager/wfm2Logout.cgi` |
| `/cgi-bin/qsync/upload.php` | `/cgi-bin/filemanager/upload.php` |

**[强推断]** 客户端先试 `qsyncPrepare.cgi`（探测 Qsync QPKG 是否存在），404 → `bPrepareCGINotFound=1` → 回退到 `utilRequest.cgi`。这与 `CQWebManConnection::NASLogin(...)(bPrepareCGINotFound=%d)` 日志一致。

### 所有请求共享
- 会话参数：`sid`（必带，除登录接口）
- 内容类型：`application/x-www-form-urlencoded`（普通）；文件上传为 `multipart/form-data`（`curl_formadd`）
- 附加头：`X-Forwarded-For`、`Connection: Keep-Alive`、`Cache-Control: no-cache`、`Accept`
- 响应格式：**JSON 为主（jsoncpp 解析，`C*Json` 类），少数 CGI 是 XML（TinyXML，`*Xml` 类）**
  - `*Xml` 仅 8 个类：`CAuthLoginXml` / `CSecurityQuestionXml` / `CSendSecurityCodeXml` /
    `CSysInfoXml` / `CQsyncQPKGXml` / `CWebFileManGetLinkXml` / `CWebFileManCreateLinkXml`
  - **实现建议：按首字符嗅探**（`{`/`[` → JSON，`<` → XML），不要写死
  - 形如 `[WFM] WFM_PARSE_XML_*` 的错误码是**历史命名**，对 JSON 解析失败也使用，不可据此判断格式
  - 详见 [11 篇 §0.5](11-API规格书.md)

### 通用错误码（WFM 层）
**[已确认]** `WFM_PARSE_XML_*` 枚举（字符串可见）：
```
WFM_PARSE_XML_EMPTY_RESPONSE        WFM_PARSE_XML_FAIL
WFM_PARSE_XML_INVALID_PARAMETER     WFM_PARSE_XML_CGI_NOT_FOUND
WFM_PARSE_XML_EMPTY_RESPONSE        WFM_PARSE_XML_INSUFFICIENT_BUFFER
WFM_PARSE_XML_HTTPTRAN_PROXY_AUTH_REQ
WFM_PARSE_XML_HTTPTRAN_SERVICE_UNAVAIL
WFM_PARSE_XML_HTTPTRAN_CONNECT_FAIL
WFM_FORCE_HTTPS_REDIRECT            WFM_NEED_USER_NAME
WFM_QSYNC_DISABLED                  WFM_QSYNC_LOG_MISSING
WFM_QSYNC_DB_OPEN                   WFM_QSYNC_SQL_EXEC
WFM_CONFIG_FILE_TYPE_DEFAULT_ALL    WFM_OUT_OF_RANGE
WFM_CHUNK_UPLOAD_CONTINUE           WFM_OPEN_FILE_FAILED
WFM_FILE_NAME_TOO_LONG              WFM_STATUS_FAILED
WFM_PARSE_XML_INVALID_PARAMETER
```

---

## 4.1 登录 / 会话

| # | 方法 | 端点 | 关键参数 | 说明 |
|---|---|---|---|---|
| A1 | POST | `/cgi-bin/authLogin.cgi` | 见 02 篇 2.2 节 | QTS 账号登录取 `authSid` |
| A2 | POST | `/cgi-bin/authLogin.cgi?func=passwordless&op=8` | — | **免密登录**（QsyncLib） |
| A3 | POST | `/cgi-bin/qsync/qsyncsrv_login.cgi` | `user`,`qbox_user`,`qbox_computer`,`qbox_device_type`,`Qsync_client_version` | Qsync 层登录，取 `q_token` |
| B3 | POST | `/cgi-bin/qsync/qsyncsrv.fcgi?func=login` | 同上 | 等价端点 |
| C3 | POST | `/cgi-bin/filemanager/wfm2Login.cgi` | 同上 | 旧版等价端点 |
| A4 | GET | `/cgi-bin/qsync/qsyncsrvPrepare.cgi?user=%s` | `user` | 取 NAS UID / CUID / UserCUID |
| B4 | GET | `/cgi-bin/filemanager/qsyncPrepare.cgi?user=%s` | `user` | 旧版 |
| A5 | GET | `/{prefix}cgi-bin/qsync/qsyncsrvPrepare.cgi?func=activate&token=%s` | `func=activate`,`token` | 激活 SID，返回 server name / is admin group |
| A6 | GET | `/cgi-bin/authLogout.cgi?sid=%s&logout=1` | `sid` | 登出 |
| A7 | GET | `/cgi-bin/qsync/qsyncsrv_logout.cgi?sid=%s&logout=1` | `sid` | Qsync 登出 |
| A8 | GET | `/cgi-bin/qsync/qsyncsrv.fcgi?func=logout&sid=%s&logout=1` | | 等价 |
| A9 | GET | `/cgi-bin/filemanager/wfm2Logout.cgi?sid=%s&logout=1` | | 旧版登出 |
| A10 | GET | `/cgi-bin/sysinfoReq.cgi?subfunc=info&sid=%s` | `subfunc=info` | 系统信息 |
| A11 | GET | `/cgi-bin/application/appRequest.cgi?subfunc=qpkg&apply=10&sid=%s` | `subfunc=qpkg`,`apply=10` | QPKG 管理（用于确认 Qsync QPKG 状态） |

---

## 4.2 Qsync 会话状态 / 连接探测

| # | 端点 | 参数 | 说明 |
|---|---|---|---|
| S1 | `func=qbox_get_qbox_info&sid=` | | Qsync 服务端信息（是否启用、版本等） |
| S2 | `func=qbox_get_nas_status&sid=` | | NAS 状态 |
| S3 | `func=qbox_get_nas_status&sid=&check_detail=%d` | `check_detail` | 带详情 |
| S4 | `func=qbox_get_static_information&sid=` | | NAS 静态信息（型号、固件、队列上限） |
| S5 | `func=qbox_get_quota_info&sid=` | | 配额 |
| S6 | `func=qbox_get_nas_uid&sid=` | | NAS 唯一 ID（用于配对校验） |
| S7 | `func=qbox_get_system_sid&sid=` | | 系统 SID |
| S8 | `func=qbox_get_policy&sid=` | | 共享策略 |
| S9 | `func=qbox_get_config_acl&sid=` | | 配置 ACL 位图（决定客户端可改哪些设置） |
| S10 | `func=qbox_get_veto_files&sid=` | | 服务端排除文件列表（veto = 不同步的黑名单） |
| S11 | `func=qbox_get_recycle_bin_status&sid=` | | 回收站状态 |
| S12 | `func=qbox_get_last_modify_time&sid=` | | 服务端配置最后修改时间 |
| S13 | `func=qbox_get_registry&sid=` | | 服务端注册表快照 |
| S14 | `func=get_domain_ip_list&sid=` | | **域名→IP 列表**（用于地址回退，见 07 篇） |
| S15 | `func=get_sys_setting&sid=` | | 系统设置 |
| S16 | `func=qbox_get_cluster_node_list&sid=` | | 集群节点列表 |
| S17 | `func=qbox_get_syncing_folder_list&sid=` | | 服务端正在同步的文件夹列表 |
| S18 | `func=qbox_get_user_home&sid=&user=` | `user` | 用户主目录路径 |
| S19 | `func=qbox_get_progress&sid=&pid=` | `pid` | 异步任务进度（搬运/复制） |
| S20 | `func=get_move_status&sid=&pid=%d` | `pid` | 同上（移动） |
| S21 | `func=daemon_list&sid=&subfunc=delete&pid=%d` | `subfunc=delete`,`pid` | 取消后台任务 |
| S22 | `func=get_ad_info&sid=` | | AD 域信息 |

---

## 4.3 变更发现（同步核心）

| # | 端点 | 参数 | 说明 |
|---|---|---|---|
| N1 | `qsyncsrv.fcgi?func=qbox_get_max_log&sid=` | | **取最大日志号**（不带 folder = 全局） |
| N2 | `qsyncsrv.fcgi?func=qbox_get_max_log&sid=&folder=` | `folder` | 单文件夹 |
| N3 | `qsyncPrepare.cgi?func=qbox_get_max_log&sid=&folder=` | | 旧版 |
| N4 | `qbox_get_sync_log&sid=&lower=&number=` | `lower`=起始游标, `number`=条数 | **拉取文件变更日志区间** |
| N5 | `qbox_get_sync_log&sid=&lower=&number=&syncing_folder=` | +`syncing_folder` | 限定同步文件夹 |
| N6 | `qbox_get_sync_log&sid=&lower=&number=&sub_folder=` | +`sub_folder` | 限定子目录 |
| N7 | `qbox_get_sync_log&sid=&lower=&number=&get_detail=1&sub_folder=` | +`get_detail=1` | 带详情（新版 fcgi） |
| N8 | `qbox_query_notify&sid=&lower=%d&upper=%d` | 区间 | **全局通知区间查询**（config / global notify） |
| N9 | `qbox_get_device_config_list&sid=&user=&lower=&upper=` | `user`, 区间 | 设备配置日志区间 |
| N10 | `qbox_get_device_config&sid=&device_uid=` | `device_uid` | 单设备配置 |
| N11 | `qbox_save_device_config&sid=&device_uid=&user=&apply=1[&config_number=%d]` | | 上报本设备配置 |
| N12 | `qbox_reset_device_config&sid=&user=&device_uid=&mode=1` | | 重置设备配置 |
| N13 | `qbox_write_log&sid=&filepath=&action=%d` | `filepath`,`action` | **客户端主动写日志**（让其他设备感知本机变更） |
| N14 | `qbox_sync_start&sid=&channel=%d` | `channel` | 开始同步（通知服务端） |
| N15 | `qbox_sync_done&sid=&number=%d` | `number` | 同步完成（回传已处理条数） |

> **N13 是关键**：客户端本地改文件后，除了在本地排队上传，还要调用 `qbox_write_log` 把变更写入 NAS 日志，这样**其它设备**的轮询才能发现。这解释了为什么日志游标是双向的。

---

## 4.4 目录列举与文件元数据

| # | 端点 | 参数 | 说明 |
|---|---|---|---|
| L1 | `func=get_list&sid=&is_iso=0&list_mode=all&path=&dir=&limit=&sort=&start=[&type=4]&no_sort=` | `path`,`dir`(ASC/DESC),`limit`,`sort`,`start`,`type=4`,`no_sort` | **列目录**。`type=4` 变体用于特定列表模式 |
| L2 | `func=get_list&...&hidden_file=1` | `hidden_file=1` | 含隐藏文件（Qsync 用） |
| L3 | `func=get_tree&sid=&is_iso=0&node=` | `node` | 树形列举（懒加载） |
| L4 | `func=stat&path=&file_total=1&file_name=[&get_privilege=1]&sid=` | `path`,`file_name`,`file_total=1`,`get_privilege` | **单文件状态**（大小/mtime/存在性） |
| L5 | `func=stat&sid=&settime=1&mtime=&path=&file_total=1&file_name=` | `settime=1`,`mtime` | **设置 mtime**（同步完成后对齐时间戳） |
| L6 | `func=properties&sid=&path=&total=1&name=` | | 属性（含缩略图/EXIF 等） |
| L7 | `func=get_thumb&sid=&path=&name=&size=%u&option=3` | `size`,`option=3` | **缩略图** |
| L8 | `func=qbox_check_permission&sid=&path=&file_name=&check_upload=1` | `check_upload` | 上传前权限预检 |

**[已确认]** `stat` 响应解析字段（`CGetPathInfoJson::Parser`）：`status`, `total`, `datas`, `epochmt`, `exist`, `versioning_support`, `privilege_ex`。

---

## 4.5 写操作（增删改移）

| # | 端点 | 参数 |
|---|---|---|
| W1 | `func=createdir&sid=&dest_folder=&dest_path=` | `dest_folder`,`dest_path` |
| W2 | `func=rename&sid=` | POST 体（`filename` / `dest_name` 等） |
| W3 | `func=move&sid=[&no_fork=%d]` | POST 体（源/目标路径） |
| W4 | `func=delete&sid=` | POST 体（`path` + `file_name` / `file_total`） |
| W5 | `func=trash_recovery&sid=&source_file=&mode=%d&source_total=1&source_path=` | 从回收站恢复 |
| W6 | `func=repository_recovery&sid=&source_file=&mode=%d&source_path=&version_id=&dest_path=&versioning_version=1` | 从版本库恢复 |
| W7 | `func=qbox_fix_team_folder_link&sid=&path=[&type=4]` | 修复团队文件夹链接 |
| W8 | `func=qbox_set_recycle_bin&recycle_bin=%d&sid=` | 开关回收站 |
| W9 | `func=qbox_set_policy&share_policy=%d&sid=` | 设置共享策略 |
| W10 | `func=qbox_auth_config_password&sid=&password=` | 校验管理口令 |

---

## 4.6 上传

| # | 端点 | 参数 | 阶段 |
|---|---|---|---|
| U1 | `func=start_chunked_upload&sid=&upload_root_dir=` | `upload_root_dir` | **① 建分块会话** → 返回 `upload_id` |
| U2 | `func=start_chunked_upload&sid=&upload_root_dir=&check_qbox_file_profile=1&check_qbox_file_exist=%d&check_qbox_file_type=0&check_qbox_file_path=` | 附加存在性检查 | 变体 |
| U3 | `func=chunked_upload&sid=&upload_id=&settime=1&mtime=&offset=&filesize=&dest_path=&overwrite=%d[&rename_dest=]&upload_root_dir=` | `offset`=本片起始偏移 | **② 传分片** |
| U4 | `func=get_chunked_upload_status&sid=&upload_id=&upload_root_dir=` | | **③ 查已传字节**（续传） |
| U5 | `func=delete_chunked_upload_file&sid=&upload_id=&upload_root_dir=` | | 放弃分块会话 |
| U6 | `func=upload&sid=&dest_path=&overwrite=%d` | | 简单上传（小文件，multipart） |
| U7 | `func=upload_and_move&sid=&settime=1&mtime=&filesize=&dest_path=&overwrite=%d[&rename_dest=]&upload_root_dir=` | | **原子上传+改名**（推荐主路径） |
| U8 | `func=upload_and_move&...&check_qbox_file_profile=1&check_qbox_file_exist=%d&check_qbox_file_type=0&check_qbox_file_path=` | | 带 profile 检查变体 |
| U9 | `/cgi-bin/{qsync,filemanager}/upload.php` | multipart | 低层上传端点 |

**[已确认]** 上层封装函数：`WFMGetUploadID`、`WFMUploadFilewithHandle`、`WFMQsyncUploadandMovewithHandle`、`WFMQsyncUploadandMoveMultiPartwithHandle`、`WFMQsynGetChunkFileSize`、`WFMQsyncChunckUploadwithHandle`、`WFMQsyncDeleteChunkFile`、`WFMQsyncDeleteMultiPartPathwithCheckProfile`。

---

## 4.7 下载

| # | 端点 | 参数 | 说明 |
|---|---|---|---|
| D1 | `func=download` | `sid`, `path`, `file_name`（+ Range 头） | **HTTP 下载**，支持 `Range: bytes=` |
| D2 | `func=download_file` | 同上 | 等价/文件式变体 |
| — | 响应头 | `Content-Range: bytes %llu-%llu/%llu` | 分片响应 |
| D3 | `func=stat&...&get_privilege=1` | | 下载前预检 |

**[已确认]** 上层封装：`WFMDownloadFileToHandle`、`WFMDownloadFileToCloudFile`（直接写入占位符，on-demand 用）。
**局域网快路径**：WebSocket 二进制命令 `LANDownloadFile`（`ws://` / `wss://` + `Auth1`/`Auth2` 握手），不走 HTTP。

---

## 4.8 版本化 / 增量 delta

见 06 篇详解。端点速查：

| # | 端点 | 参数 |
|---|---|---|
| V1 | `func=versioning_probe&sid=` | 探测服务端是否支持版本化 |
| V2 | `func=versioning_stat&sid=` / `func=versioning_stat&sid=&source_path=&source_file=` | 版本化统计 |
| V3 | `func=versioning_lock&create_version=1&sid=&source_path=&source_file=` | **创建新版本 + 加锁** |
| V4 | `func=versioning_lock&check_version=1&sid=&source_path=&source_file=&version_id=&lockid=` | 校验并续锁 |
| V5 | `func=versioning_unlock&sid=&source_path=&source_file=&lockid=` | 解锁 |
| V6 | `func=versioning_gen_sig&sid=&source_path=&source_file=&lockid=&version_id=` | **让服务端生成 rsync 签名** |
| V7 | `func=versioning_get_sig&sid=&source_path=&source_file=&lockid=&version_id=` | 取签名（分块） |
| V8 | `func=versioning_stat_delta&sid=&source_path=&source_file=&version_id=` | 查询既有 delta 大小 |
| V9 | `func=versioning_gen_delta&sid=&source_path=&source_file=&lockid=&version_id=` | 生成 delta |
| V10 | `func=versioning_get_delta&sid=&source_path=&source_file=&lockid=&version_id=&offset=` | 取 delta（**带 offset，分段下载**） |
| V11 | `func=versioning_upload_file&sid=&dest_path=&overwrite=&version_id=&versioning_version=1&source_file=&offset=&upload_name=&filesize=` | 上传 delta 片 |
| V12 | `func=versioning_commit_upload&sid=&settime=1&mtime=&source_path=&source_file=&lockid=&version_id=` | 提交（合并 delta 为新版本） |
| V13 | `func=versioning_clean_version&sid=&source_path=&source_file=&lockid=&version_id=` | 清理临时版本 |
| V14 | `func=versioning_gen_file&sid=` | 重建文件 |
| V15 | `func=versioning_delete_all&sid=` | 清空版本 |
| V16 | `func=versioning_get_progress&sid=` | 进度 |

---

## 4.9 共享链接 / 共享成员 / 团队文件夹

| # | 端点 | 参数 |
|---|---|---|
| H1 | `func=get_share_link&sid=` | 列出分享链接 |
| H2 | `func=update_share_link&sid=` | 修改链接 |
| H3 | `func=update_link&sid=` | 同上 |
| H4 | `func=get_share_list&sid=&dir=ASC&limit=&sort=filename&start=` | 分页列分享 |
| H5 | `func=share_file&sid=` | 创建分享 |
| H6 | `func=delete_share&sid=&ssids=&file_total=%d` | 按 ssid 批量删 |
| H7 | `func=delete_share&sid=&filename=&download_link=&file_total=%d` | 删除指定链接 |
| H8 | `func=send_share_mail&sid=` | 邮件分享 |
| H9 | `func=qbox_get_share_info&sid=&file=` | 某文件的分享信息 |
| H10 | `func=qbox_get_share_path&sid=&share_id=` | 分享路径 |
| H11 | `func=qbox_unshare&sid=&share_id=` | 取消分享 |
| H12 | `func=qbox_find_share&sid=&file=&lower=&upper=` | 查找分享 |
| H13 | `func=qbox_get_share_member&sid=&user_type=&share_id=&lower=&upper=&all_user=&refresh=&netbios=&domain=&filter=` | 成员列表 |
| H14 | `func=qbox_get_user_list&sid=&user_type=&all_user=&refresh=&lower=&upper=&netbios=&domain=&filter=` | 用户列表 |
| H15 | `func=qbox_set_share_member` | 设置成员（POST 体） |
| H16 | `func=qbox_share_to` | 分享给用户 |
| H17 | `func=qbox_accept_share&sid=&event_id=%d` | 接受共享邀请 |
| H18 | `func=qbox_deny_share&sid=&event_id=%d` | 拒绝 |
| H19 | `func=qbox_leave_share&sid=&event_id=%d` | 退出共享 |
| H20 | `func=qbox_kickout_share&sid=&share_id=` | 踢出成员（qsyncsrv 版） |
| H21 | `func=qbox_get_my_event&sid=&event_type=%d&lower=%d&upper=%d` | 我的事件（共享邀请等） |
| H22 | `func=qbox_remove_event&sid=&event_id=%d` | 移除事件 |
| H23 | `func=qbox_team_folder_get_list&sid=&event_status=0&event_type=%d&lower=%d&upper=%d` | 团队文件夹列表 |
| H24 | `func=qbox_team_folder_get_info&sid=&path=` | 详情 |
| H25 | `func=qbox_team_folder_get_member&sid=&user_type=&share_id=&lower=&upper=&all_user=&refresh=&netbios=&domain=&filter=` | 成员 |
| H26 | `func=qbox_team_folder_set_member` | 设置成员 |
| H27 | `func=qbox_team_folder_share_to` | 分享 |
| H28 | `func=qbox_team_folder_accept_share&sid=&display_name=&share_id=` | 接受 |
| H29 | `func=qbox_team_folder_deny_share&sid=&share_id=` | 拒绝 |
| H30 | `func=qbox_team_folder_leave_share&sid=&share_id=` | 退出 |
| H31 | `func=qbox_team_folder_unshare_ex&sid=&share_id=` | 取消分享 |

**公开分享查看（无需登录）** **[已确认]**：
```
%s://%s:%s/share.cgi?ssid=%s          Qsync.exe@0x002e4ccc
/share.cgi?func=get_list&ssid=%s      QsyncLib/QsyncAPI
```

---

## 4.10 备份 / 回收站

| # | 端点 | 参数 |
|---|---|---|
| B1 | `func=qbox_backup_start&channel=%d&sid=` | 开始备份会话 |
| B2 | `func=qbox_backup_done&sid=&number=%d` | 结束 |
| B3 | `func=qbox_check_backup_folder&sid=&path=` | 检查备份目录 |
| B4 | `func=qbox_set_backup_folder&sid=&path=&action=%d` | 设置/取消备份目录 |
| B5 | `func=qbox_clean_backup_folder&sid=&path=` | 清空 |
| B6 | `func=qbox_remove_backup_folder&sid=&path=` | 移除 |
| B7 | `func=qbox_set_backup_finish_time&sid=&path=&time=` | 记录完成时间 |
| B8 | `func=get_backup_file_list&sid=&source_path=&filter=&timestamp=&show_deleted=%d&limit=&start=` | 备份文件列表 |

---

## 4.11 云账号 API（QID / myQNAPcloud）

> 本节经 `cloudapi-evidence.md` 交叉验证并扩充。完整细节与反汇编证据见 **[07 篇](07-云账号QID与设备发现.md)** 与 `cloudapi-evidence.md`。

| # | URL | 说明 |
|---|---|---|
| C1 | `{account}/oauth/token` | `POST` OAuth2 取 token（`authorization_code`(+PKCE) / `refresh_token` / `client_credentials`） |
| C2 | `{account}/oauth/tokeninfo?access_token=%s` | 校验/查询 token，返回 user/email/id/display_name |
| C3 | `{account}/oauth/signout` | 登出 |
| C4 | `{account}/oauth/auth?response_type=code&client_id=&redirect_uri=&code_challenge_method=S256&code_challenge=` | **浏览器授权入口（主路径，PKCE）** |
| C5 | `{account}/signin?create=0&state=&hide_signup=true&hide_social=true&hide_forget_password=true&hide_activation_mail=true&switch_account=true` | 账号站 SPA 入口 |
| C6 | `http://127.0.0.1:{4300\|4343\|14300\|14343}/oauth2/callback` | **本地回环回调**（端口有备选族） |
| C7 | `{core2}/v1.1/me` | 当前用户/组织 |
| C8 | `{core2}/v1.1/device` | 设备列表（分页 `offset`/`limit`） |
| C9 | `{core2}/v1.1/device/search?device_name=%4` | 按设备名查 |
| C10 | `{core2}/v1.1/device/count` | 设备数 |
| C11 | `{core2}/v1.1/device/%s/network` | 设备网络/端口信息 |
| C12 | `{core2}/v1.1/utility/geo/search` | 公网 IP / 地理（`QIDAPIGetPublicIP`） |
| C13 | `{core2}/v1.2/device` | 设备列表（v1.2） |
| C14 | `{core2}/v1.2/device/sharedtome` | 分享给我的设备 |
| C15 | `{core2}/v1/users/deviceId/%s` | **[未确认，无代码引用]** |
| C16 | `{core2}/v1/services/vlink/%s` | **vLink / CloudLink 服务查询** |
| C17 | `{core2}/v1/devices/services/portMapping/%s` | **设备端口映射**（内/外网 HTTP(S) 端口） |
| C18 | `{core2}/api/v1/authorizes/q_token` | **用 QID token 换 NAS 可用的 q_token** |
| C19 | `{core2}/api/v1/questionnaires` | 问卷（DCS 打点） |
| C20 | `{account}/v1/record/{id}` | 记录上传（诊断/分析数据，可跳过） |
| C21 | `https://update.qnap.com/SoftwareReleaseS.xml` | 版本更新检查（`.cn` 镜像同理） |

**域名集合** **[已确认]**：
```
account.qnap.com / account.qnap.com.cn                     (+ alpha- 变体)
core2.myqnapcloud.io
core2.api.myqnapcloud.com / .cn                            (+ alpha-, alpha-.cn)
core.api.myqnapcloud.com / .cn                             (+ alpha-, 新版无 core2 前缀)
auth.api.myqnapcloud.com / .cn                             (+ alpha-)
edge.api.myqnapcloud.com / .cn                             (+ alpha-)
core2.api.dev.myqnapcloud.cn / core2.dev.myqnapcloud.io    (仅 cloudlinkP2P.dll)
edge.api.dev.myqnapcloud.cn / edge.dev.myqnapcloud.io      (仅 cloudlinkP2P.dll)
```

**云侧请求附加头** **[已确认]**：
```
X-QNAP-APP-ID   X-QNAP-SUBAPP-ID   X-QNAP-APP-VER
X-QNAP-TIME     X-QNAP-CHECK       Authorization: Bearer <access_token>
Content-Type: application/x-www-form-urlencoded      Accept: application/json
```

**⚠️ 更正**：`grant_type=password&...&username=%3&password=%4` **不属于账号站登录**，它属于
`CDCSCloudHttpService`（DCS 打点/问卷服务），同函数内还会尝试 `client_credentials` 等。
QID 登录主路径是 **授权码 + PKCE + 本地回调**。
```

---

## 4.12 API 数量统计

由 `qsync-analysis/categorize.py` 对 `func_inventory.txt` 做**互斥分类**（可复现，合计与总数一致）：

| 分类 | 端点个数 |
|---|---|
| 登录/会话 | 5 |
| 鉴权（共享文件夹两步 `auth_1/auth_2`） | 4 |
| 会话状态/探测 | 23 |
| **变更发现（日志游标）** | **12** |
| 列举/元数据 | 8 |
| 写操作（增删改移/回收站/恢复） | 10 |
| 上传 | 6 |
| 下载 | 2 |
| 版本化/delta | 15 |
| 共享/团队文件夹 | 28 |
| 备份 | 8 |
| 其他（`qpkg`、`search_engine`） | 2 |
| **合计** | **123** |

此外还有 **不属于 `func=` 体系**的独立 CGI：
```
/authLogin.cgi (authLogout.cgi, passwordless)
/qsyncsrv_login.cgi / qsyncsrv_logout.cgi / qsyncsrv.fcgi?func=login|logout
/qsyncsrvPrepare.cgi (activate / user=)
/wfm2Login.cgi / wfm2Logout.cgi
/qsyncPrepare.cgi
/upload.php
/share.cgi?ssid=  (公开分享，无需登录)
/sysinfoReq.cgi / appRequest.cgi
/oauth/token /tokeninfo /signout /auth /callback   (云账号)
/v1.1/me /v1.2/device /v1.2/device/sharedtome      (云账号)
/v1/services/vlink/{id} /v1/devices/services/portMapping/{id}
/api/v1/authorizes/q_token /api/v1/questionnaires /v1/record/{id}
```
以及 **WebDAV**（自定义 `QBack` 命名空间，用于保真 Windows 文件元数据）：
```
PROPFIND   Depth: 0 | Depth: 1      → 支持 getetag / getlastmodified
PROPPATCH  <D:set><D:prop>ns1:Win32{CreationTime,LastModifiedTime,LastAccessTime}</D:prop></D:set>
PROPPATCH  <D:set><D:prop>ns1:Win32FileAttributes</D:prop></D:set>
MKCOL                                → 建目录
条件头: if-match: / if-none-match:
```
详见 01 篇 §1.4(c)。
全量 URL 模板（含每个模块的原始形态）见 `out/endpoints_clean.txt`（322 条去重）。
