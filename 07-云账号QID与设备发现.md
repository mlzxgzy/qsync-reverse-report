# 07 · 云账号（QID / myQNAPcloud）与设备发现

> 作用：让客户端**不需要用户输入 NAS 的 IP/DDNS** 就能找到并连上 NAS。
> 这一层完全独立于同步协议，**第一版可以不做**（直接用 NAS 地址 + 账号密码登录即可），但做了体验会好很多。
>
> 本篇所有结论的逐条原始证据（含反汇编 VA 与字符串偏移）见 **[cloudapi-evidence.md](cloudapi-evidence.md)**。

---

## 7.1 OAuth2 客户端凭据（硬编码）★

**[已确认]** `Qsync.exe` 的 `.rdata` 中直接内嵌了 QID OAuth2 客户端凭据：

| 字段 | 值 | 文件偏移 |
|---|---|---|
| `client_id` | `593a4f08d6b82f791bacd7db` | `Qsync.exe@0x002f0e6c` |
| `client_secret` | `g9LsfI…gfXQp`（公开版已掩码） | `Qsync.exe@0x002f0e98` |

> ⚠️ **公开版掩码说明**：`client_secret` 的完整值已从报告中移除，以免在公开仓库散布第三方凭据
> （GitHub secret scanning 也会因此报警）。完整值可从**你自己合法获得的** Qsync 安装包直接提取：
> ```bash
> ./tools/reveal-credentials.sh "/path/to/Qsync/Qsync.exe"
> # 或按文件偏移查看：Qsync.exe 偏移 0x002f0e98 附近
> ```
> `client_id` 是客户端标识（非密钥），保留原文。

- 同一对常量在 `QsyncLib.dll@0x0041eee5` / `@0x0041eeea` **再次出现**（引擎侧调 `QIDAPIAPPSignin` / `RefreshToken` 时使用）。
- `Qsync.exe` **没有**导入 `setAppIdSecret` → 排除「配置下发」的可能，确认是编译期常量。
- 另有 app id 字符串 `com.qnap.qsync.windows.2017`（`QsyncLib.dll@0x0042236`、`@0x00044705`）。

> 这是**客户端标识**（所有 Qsync 安装共用），不是用户凭据。用户凭据是登录后拿到的 `access_token` / `refresh_token`。
> ⚠️ 在公开仓库里提交这个值可能触发凭据扫描告警；建议放到构建期注入或配置项。

---

## 7.2 域名矩阵与区域选择

**[已确认]** 各组域名（均以 `/` 结尾，实际拼接为 `${scheme}${host}:${port}${path}`）：

| 用途 | 域名 |
|---|---|
| **账号（OAuth2）** | `https://account.qnap.com/` `@0x2f0d4c`<br>`https://account.qnap.com.cn/` `@0x2f0d8c`<br>`https://alpha-account.qnap.com/` `@0x2f0d2c`<br>`https://alpha-account.qnap.com.cn/` `@0x2f0d68` |
| **核心 API（core2 族）** | `https://core2.myqnapcloud.io/` `@0x2f0f78`<br>`https://core2.api.myqnapcloud.cn/` `@0x2f0fc0`<br>`https://core2.api.alpha-myqnapcloud.com/` `@0x2f0f4c`<br>`https://core2.api.alpha-myqnapcloud.cn/` `@0x2f0f98` |
| **核心 API（新版无 core2 族）** | `core.api.myqnapcloud.com` `@0x747690`<br>`core.api.myqnapcloud.cn` `@0x7476ac`<br>`core.api.alpha-myqnapcloud.com` `@0x747650`<br>`core.api.alpha-myqnapcloud.cn` `@0x747670` |
| **认证 / 边缘**（`QSystemLib.dll`） | `https://auth.api.myqnapcloud.cn/`、`https://edge.api.myqnapcloud.cn/`、`https://edge.api.alpha.myqnapcloud.cn/`、`https://core2.api.alpha.myqnapcloud.cn/` |
| **开发环境**（仅 `cloudlinkP2P.dll`） | `https://core2.api.dev.myqnapcloud.cn`、`https://core2.dev.myqnapcloud.io`、`https://edge.api.dev.myqnapcloud.cn`、`https://edge.dev.myqnapcloud.io` |

> 注意：**`Qsync.exe` 与 `QsyncLib.dll` 里没有 `dev` 变体** —— 它们只存在于 `cloudlinkP2P.dll`。

### 区域选择逻辑
**[已确认]** `CCloudHttpService_V2::setRegion(bool)` 实为**写一个全局字节** `0xbcfe1c`（唯一写点 `Qsync.exe@0x001fa867`）。
读取侧用 `cmp [0xbcfe1c], 0` + `cmovne/cmove` 在 **alpha / 生产** 之间二选一；再用对象成员 `[obj+0xb8]` 在 **`.cn` / `.com`（或 `.io`）** 之间二选一。
`QSystemLib.dll` 有同构逻辑（`@0x6b99` 账号站、`@0x7e9e`/`@0x8a9d` auth 与 core2），成员 `+0x88` = 国际/中国，`+0x89` = 是否用中国 api 变体。

**[未确认]** `setRegion` 的**上层调用者**（谁决定区域）未定位。**实现建议**：默认 `.com`，失败或用户在中国大陆时切 `.cn`；两者都试兜底。`alpha` / `dev` 正式版用不到。

---

## 7.3 登录流程

### 主路径：OAuth2 授权码 + PKCE + 本地回环回调 ★
**[已确认]** 完整时序：

```
1) 选账号站域名（见 7.2）
2) 起本地回环回调服务
   http://127.0.0.1:{4300|4343|14300|14343}/oauth2/callback
     主端口 4300  (Qsync.exe@0x47f268  mov ecx,0x10cc)
     备端口 4343  (Qsync.exe@0x47f26d  mov eax,0x10f7)
     备用族 14300 (0x37dc) / 14343 (0x3807)   @0x47f30f
   日志: [QID][helper] port=%d unavailable, falling back to alternative port
         [QID][helper] alt port=%d also unavailable, giving up
         [QID][helper] result: %s, finalPort=%d

3) 生成 PKCE
   QSystemLib.dll 导出: generateCodeVerifier() / generateCodeChallenge(verifier)
   追加: &code_challenge_method=S256  &code_challenge=<challenge>

4) 打开浏览器授权
   GET {account}/oauth/auth?response_type=code&client_id=<id>
                            &redirect_uri=<http://127.0.0.1:port/oauth2/callback>
                            &code_challenge_method=S256&code_challenge=<challenge>
   （备选入口：{account}/signin?create=0&state=<state>&hide_signup=true&hide_social=true
                &hide_forget_password=true&hide_activation_mail=true&switch_account=true[&qid=<qid>]）

5) 回调收 code
   GET /oauth2/callback?code=<code>
   Qt 信号: slotOauthCodeArrived() / onRequestUrlArrived()
            slotAuthFlowCompleted() / onAuthDoneFlowCompleted()

6) 换 token
   POST {account}/oauth/token
   grant_type=authorization_code&client_id=%1&client_secret=%2
     &code=%3&code_verifier=%4&redirect_uri=%5
   Header: Content-Type: application/x-www-form-urlencoded

7) 取用户信息
   GET {account}/oauth/tokeninfo?access_token=<token>
   响应字段: user, email, id, display_name
```

**[已确认]** 相关实现：`Qsync.exe` 内的 QID OAuth helper（本地 HTTP 服务）、`QSystemLib.dll` 导出的 `QcOauth2Helper`（含 `getOauthLoginUrl`、`generateCodeVerifier`、`generateCodeChallenge`）。

### ⚠️ 关于 `grant_type=password`（重要更正）
**[已确认]** `grant_type=password&client_id=%1&client_secret=%2&username=%3&password=%4`（`Qsync.exe@0x7474e8`）
**不属于账号站登录**。它所在的函数属于 **`CDCSCloudHttpService`（DCS 打点/问卷服务）**，同一函数里依次尝试 `authorization_code` / `password` / `client_credentials` / `refresh_token` 多种 grant。
→ **不要把它当成 QID 登录入口**。

### 续期 / 登出 / 校验
**[已确认]**
```
刷新:  POST {account}/oauth/token   grant_type=refresh_token&client_id=%1&client_secret=%2&refresh_token=%3
登出:  {account}/oauth/signout          (Qsync.exe@0x747638 ; QsyncAPI.dll@0x000ea648)
校验:  {account}/oauth/tokeninfo?access_token=<token>
Header: Authorization: Bearer <access_token>
```
`CCloudHttpAuthToken` 响应字段：`access_token`、`refresh_token`、`token_type`、`expires_in`、`error`、`error_description`（对应导出访问器 `getAuthToken` / `getRefreshToken` / `getTokenType` / `getExpiresIn` / `getError` / `getErrorDescription`）。

### 请求头（云侧通用）**[已确认]**
```
X-QNAP-APP-ID         X-QNAP-SUBAPP-ID      X-QNAP-APP-VER
X-QNAP-TIME           X-QNAP-CHECK
Authorization: Bearer %1
Content-Type: application/x-www-form-urlencoded
Accept: application/json      Connection: Keep-Alive      Cache-Control: no-cache
```
服务端错误串：`X-QNAP-TIME is invalid.`、`The checksum X-QNAP-CHECK is invalid.`、`The app id is not found.`、`The vlink configuration is not found.`、`Get device name failed.`、`The device is not found.`、`Get device failed.`
→ **`X-QNAP-CHECK` 是一个校验和签名**（内容未还原，见 7.9）。

---

## 7.4 用户信息

**[已确认]**：
```
GET {core2}/v1.1/me
响应字段: result, user, email, display_name, first_name, last_name,
          organization_id, organization_name, organization_site_name, limit, offset
```
另有 `code`、`info`、`error` 三个通用包裹字段（`Qsync.exe@0x2f1010/0x2f1018/0x2f1020`）。

---

## 7.5 设备发现

**[已确认]** 全部端点（`%1%2:%3` = scheme + host + port）：

| 模板 | 偏移 | 说明 |
|---|---|---|
| `%1%2:%3/v1.1/device` | `Qsync.exe@0x7476f0` | 设备列表（`offset`/`limit` 分页） |
| `%1%2:%3/v1.1/device/search?device_name=%4` | `Qsync.exe@0x7476c4` | 按设备名查 |
| `%1%2:%3/v1.1/device/count` | `QsyncAPI.dll@0x000eac20` | 设备数 |
| `%1%2:%3/v1.1/device/%ls/network` | `QsyncAPI.dll@0x000ea716` | 某设备的网络/端口信息 |
| `%1%2:%3/v1.1/utility/geo/search` | `QsyncAPI.dll@0x000eb688` | 公网 IP / 地理（`QIDAPIGetPublicIP`） |
| `%1%2:%3/v1.2/device` | `Qsync.exe@0x2f0fec` | v1.2 设备列表 |
| `%1%2:%3/v1.2/device/sharedtome` | `Qsync.exe@0x2f0ff8` | 别人分享给我的设备 |
| `%1%2:%3/v1/users/deviceId/%ls` | `QsyncAPI.dll@0x000eafce` | **[未确认]** 无代码引用 |
| `%1%2:%3/v1.1/me` | `Qsync.exe@0x2f0e04` | 当前用户/组织 |

### 设备字段 **[已确认]**
```
通用:   code, result, info, error
设备:   host_name, device_name, model_name, fw_model_name,
        mac_address, cluster_uid, device_id,
        firmware_version, firmware_number,
        qid_login_enabled, region, domain_name,
        lan_ips[]{ipv4, ipv6}, lan_gateway,
        wan_ips[]{ipv4},
        local_services[]: { service_name, internal_port, external_port, published }
组织:   organization_name, organization_site_name
```
`service_name` 的取值示例 **[已确认]**：`WebAdministration`、`Secured WebAdministration`。

对应 C++ 类（`Qsync.exe` 导出）：
| 类 | 关键访问器 |
|---|---|
| `CCloudDeviceInfo` | `getDeviceId`, `getDeviceName`, `getLanIPs`, `getWanIPs`, `getLocalServices` |
| `CCloudDeviceDetailInfo` | `getDeviceId/Name/Type`, `getAgentVersion`, `getFWNumber`, `getFirmwareVersion/BuildNumber/PatchVersion`, `getFwModelName`, `getFwSerialNumber`, `getHwSerialNumber`, `getHostName`, `getMacAddress`, `getModelName`, `getRemoteAccessSupported`, `getLanIPs`, `getWanIPs` |
| `CCloudHttpPortMapping` | `getProtocol`, `getServeicName`（原文拼写）, `getSubServeicName`, `getInternalHTTPPort`, `getInternalHTTPSPort`, `getExternalHTTPPort`, `getExternalHTTPSPort` |
| `CCloudHttpvLINKInfo` | `getvLINKID`, `getLANIP`, `getWANIP`, `getGatewayIP` |
| `CCloudLinkInfo` | `getCloudLinkID` |

**结构体响应字段补充** **[已确认]**：
- `CCloudHttpvLINKInfo` ← `vlinkId`, `vlinkType`, `vlinkVersion`, `lanIp`, `lanGW`, `wanIp`, `actTime`
- `CCloudHttpPortMapping` ← `service_name`, `subServiceName`, `proto`/`protocol`, `internalPort`, `externalPort`
- 连接类型字符串：`wan_ip` / `ddns` / `lan_ip`

### `CCloudHttpService_V2` 方法签名 **[已确认]**
```
signin(QString scheme/host ×3, QString clientId, QString clientSecret,
       QString username, QString password, QString refreshToken, bool*, CCloudHttpAuthToken&)
signout(QString ×3, bool*)
getAllDeviceInfo(QString ×3, bool*, QVector<CCloudDeviceDetailInfo*>&)
getDeviceInfo(QString ×4, bool*, CCloudDeviceInfo&)
```
→ **参数 1..3 是 3 组 (scheme+host) 候选**（国际 / 中国 / alpha），每个候选都会试同一 path。
`getDeviceInfo` 的第 4 个 QString 是 **`device_vague_uid` 或设备名**（字符串 `device_vague_uid` `@0x746c8c`、`DeviceName` `@0x746d7c`、`session_code` `@0x746e08`）。

`sendAnalyticData` → `{account}/v1/record/{id}`（诊断上传，**Linux 实现可跳过**）。

---

## 7.6 从「NAS 账号」到「可用连接地址」★

这是 QID 登录之后最关键的一步。

### 候选地址的枚举顺序 **[已确认]**
`CQsyncConnection::UpdateAddressList`（`QsyncLib.dll` VA `0x100412c0`）在**同一个循环体内**按固定顺序枚举 4 类候选，**首个成功者即被采用**：

| 顺序 | 类型 | 日志（`QsyncLib.dll@偏移`） |
|---|---|---|
| 1 | **GatewayIP** | `@0x004134b` `UpdateAddressList GetDeviceInformation(GetWayIP=%s)` |
| 2 | **LANIP** | `@0x004153d` `UpdateAddressList GetDeviceInformation(LANIP=%s)` |
| 3 | **myQNAPcloud (DDNS)** | `@0x0041666` `UpdateAddressList GetDeviceInformation(MyQNAPCloud=%s)` |
| 4 | **WANIP** | `@0x0041769` `UpdateAddressList GetDeviceInformation(WANIP=%s)` |

收尾：`TotalProcessTime(MyQNAPcloud) = %lld ms` → `cancel ping thread` → `StartPingAddress`。

> ⚠️ 这**修正**了一个常见的直觉：不是「CloudLink 永远优先」。CloudLink 是**独立的连接模式**（见下），普通模式下顺序就是 网关 → 内网 → DDNS → 外网。

### DDNS 主机名构造 **[已确认]**
`domain_name` + `.myqnapcloud.com` 或 `.myqnapcloud.cn`（`QsyncLib.dll@0x0043523` / `@0x0043563`）。

### 端口选择 **[已确认]**
- 端口来自 `CCloudHttpPortMapping` 的四个值，持久化到注册表：
  `QSYNC_LINK_NAS_INTERNAL_HTTP_PORT` / `_INTERNAL_HTTPS_PORT` / `_EXTERNAL_HTTP_PORT` / `_EXTERNAL_HTTPS_PORT`
- 用户可覆盖 **[已确认]**（新增发现的注册表值）：
  `QSYNC_LINK_USE_SPECIFY_HTTP_PORT`、`QSYNC_LINK_SPECIFY_LAN_HTTP_PORT`、`QSYNC_LINK_SPECIFY_INTERNET_HTTP_PORT`、
  `QSYNC_LINK_USE_SPECIFY_HTTPS_PORT`、`QSYNC_LINK_SPECIFY_LAN_HTTPS_PORT`、`QSYNC_LINK_SPECIFY_INTERNET_HTTPS_PORT`、`QSYNC_LINK_PORT`
- 地址列表持久化格式：`Address%d` = `"%s,%d,%d"`（地址串, 类型, 端口），个数存 `QSYNC_LINK_NAS_ADDRESS_NUM`（另有 `AddressNUM`）

### 测速与排序 **[已确认]**
`InitStartPingAddress` / `StartPingAddress` / `PingAddressThreadProc` / `WFMValidIP`：
- 并发 ping 所有候选（`nFinishPing:%d,nIPcount:%d and sleep(100)`）
- 结果可 **Re-order**（按 RTT 重排）或 **Keep-order**（保持原序）：
  `(Re-order :Addr=%s,RTT=%d)` / `(Keep-order :Addr=%s,RTT=%d)`
- 日志：`[LOGINLOG] Ping start` / `Ping %s:%d start/end` / `Ping end`
- 上层 API：`CQsyncSyncDll::CheckConnectSpeed(handle, bool&, bool&, bool*)`；最终类型由 `QBackUpdateIPConnectType` 落盘

### 连接类型枚举 **[已确认]**
`CQsyncSyncDll::GetConnectType(handle, path)`（VA `0x10046c80`）：
```
m_eCloudLinkTunnelType == 1 → 返回 4   (P2P)
                       == 2 → 返回 5   (Relay)
                       == 3 → 返回 6   (Lan)
                       == 0 → 按地址查表，返回该地址记录的类型；都不中则做 IP 判定 → 3
                       其它 → 记日志 Unknown type，返回 7
```
隧道类型字符串：`[LOGINLOG] Connect Type myQNAPcloud Link v2 - P2P / Relay / Lan / None`。

### CloudLink（myQNAPcloud Link v2 / QUTK）**[已确认]**
`CQsyncConnection::OpenQUTKTunnel`（`QsyncLib.dll@0x0046704`~`@0x46fcf`）：
```
Cloudlink_p2p_create_session
Start to get port mapping
Cloudlink_p2p_connect(-1)                       [LOGINLOG] QUTK Connect start/end
Cloudlink_p2p_start_tunnel                      [LOGINLOG] QUTK StartProxy start/end
m_dwQUTKMappedPort mapped                       [LOGINLOG] QUTK end(QUTKMappedPort=%d)
状态回调: QUTKTunnelStatusCallback(%d)
   new / signaling / connecting / connected / disconnected / failed / auth error
```
**关键**：隧道成功后客户端拿到 **`127.0.0.1:<QUTKMappedPort>`** 本地代理地址
（`QsyncLib.dll@0x0043e1ca push '127.0.0.1'` + `@0x43e1d0 push '%s%s:%d'`），
**此后所有 NAS 请求都走本机回环**。这就是为什么「CloudLink 优先」在代码里表现为一个独立分支：
`Try CloudLink first` / `Link with CloudLink mode first` / `Try CloudLink`。
底层是 `cloudlinkP2P.dll`（13.6 MB，Go 编译的 myQNAPcloud Link v2 客户端）。

---

## 7.7 `QIDAPI*` / `MCNAPI*`（`QsyncAPI.dll`）

### 参数约定 **[已确认]**
- 入参 1..3：`scheme`（http/https 二选一）、`host`、`port`，最终 `sprintf(buf, "%ls%ls:%d<path>", scheme, host, port)`
- 入参（凭据）：`client_id`、`client_secret`、`access_token`、`refresh_token`
- 输出：`bool*`（成功/继续翻页）、`int*`（返回码/计数）、结构体指针

> 修饰名把前 6 个参数都写成 `PB_W`，与 `%ls%ls:%d` 只有 3 个占位符不完全吻合。**单组语义已由反汇编证实；「前 6 个是 3 组候选」属强推断。**

### 导出 → URL 映射 **[已确认]**
| 导出 | URL |
|---|---|
| `QIDAPIAPPSignin` (5) | `%ls%ls:%d/oauth/token` `@0xea112` |
| `QIDAPIAPPRefreshToken` (3) | `%ls%ls:%d/oauth/token`（body `grant_type=refresh_token`） |
| `QIDAPIAPPSignOut` (4) | `%ls%ls:%d/oauth/signout` `@0xea648` |
| `QIDAPIGetTokenInfo` (12) | `%ls%ls:%d/oauth/tokeninfo?access_token=%ls` `@0xe9f30` |
| `QIDAPIGetAllDeviceCount` (6) | `%ls%ls:%d/v1.1/device/count` `@0xeac20` |
| `QIDAPIGetAllDeviceInfo` (7) | `%ls%ls:%d/v1.1/device` `@0xeadcc` |
| `QIDAPIGetDeviceInfoByName` (10) | `%ls%ls:%d/v1.1/device/search?device_name=%ls` `@0xea96e` |
| `QIDAPIGetDeviceID` (9) | `%ls%ls:%d/v1/users/deviceId/%ls` `@0xeafce` **[未确认，无代码引用]** |
| `QIDAPIGetCloudLinkSetting` (8) | 走 `/v1.1/device/%ls/network` `@0xea716` **[未完全确认]** |
| `QIDAPIGetPublicIP` (11) | `%ls%ls:%d/v1.1/utility/geo/search` `@0xeb688`（反汇编确认 `QsyncAPI.dll@0x0003017e`） |
| `MCNAPIGetVLinkInfo` (2) | `%ls%ls:%d/v1/services/vlink/%ls` `@0xea290` |
| `MCNAPIGetServicePorts` (1) | `%ls%ls:%d/v1/devices/services/portMapping/%ls` `@0xea4e0` |
| `QIDFreeCloudInfo` / `QIDFreeDeviceInfo` | 释放结构体 |

结构体：`_CLOUDSERVER_INFORMATION`、`_NAS_DEVICE_INFORMATION`、`_NAS_DEVICE_INFORMATION_API_V11`、`_CLOUD_LINK_INFORMATION`、`_LOCAL_DEVICE_INFORMATION`。

---

## 7.8 Linux 实现建议

### 最小路径（跳过 QID）
```
用户手动输入：NAS 地址（IP 或 xxx.myqnapcloud.com）+ 端口 + 用户名 + 密码
→ 直接走 02 篇的 authLogin.cgi 流程
```
**这已足够完成全部同步功能。** QID 只解决「用户不知道 NAS 地址」的便利性问题。

### 完整路径（实现 QID）
```
1. 起本地回环服务器，绑定 4300（失败则 4343，再失败 14300/14343）
2. 生成 PKCE verifier/challenge (S256)
3. 打开浏览器到 {account}/oauth/auth?response_type=code&client_id=...&redirect_uri=...&code_challenge=...
4. 回调收 code → POST {account}/oauth/token (grant_type=authorization_code + code_verifier + client_secret)
5. GET {core2}/v1.1/me 取用户信息
6. GET {core2}/v1.2/device 取设备列表
7. 对目标设备按 GatewayIP → LANIP → DDNS → WANIP 顺序组装候选地址（+ 端口）
8. 并发 ping 测速，按 RTT 排序
9. 把 QID token 换成 NAS 凭据：GET {core2}/api/v1/authorizes/q_token
10. 交给 qsyncsrv_login.cgi 免密登录
```
**简化选项**：跳过第 3–4 步的浏览器流程 —— 但注意 `grant_type=password` 模板属于 DCS 打点服务，
**不能确定账号站支持 password grant**。若要免浏览器登录，需要先抓包验证账号站是否接受 password grant。

### ⚠️ 合规提示
`client_secret` 与区域逻辑来自对 QNAP 客户端的逆向。若你要**公开发布**这个三方客户端，建议：
- 不要内嵌 `client_secret`（它属于 QNAP，滥用可能违反其服务条款）
- 优先提供「手动输入 NAS 地址」路径，把 QID 作为可选的、用户自备凭据的功能
- 明确声明这是非官方客户端

---

## 7.9 待验证

| 项 | 说明 |
|---|---|
| `setRegion` 的上层调用者 | 谁决定「国际/中国」与「alpha/生产」 |
| `X-QNAP-CHECK` 的算法 | 疑似请求签名/校验和，反汇编构造处或抓包对比 |
| `PORTTYPE` / `CONNECT_IP_TYPE` 枚举数值 | 字符串中无取值 |
| `QIDAPIGetDeviceID` 模板是否启用 | 无代码引用 |
| 账号站是否支持 `password` grant | 抓包验证（决定能否免浏览器登录） |
| `%1%2:%3` 前 6 个 `PB_W` 是否是 3 组候选 | 反汇编 `signin`/`getAllDeviceInfo` |
| CloudLink 隧道建立细节 | 仅在需要 NAT 穿透时研究（`cloudlinkP2P.dll` 是 Go 二进制） |
