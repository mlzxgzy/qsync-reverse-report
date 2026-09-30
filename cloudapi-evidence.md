# Qsync for Windows —— QNAP 云账号（QID / myQNAPcloud）侧 API 与登录流程逆向证据

分析目标：Qsync 6.1.0.0831 Windows（PE 构建时间 2026-08-31），模块 `Qsync.exe` / `QsyncLib.dll` / `QsyncAPI.dll` / `QSystemLib.dll` / `cloudlinkP2P.dll`。

约定：
- 偏移一律写成 `模块@0x<文件偏移>`，并附字符串原文。
- 涉及"虚拟地址"（`__ImageBase` 相关）时，`Qsync.exe` 的 VA = `0x400000 + RVA`，字符串块位于 `.rdata`（RVA `0x2db000`）。本文件中凡写 `va=0x6f....` 处即该字符串的 VA，可按 `Qsync.exe@0x2f0xxx` 对应的文件偏移复核。
- 未经证实的一律标 **未确认**。

**地址格式说明（各模块不同，引用时按此表换算）**
| 模块 | ImageBase | .text 映射 | 本报告引用格式 |
|---|---|---|---|
| `Qsync.exe` | `0x400000` | `VA = 0x401000 + (file - 0x400)` | `Qsync.exe@0x<file>`（文件偏移） |
| `QsyncLib.dll` | `0x10000000` | `VA = 0x10001000 + (file - 0x400)` | `QsyncLib.dll@0x00<file>`（文件偏移）；日志字符串额外给出 `VA=0x100....` |
| `QsyncAPI.dll` | `0x10000000` | `VA = 0x10001000 + (file - 0x400)` | 同上 |
| `QSystemLib.dll` | `0x10000000` | `VA = 0x10001000 + (file - 0x400)` | `QSystemLib.dll@0x000<file>`（文件偏移）；`.rdata` 常量另给 `va=0x100....` |
（`QsyncLib.dll` 的 `.text` RawData 起始文件偏移为 `0x400`、VA `0x1000`；`QSystemLib.dll` 同形。故 `VA - 0x10000000 - 0x1000 + 0x400 = file`。）

---

## 1. client_id / client_secret 的实际字面值

### 结论
**没有"从配置/注册表/接口下发"这一选项：client_id 与 client_secret 是硬编码在 `Qsync.exe` 与 `QsyncLib.dll` 的 `.rdata` 里的字符串常量**，三处（Qsync.exe 两处 + QsyncLib.dll 一处）字面值完全一致：

| 项 | 值 | 长度 |
|---|---|---|
| `client_id` | `593a4f08d6b82f791bacd7db` | 24 字符（12 字节 hex） |
| `client_secret` | `g9LsfI…gfXQp`（公开版已掩码） | 48 字符 |

> ⚠️ **公开版掩码说明**：`client_secret` 的完整值已从报告中移除，以免在公开仓库散布第三方凭据
> （GitHub secret scanning 也会因此报警）。完整值可从**你自己合法获得的** Qsync 安装包直接提取：
> ```bash
> ./tools/reveal-credentials.sh "/path/to/Qsync/Qsync.exe"
> # 或按文件偏移查看：Qsync.exe 偏移 0x002f0e98 附近
> ```
> `client_id` 是客户端标识（非密钥），保留原文。

### 证据

**A. Qsync.exe 中的字面值**
- `Qsync.exe@0x002f0e6c` — `593a4f08d6b82f791bacd7db`（`va=0x6f1c6c`）
- `Qsync.exe@0x002f0e98` — `g9LsfI…gfXQp`（公开版已掩码）（`va=0x6f1c98`）
- 相邻的键名字符串（同一 Qt 字面量块，顺序即源码书写顺序）：
  `Qsync.exe@0x002f0e60` = `client_id`，`Qsync.exe@0x002f0e88` = `client_secret`，
  `Qsync.exe@0x002f0e44` = `grant_type`，`Qsync.exe@0x002f0e50` = `refresh_token`

**B. 代码引用点（Qsync.exe，x86 绝对地址立即数）**
- `Qsync.exe@0x0007b0a6` 处 `push 0x6f1c6c` → `mov [ebp-0x14]`（构造 `client_id` 的 QString）
- `Qsync.exe@0x0007b159` 处 `push 0x6f1c98` →（同一函数内，长度 0x30=48）
- `Qsync.exe@0x0007ea0b` 处 `push 0x6f1c98`（授权码换 token，函数 `0x47f440` 一带）
- `Qsync.exe@0x0007f7d0` 处 `push 0x6f1c6c`（拼 OAuth 授权 URL，函数 `0x4801e0`）

**C. QsyncLib.dll 中的字面值（同一个 client，另一份拷贝）**
- `QsyncLib.dll@0x0041eeea` — `593a4f08d6b82f791bacd7db`（`va=0x1041f...`）
- `QsyncLib.dll@0x0041eee5` — `g9LsfI…gfXQp`（公开版已掩码）
- 这两处位于 `CQsyncConnection::CheckAccessTokenAndUpdate` / `GetDeviceInformationV11` 区间（同区间日志见 `QsyncLib.dll@0x0041f30` `'CQsyncConnection::CheckAccessTokenAndUpdate QIDAPIAPPSignin success'`），即 NAS 侧 QID 登录/刷新 token 时直接内联了同一对凭据。

**D. 与 CLI/配置无关的证据**
- `Qsync.exe` 的导入表里没有 `QSystemLib.dll!QcQcloudAPIHelper::setAppIdSecret`（`Qsync.exe` 导入的 46 个 `QSystemLib` 符号只有 `Qcommon::Logger` / `WinDirMonitor` / `DirMonitor` / `Qcommon::Settings` 等，见 `qsync-analysis/out/pe_dump.json` 的 `Qsync.exe.imports["QSystemLib.dll"]`）。
- 即：`Qsync.exe` 的 `CCloudHttpService_V1/V2`、`CDCSCloudHttpService` 不走"外部下发凭据"的通用 helper，而是自带这对常量。
- 另一个独立实现 `QSystemLib.dll` 的 `?readClient@QcOauth2Helper@@AAEXXZ` / `?setAppIdSecret@QcQcloudAPIHelper@@QAEX_NVQString@@1@Z`（导出序数 304 / 318）**签名里带 `QString,QString` 参数**，说明那条路径的 appId/secret 是调用方传入的；但 Qsync 主体并不使用它（见上一条）。因此第 1 问的落点是"硬编码"，不是"下发"。

**E. 同一套流程里另外出现的 UUID 常量（不是 client_id）**
`Qsync.exe@0x0074728c` = `dd0c1daf-3237-4a2b-9737-f40a6e58799b`、`@0x007472b4` = `5354ddf5-a807-424c-b0c1-68d754ca61ce`、`@0x007472fc` = `7f4ddd1f-6428-405e-8273-178d5a18643a`、`@0x00747324` = `515ef0b5-254e-4cf5-b5a9-2a6038069e6b`、`@0x0074735c` = `efdc0ec5-72be-4714-9af6-26ecf76992c9`、`@0x00747384` = `099a2183-c5e6-4284-a442-eb882e3ed85d`、`@0x007473c0` = `85264ec9-614b-4b84-b630-4b738aa476d2`、`@0x007473e8` = `f2cd8f9a-4712-4f50-b283-a06b8aba4f1a`。这些成对出现在 DCS 问卷/打点结构里（字段 `deviceVagueUID` / `uuid` / `questionnaire_uuid`，见第 6 问），**不是** OAuth 凭据。另有 `Qsync.exe@0x007472c4`（即 `QsyncLib.dll` 对应）`com.qnap.qsync.windows.2017`，是 `X-QNAP-APP-ID`/app 标识，也不是 client_id。

---

### 1.1 区域/域名常量总表（Qsync.exe 内）

`Qsync.exe@0x002f0d2c` 起是一整块连续的 Qt 字面量（顺序即源码顺序），逐个列出（文件偏移 → 原文）：

| 文件偏移 | 原文 | 用途 |
|---|---|---|
| `0x2f0d2c` | `https://alpha-account.qnap.com/` | alpha 账号站（国际） |
| `0x2f0d4c` | `https://account.qnap.com/` | 生产账号站（国际） |
| `0x2f0d68` | `https://alpha-account.qnap.com.cn/` | alpha 账号站（中国） |
| `0x2f0d8c` | `https://account.qnap.com.cn/` | 生产账号站（中国） |
| `0x2f0dac` | `%1=%2` | 表单键值对 |
| `0x2f0db4` | `access_token` | |
| `0x2f0dc8` | `%1%2?%3` | URL+查询串 |
| `0x2f0dd0` | `oauth/tokeninfo` | 用户信息 GET |
| `0x2f0de0`/`0x2f0de8`/`0x2f0df0`/`0x2f0e00` | `user`/`email`/`display_name`/`id` | tokeninfo 响应字段 |
| `0x2f0e04` | `v1.1/me` | /api/v1.1/me |
| `0x2f0e0c`/`0x2f0e14`/`0x2f0e20`/`0x2f0e2c`/`0x2f0e34` | `result`/`first_name`/`last_name`/`limit`/`organization_id` | 设备列表响应字段 |
| `0x2f0e44`/`0x2f0e50` | `grant_type`/`refresh_token` | |
| `0x2f0e60`/`0x2f0e6c` | `client_id` / `593a4f08d6b82f791bacd7db` | |
| `0x2f0e88`/`0x2f0e98` | `client_secret` / `g9LsfI…gfXQp`（公开版已掩码） | |
| `0x2f0ecc` | `oauth/token` | |
| `0x2f0f38` | `client_credentials` | （见第 6 问，DCS 打点用） |
| `0x2f0f4c` | `https://core2.api.alpha-myqnapcloud.com/` | QID API（alpha，.com） |
| `0x2f0f78` | `https://core2.myqnapcloud.io/` | QID API（生产，.io） |
| `0x2f0f98` | `https://core2.api.alpha-myqnapcloud.cn/` | QID API（alpha，.cn） |
| `0x2f0fc0` | `https://core2.api.myqnapcloud.cn/` | QID API（生产，.cn） |
| `0x2f0fe4` | `offset` | |
| `0x2f0fec` | `v1.2/device` | |
| `0x2f0ff8` | `v1.2/device/sharedtome` | |
| `0x2f1010`~`0x2f10b8` | `code`/`info`/`error`/`host_name`/`device_name`/`fw_model_name`/`model_name`/`mac_address`/`cluster_uid`/`device_id`/`firmware_version`/`firmware_number`/`qid_login_enabled`/`region` | 设备响应字段 |
| `0x2f10c0`/`0x2f10c4` | `GLB` / `CHN` | 区域取值 |
| `0x2f10c8`~`0x2f1174` | `domain_name`/`wan_ips`/`ipv4`/`local_services`/`service_name`/`WebAdministration`/`Secured WebAdministration`/`internal_port`/`external_port`/`published`/`organization_name`/`organization_site_name` | 端口映射字段 |
| `0x2f12a4` | `http://127.0.0.1` | 本地 OAuth 回调 |
| `0x2f12b8` | `/oauth2/callback` | |
| `0x2f12cc` | `/oauth/auth?response_type=code&client_id=` | |
| `0x2f12f8` | `&code_challenge_method=S256` | PKCE |
| `0x2f1314` | `&code_challenge=` | |
| `0x2f1328` | `&redirect_uri=` | |
| `0x2f1338` | `%1oauth/token` | |
| `0x2f1348` | `?access_token=%1` | |
| `0x2f135c` | `%1oauth/tokeninfo` | |
| `0x2f1370` | `%1signin?create=0&state=` | |
| `0x2f1390` | `&hide_signup=true&hide_social=true&hide_forget_password=true&hide_activation_mail=true&switch_account=true` | |
| `0x2f13fc` | `&qid=` | |
| `0x2f14b8` | `grant_type=authorization_code&client_id=%1&client_secret=%2&code=%3&code_verifier=%4&redirect_uri=%5` | 带 PKCE |
| `0x2f1338` 等 | 见上 | |

**第二块 QID API 字面量**（`Qsync.exe@0x007470a0` 起，`X-QNAP-*` 头与 DCS/问卷）：

| 文件偏移 | 原文 |
|---|---|
| `0x7470d4` / `0x7470f8` | `analytics.api.alpha-myqnapcloud.com` / `analytics.api.alpha-myqnapcloud.cn` |
| `0x74711c` / `0x74713c` | `analytics.api.myqnapcloud.com` / `analytics.api.myqnapcloud.cn` |
| `0x74715c` | `%1%2:%3/v1/record/%4` |
| `0x747174` | `application/x-www-form-urlencoded` |
| `0x747198` / `0x7471a8` / `0x7471cc` | `X-QNAP-APP-ID` / `X-QNAP-SUBAPP-ID` / `X-QNAP-APP-VER` |
| `0x7471bc` | `Content-Length` |
| `0x7471dc` | `Bearer %1` |
| `0x7471e8` / `0x7471f4` / `0x747204` | `Keep-Alive` / `Cache-Control` / `no-cache` |
| `0x747210` / `0x747224` | `stage-dcs.qnap.com` / `dcs.qnap.com` |
| `0x747234` | `%1%2/api/v1/authorizes/q_token` |
| `0x747254` | `application/json; charset=utf-8` |
| `0x747468` | `X-DCS-Q-TOKEN` |
| `0x74744c` | `%1%2/api/v1/questionnaires` |
| `0x747490` | `grant_type=authorization_code&client_id=%1&client_secret=%2&code=%3&redirect_uri=%4` |
| `0x7474e8` | `grant_type=password&client_id=%1&client_secret=%2&username=%3&password=%4` |
| `0x747534` | `grant_type=client_credentials&client_id=%1&client_secret=%2` |
| `0x747570` | `grant_type=refresh_token&client_id=%1&client_secret=%2&refresh_token=%3` |
| `0x7475b8`/`0x7475d0`/`0x7475ec`/`0x747600` | `alpha-account.qnap.com` / `alpha-account.qnap.com.cn` / `account.qnap.com` / `account.qnap.com.cn` |
| `0x747614` | `%1%2:%3/oauth/token` |
| `0x747628` | `access_token=%1` |
| `0x747638` | `%1%2:%3/oauth/signout` |
| `0x747650`/`0x747670`/`0x747690`/`0x7476ac` | `core.api.alpha-myqnapcloud.com` / `core.api.alpha-myqnapcloud.cn` / `core.api.myqnapcloud.com` / `core.api.myqnapcloud.cn` |
| `0x7476c4` | `%1%2:%3/v1.1/device/search?device_name=%4` |
| `0x7476f0` | `%1%2:%3/v1.1/device` |

**QSystemLib.dll 内同名常量**（独立实现，见第 7 问）：
`QSystemLib.dll@0x0002ac08` `https://alpha-account.qnap.com/`、`@0x2ac28` `https://account.qnap.com/`、`@0x2ac44` `https://alpha-account.qnap.com.cn/`、`@0x2ac68` `https://account.qnap.com.cn/`、`@0x2adac` `https://auth.alpha.myqnapcloud.io/`、`@0x2add0` `https://auth.myqnapcloud.io/`、`@0x2adf0` `https://auth.api.alpha.myqnapcloud.cn/`、`@0x2ae18` `https://auth.api.myqnapcloud.cn/`、`@0x2aef0` `https://core2.alpha.myqnapcloud.io/`、`@0x2af14` `https://core2.myqnapcloud.io/`、`@0x2af34` `https://core2.api.alpha.myqnapcloud.cn/`、`@0x2af5c` `https://core2.api.myqnapcloud.cn/`、`@0x2b048` `https://edge.alpha.myqnapcloud.io/`、`@0x2b06c` `https://edge.myqnapcloud.io/`、`@0x2b08c` `https://edge.api.alpha.myqnapcloud.cn/`、`@0x2b0b4` `https://edge.api.myqnapcloud.cn/`。

---

## 2. QID 登录流程完整时序

### 2.1 两个入口

**入口 A：账号密码登录（resource-owner password grant）**
- URL 模板（Qsync.exe）：`Qsync.exe@0x00747614` = `%1%2:%3/oauth/token`
  - 由 `%1`=scheme 前缀、`%2`=账号域名、`%3`=端口 拼成。
  - scheme/端口在 `Qsync.exe@0x006005ee` 一带动态选择：`push 8 / push 'https://'(@0x006e5a94)`，端口常量 `0x50`(=80) / `0x1bb`(=443)，用 `cmovne/cmove` 二选一（同一函数的汇编见第 4/7 问）。
- 请求体模板：`Qsync.exe@0x007474e8` = `grant_type=password&client_id=%1&client_secret=%2&username=%3&password=%4`
- 方法：`POST`（方法名常量在 Qt 字面量中以致 `%1%2:%3/oauth/token` 的方式使用；`Qsync.exe` 未出现裸 ASCII `POST`，Qt 侧为 `QNetworkAccessManager::post`，**方法为 POST 属强推断**）
- Content-Type：`Qsync.exe@0x002f8e7c` = `application/x-www-form-urlencoded; charset=UTF-8`、`Qsync.exe@0x00747174` = `application/x-www-form-urlencoded`
- 头：`X-QNAP-APP-ID`(@0x747198)、`X-QNAP-SUBAPP-ID`(@0x7471a8)、`X-QNAP-APP-VER`(@0x7471cc)、`Content-Length`(@0x7471bc)
- 注意：**该 password 模板所在的代码区（`Qsync.exe@0x00600277`~`0x0060045f`）属于 `CDCSCloudHttpService`（DCS 打点/问卷服务），不是账号站登录**。账号站登录实际走的是"浏览器授权码"（入口 B）。证据：模板 `grant_type=authorization_code&client_id=%1&client_secret=%2&code=%3&redirect_uri=%4`（`0x747490`）与 `password` 模板同在一个函数里被 `push`，函数起点为 `Qsync.exe@0x00600580` 一区（DCS 的 token 获取），其中先尝试 password/client_credentials/refresh_token 等多种 grant（`Qsync.exe@0x00600277` `authorization_code`、`@0x600361` `password`、`@0x60044b` `client_credentials`、`@0x6004d7` `refresh_token`）。

**入口 B：OAuth 授权码（PKCE）+ 本地回调（Qsync 主用的 QID 登录）**
模块内实现：`Qsync.exe` 的"`CQIDOauth2Helper`"（本地 HTTP 服务 + `QcOauth2Helper` 语义），以及 `QSystemLib.dll` 的 `QcOauth2Helper`（导出名 `?getOauthLoginUrl@QcOauth2Helper@@SA?AVQString@@V2@00_N1@Z` 序数 181）。

时序（全部有字符串证据）：

1. **选账号站域名**（国际 vs 中国，alpha vs 生产）
   - `https://account.qnap.com/`(`Qsync.exe@0x2f0d4c`) / `https://account.qnap.com.cn/`(`@0x2f0d8c`) / `https://alpha-account.qnap.com/`(`@0x2f0d2c`) / `https://alpha-account.qnap.com.cn/`(`@0x2f0d68`)
   - 选择逻辑见第 7 问。
2. **起本地回调服务**：`http://127.0.0.1`(`Qsync.exe@0x2f12a4` / `@0x6f20a4`) + `%1:%2%3`(`Qsync.exe@0x2f129c`) + `/oauth2/callback`(`Qsync.exe@0x2f12b8` / `@0x6f20b8`)
   - 端口常量在构造函数 `Qsync.exe@0x0047f230`：`Qsync.exe@0x0047f268` `mov ecx,0x10cc`(=4300)、`@0x47f26d mov eax,0x10f7`(=4343)、`@0x47f272 cmovne eax,ecx` → 主端口 4300，备端口 4343。
   - 备用端口族：`Qsync.exe@0x0047f30f mov ecx,0x37dc`(=14300)、`@0x47f314 mov eax,0x3807`(=14343)。
   - 日志：`Qsync.exe@0x2f1408` `[QID][helper] port=%d unavailable, falling back to alternative port`、`@0x2f144c` `[QID][helper] alt port=%d also unavailable, giving up`、`@0x2f148c` `[QID][helper] result: %s, finalPort=%d`
3. **生成 PKCE**：`QSystemLib.dll` 导出 `?generateCodeVerifier@QcOauth2Helper@@SA?AVQString@@XZ`、`?generateCodeChallenge@QcOauth2Helper@@SA?AVQString@@V2@@Z`；URL 追加 `&code_challenge_method=S256`(`Qsync.exe@0x2f12f8`)、`&code_challenge=`(`@0x2f1314`)
4. **打开浏览器授权**：`/oauth/auth?response_type=code&client_id=`(`Qsync.exe@0x2f12cc`) + `<client_id>` + `&redirect_uri=`(`@0x2f1328`) + 回调地址 + `&code_challenge_method=S256&code_challenge=...`
   - 另有一路基于账号站 SPA 的入口：`%1signin?create=0&state=`(`Qsync.exe@0x2f1370`) + `&qid=`(`@0x2f13fc`) + `&hide_signup=true&hide_social=true&hide_forget_password=true&hide_activation_mail=true&switch_account=true`(`@0x2f1390`)
5. **回调收 code**：本地 HTTP server 收到 `GET /oauth2/callback?code=...`（`Qsync.exe@0x0047f48f push 4 / push 'code'`(@0x6f1e10)），触发 Qt 信号 `1slotOauthCodeArrived()`(`Qsync.exe@0x2f11ec`)、`2onRequestUrlArrived()`(`@0x2f1204`)、`1slotAuthFlowCompleted()`(`@0x2f121c`)、`2onAuthDoneFlowCompleted()`(`@0x2f1238`)
6. **换 token**：`POST {account}/oauth/token`，body = `grant_type=authorization_code&client_id=593a...&client_secret=g9Ls...&code=<code>&code_verifier=<verifier>&redirect_uri=http://127.0.0.1:<port>/oauth2/callback`
   - 证据：`Qsync.exe@0x0047f5fc push 0x30 / push 0x6f1c98`（secret）、`@0x47f608 push 0x18 / push 0x6f1c6c`（client_id）、`@0x47f656 push 0x64 / push 0x6f22b8`（= `Qsync.exe@0x2f14b8` 模板块原文）
7. **取用户信息**：`GET {account}/oauth/tokeninfo?access_token=<token>`，模板 `%1oauth/tokeninfo`(`Qsync.exe@0x2f135c`)，响应字段 `user`/`email`/`id`/`display_name`（`Qsync.exe@0x2f0de0`~`0x2f0df0`），另 `Qsync.exe@0x0047fabf` 起依次读取 `user`/`email`/`id`/`display_name`
   - 原始 tokeninfo 模板也出现在 `%1%2?%3`(`Qsync.exe@0x2f0dc8`) + `oauth/tokeninfo`(`@0x2f0dd0`) + `access_token`(`@0x2f0db4`) 组合中

### 2.2 拿到 token 后的刷新/登出
- 刷新：`grant_type=refresh_token&client_id=%1&client_secret=%2&refresh_token=%3`（`Qsync.exe@0x2f0e50` 邻近区无独立模板，模板见 `Qsync.exe@0x00747570`；`Qsync.exe@0x0047bea3` 一带用 `refresh_token`(`0x6f1c50`)+`grant_type`(`0x6f1c44`)）
- 登出：`{account}/oauth/signout`，模板 `%1%2:%3/oauth/signout`(`Qsync.exe@0x00747638`)，另有 `oauth/signout`(`Qsync.exe@0x00747640`) 直接拼接形式
- 登出/刷新在 `QsyncLib.dll` 侧：`%ls%ls:%d/oauth/token`(`QsyncAPI.dll@0x000ea112`)、`%ls%ls:%d/oauth/signout`(`QsyncAPI.dll@0x000ea648`)、`%ls%ls:%d/oauth/tokeninfo?access_token=%ls`(`QsyncAPI.dll@0x000e9f30`)

### 2.3 响应字段 → `CCloudHttpAuthToken`
`Qsync.exe@0x0060418e` `access_token`、`@0x6042b1` `token_type`、`@0x6044e8` `expires_in`、`@0x603f78` `error`、`@0x604087` `error_description`。
对应 Dart/导出访问器（`Qsync.exe` 导出表，见 `qsync-analysis/out/pe_dump.json`）：`getAuthToken`、`getRefreshToken`、`getTokenType`、`getExpiresIn`、`getError`、`getErrorDescription`。

### 2.4 `CCloudHttpService_V1/V2` 与 URL 模板的对应关系
`Qsync.exe` 内 `CCloudHttpService` 实现集中在 VA `0x5f8xxx`~`0x605xxx`（文件偏移 `0x1f8xxx`~`0x205xxx`）。该区间内被 `push` 的字符串常量（自动提取，`→` 后为地址）给出精确对应：

| 导出方法 | 关键常量（文件偏移 = 原文） | 含义 |
|---|---|---|
| `?signin@CCloudHttpService_V2@@QAE?AW4_QCLOUD_HTTP_API_RESULT_@@VQString@@00000000PA_NAAVCCloudHttpAuthToken@@@Z` | `0x1f89ef` `APPVersion`、`0x1f8984` `AccessToken`、`0x1f8d73` `Bearer ...`…；`0x1fab82` `APPVersion`、`0x1fab45` `RefreshToken` | 8 个 QString 入参：3 个 URL 候选（scheme+host ×3）+ client_id/secret + username/password/refresh_token；token 放 header `Authorization: Bearer %1` |
| `?signout@CCloudHttpService_V2@@QAE?AW4_QCLOUD_HTTP_API_RESULT_@@VQString@@00PA_N@Z` | `0x1ff644` `APPVersion`、`0x1ffefc` `AccessToken`、`0x1fffca` `core.api.myqnapcloud.cn`、`0x1ff8f0`(见下) | 3 个 QString（URL 候选） |
| `?getAuthToken@CDCSCloudHttpService@@QAE?AW4_QCLOUD_HTTP_API_RESULT_@@AAVQString@@PA_N@Z` | `0x1f9823`/`0x1f9857`/`0x1fa51b` `GrantType`…；`0x1fa99a` `GrantType`、`0x1fa9d7` `AccessToken` | DCS token（另有 V1 版本 `getAuthToken@CCloudHttpAuthToken`） |
| `?getAllDeviceInfo@CCloudHttpService_V2@@QAE?AW4_QCLOUD_HTTP_API_RESULT_@@VQString@@00PA_NAAV?$QVector@PAVCCloudDeviceDetailInfo@@@@@Z` | `0x1f8fcf` `APPVersion`、`0x1f8f64` `AccessToken`、`0x1f8da7`/`0x1f8db3` `Bearer ...`…；请求 URL 由 `%1%2:%3/v1.1/device/search?device_name=%4`(`Qsync.exe@0x7476c4`)、`%1%2:%3/v1.1/device`(`@0x7476f0`) 驱动（见第 3 问） | 5 个 QString + 1 `bool*` + `QVector<CCloudDeviceDetailInfo*>&` |
| `?getDeviceInfo@CCloudHttpService_V2@@QAE?AW4_QCLOUD_HTTP_API_RESULT_@@VQString@@000PA_NAAVCCloudDeviceInfo@@@Z` | `0x1f97ef` `APPVersion`、`0x1f9784` `AccessToken`、`0x1f97bb`(AccessToken)、`0x1f99a6` `device_vague_uid`、`0x1f9c02` `DeviceName`… | 5 个 QString + `bool*` + `CCloudDeviceInfo&` |

> 精确到"哪一个字符串属于哪一个方法"可用同一技巧复核：把 `qsync-analysis/out/str_Qsync.exe.txt` 中的字符串按 `0x2f....` 文件偏移查出来，在反汇编中搜其 `va`（`va = 0x400000 + (.rdata RVA)`）即可。

### 2.5 认证头与 HTTP 细节
`Qsync.exe@0x00600d24` `X-QNAP-APP-ID`、`@0x600d9d` `X-QNAP-SUBAPP-ID`、`@0x600e16` `X-QNAP-APP-VER`、`@0x600e8f` `Authorization`、`@0x600e9b` `Bearer %1`、`@0x600cb2` `Content-Type`、`@0x600cbf` `application/x-www-form-urlencoded`、`@0x600ceb` `Accept`、`@0x600cf8` `application/json`、`@0x600f08` `Connection`、`@0x600f15` `Keep-Alive`、`@0x600f41` `Cache-Control`、`@0x600f4e` `no-cache`、`@0x6025ab` `Content-Length`。

`Qsync.exe` 打印：`@0x5fd17e` ` URL Redirect!`、`@0x5fd1fd` `EMPTY!!`、`@0x5fd232` `API Result:%1`、`@0x5fd35c` `Err request:%1`、`@0x5fd02e` `1slotNetworkAccessManagerFinish(QNetworkReply*)`、`@0x5fcfed` `1onSslError(QNetworkReply*, QList<QSslError>)`、`@0x5fd018` `2finished(QNetworkReply*)`。

---

## 3. 设备发现（拿到 QID token 之后）

### 3.1 端点（Qsync.exe 侧，`core2` 云）

两个地址族，均由 `%1%2:%3` 前缀（scheme + host + port）拼出：

| 模板原文 | 文件偏移 | 说明 |
|---|---|---|
| `%1%2:%3/v1.1/device` | `Qsync.exe@0x007476f0` | 列出账号下设备（默认 / 按 offset+limit 翻页） |
| `%1%2:%3/v1.1/device/search?device_name=%4` | `Qsync.exe@0x007476c4` | 按设备名查 |
| `%1%2:%3/v1.2/device` | `Qsync.exe@0x002f0fec` | v1.2 设备列表 |
| `%1%2:%3/v1.2/device/sharedtome` | `Qsync.exe@0x002f0ff8` | 别人分享给我的设备 |
| `%1%2:%3/v1.1/me`（见 `v1.1/me`） | `Qsync.exe@0x002f0e04` | 当前用户/组织 |
| `oauth/tokeninfo` + `?access_token=%1` | `Qsync.exe@0x002f0dd0` / `@0x2f1348` | 用户信息 |

域名（`Qsync.exe`，均以 `/` 结尾，拼 `${host}:${port}${path}`）：
`https://core2.myqnapcloud.io/`(`0x2f0f78`)、`https://core2.api.myqnapcloud.cn/`(`0x2f0fc0`)、
`https://core2.api.alpha-myqnapcloud.com/`(`0x2f0f4c`)、`https://core2.api.alpha-myqnapcloud.cn/`(`0x2f0f98`)；
以及"新版无 core2"族 `core.api.myqnapcloud.com`(`Qsync.exe@0x747690`)、`core.api.myqnapcloud.cn`(`@0x7476ac`)、`core.api.alpha-myqnapcloud.com`(`@0x747650`)、`core.api.alpha-myqnapcloud.cn`(`@0x747670`)，与 `https://`(`Qsync.exe@0x6e5a94`) 拼接（`Qsync.exe@0x006005ee`/`@0x00600be2`）。

### 3.2 `getAllDeviceInfo` / `getDeviceInfo` / `getDeviceId` 的调用形态（Qsync.exe）
- `getAllDeviceInfo(QString, QString, QString, bool*, QVector<CCloudDeviceDetailInfo*>&)`
  → 3 个 QString 正是 **3 个候选 (scheme+host)**（同一云有国际/中国/alpha 多组，见第 7 问）。每个候选都会尝试同一 path。
- `getDeviceInfo(QString, QString, QString, QString, bool*, CCloudDeviceInfo&)`
  → 4 个 QString；结合字符串 `device_vague_uid`(`Qsync.exe@0x00746c8c`)、`session_code`(`Qsync.exe@0x00746e08`)、`DeviceName`(`Qsync.exe@0x00746d7c`)、`DeviceId`(`Qsync.exe@0x00746d60`)、`ProjectId`(`Qsync.exe@0x00746d6c`)、`ClientId`(`Qsync.exe@0x00746d04`)、`AccessToken`(`Qsync.exe@0x00746d54`)、`APPVersion`(`Qsync.exe@0x00746d48`)，第 4 个 QString 是 **device_vague_uid / device name**（QS 侧把设备名或 vague uid 作为查询键）。
- `getDeviceId@CCloudDeviceInfo@@QAE?AVQString@@XZ` / `getDeviceId@CCloudDeviceDetailInfo@@...` 是**结构体访问器**，不吃 URL，"设备 ID"直接来自 v1.1/v1.2 设备列表响应中的 `device_id`。

### 3.3 响应字段名 → `CCloudDeviceInfo` / `CCloudDeviceDetailInfo`
Qsync.exe 解析器（`Qsync.exe@0x0047db30` = `getDeviceInfo` 的 JSON 解析段）依次读取：

`code`(`Qsync.exe@0x002f1010`)、`result`(`Qsync.exe@0x002f0e0c`)、`info`(`Qsync.exe@0x002f1018`)、`error`(`Qsync.exe@0x002f1020`)、
`host_name`(`@0x2f1028`)、`device_name`(`@0x2f1034`)、`fw_model_name`(`@0x2f1040`)、`model_name`(`@0x2f1050`)、`mac_address`(`@0x2f105c`)、`cluster_uid`(`@0x2f1068`)、`device_id`(`@0x2f1074`)、`firmware_version`(`@0x2f1080`)、`firmware_number`(`@0x2f1094`)、`qid_login_enabled`(`@0x2f10a4`)、`region`(`@0x2f10b8`)、`domain_name`(`@0x2f10c8`)、`wan_ips`(`@0x2f10d4`)、`ipv4`(`@0x2f10dc`)、`local_services`(`@0x2f10e4`)、`service_name`(`@0x2f10f4`)、`WebAdministration`(`@0x2f1104`)、`Secured WebAdministration`(`@0x2f1118`)、`internal_port`(`@0x2f1134`)、`external_port`(`@0x2f1144`)、`published`(`@0x2f1154`)、`organization_name`(`@0x2f1160`)、`organization_site_name`(`@0x2f1174`)

detail 结构的字段族（`Qsync.exe@0x60418e`~`@0x607a9e`）：
`access_token`、`token_type`、`expires_in`、`code`、`result`、`device_id`、`device_name`、`domain_name`、`info`、
`lan_ips`(`Qsync.exe@0x60585a`)、`ipv4`(`@0x605bb4`)、`ipv6`(`@0x605d24`)、`lan_gateway`(`@0x606034`)、`wan_ips`(`@0x6065f5`)、
`local_services`(`@0x606dbc`)、`service_name`(`@0x607007`)、`external_port`(`@0x607161`)、`internal_port`(`@0x607245`)、`uri`(`@0x60731d`)、`private`(`@0x60746c`)、`published`(`@0x60754d`)、`access_control_mode`(`@0x607957`)、`starred`(`@0x607a9e`)

`QsyncAPI.dll` 侧的完整响应字段表（`QsyncAPI.dll@0x000e8428` 起，ASCII 块）：
`serviceName`、`proto`、`WebAdministration`、`TCP`、`subServiceName`、`Secured`、`internalPort`、`externalPort`、
`error_description`、`access_token`、`token_type`、`refresh_token`、`expires_in`、`public_ip`、`device_id`、`token`、`access_code`、`access_control_mode`、`user_id`、`domain_name`、`info`、`local_services`、`local_users`、`model_info`、`permissions`、`user_name`、`service_name`、`uri`、`external_port`、`internal_port`、`private`、`published`、`device_type`、`model_name`、`fw_model_name`、`hw_serial_number`、`fw_serial_number`、`mac_address`、`host_name`、`firmware_version`、`firmware_build_number`、`firmware_patch_version`、`agent_version`、`firmware_number`、`lan_gateway`、`ipv4`、`ipv6`、`lan_ips`、`wan_ips`、`latest_fw_version`、`latest_fw_build_number`、`latest_fw_patch_version`、`img_url`、`basic_info`、`remote_access`、`public_local_service`、`private_local_service`、`public_package_services`、`protected_package_services`、`private_package_services`、`type`、`cloud_link_id`、`wan_ip`、`ddns`、`lan_ip`、`email`、`mycloudnas_dn`、`ddns_dn`、`ext_ip`、`qbox_slave_id`、`domain`、`netbios`、`TrustedDomainEnable`。
以及 `QsyncAPI.dll@0x000e81d8` 一带 vLink 结构：`vlinkId`、`vlinkType`、`vlinkVersion`、`lanIp`、`lanGW`、`wanIp`、`actTime`、`StatusCode`、`message`。

这些字段与 `Qsync.exe` 导出访问器一一对应：`getLanIPs`/`getWanIPs`/`getDeviceId`/`getDeviceName`/`getDeviceType`/`getHostName`/`getMacAddress`/`getModelName`/`getFwModelName`/`getFwSerialNumber`/`getHwSerialNumber`/`getFirmwareVersion`/`getFirmwareBuildNumber`/`getFirmwarePatchVersion`/`getFWNumber`/`getRemoteAccessSupported`/`getAgentVersion`/`getLocalServices`（内部类 `CCloudDeviceInfo::CLacalService`）。

### 3.4 QsyncLib 侧的设备发现（NAS 端 → 云）
`QsyncLib.dll@0x005583b4`（utf16）`CQsyncConnection(%s)::GetDeviceInformationV11 ...`，流程顺序有明确日志：
- `QsyncLib.dll@0x0043864` `CloseQUTKTunnel`
- `@0x443893` `(Try CloudLink first)`
- `@0x4438ce` `(OpenQUTKTunnel failure)` / `@0x4438f0` `failed` / `@0x44391b` `CloudLink dwServicePort = %d , dwMappedPort = %d` / `@0x44393f` `(OpenQUTKTunnel successfully)`
- `@0x443c5c` `(Link with CloudLink mode first)` / `@0x443cd3` `(Link with CloudLink mode)(failure) first`
- `@0x444289` `Get Cloud Info Start`、`@0x4455c` `QIDAPIGetCloudInfo OK`、`@0x44593` `SupportQUTK(%d->%d)`、`@0x445c3` `set retry sleep time to 1`、`@0x44612` `QIDAPIGetCloudInfo failed(...)`、`@0x44646` `Cloudlink_p2p_get_cloud_info failed`
- `@0x4473a` `QIDAPIGetDeviceInfoByName dwAPIResult(%d) uAPIResult(%d) devices(%d)`
- `@0x448b2` `QIDAPIGetCloudLinkSetting cloudlink(%s)`、`@0x448dd` `SupportQUTK(%d)`、`@0x44904` `QIDAPIGetCloudLinkSetting dwTmpResult(%d) uDeviceCount(%d)`
- `@0x456b9` `(Try CloudLink)`、`@0x45c8d` `(Link with CloudLink mode)`、`@0x45d7f` `(Link with CloudLink mode)(failure)`
- `@0x461b4` `(Get MCNAPIGetVLinkInfo failure, TotalQueryQCloudCount = %d, dwAPIResult = %d)`

`QsyncLib.dll@0x0042d36` 起：`\NASInfo`、`%s%s%s`、`AccessToken`（token 写注册表）；`QsyncLib.dll@0x0043523` `.myqnapcloud.com`、`@0x43563` `.myqnapcloud.cn` —— **myQNAPcloud DDNS 主机名 = `<domain_name>` + `.myqnapcloud.com` / `.myqnapcloud.cn`**。

---

## 4. 地址与端口解析（`CCloudHttpPortMapping` / `CCloudHttpvLINKInfo` / `CCloudLinkInfo`）

### 4.1 结构体字段（Qsync.exe 导出访问器）
- `CCloudHttpPortMapping`：`getProtocol`/`getServeicName`（原文如此，拼写为 `Serveic`）/`getSubServeicName`/`getInternalHTTPPort`/`getExternalHTTPPort`/`getInternalHTTPSPort`/`getExternalHTTPSPort`
  → 构造签名 `??0CCloudHttpPortMapping@@QAE@VQString@@00IIII@Z` = `(QString ServiceName, QString SubServiceName, QString Protocol, uint InternalHTTP, uint ExternalHTTP, uint InternalHTTPS, uint ExternalHTTPS)`
  → 对应的响应字段：`service_name`/`serviceName`、`subServiceName`、`proto`/`protocol`、`internalPort`、`externalPort`（`QsyncAPI.dll@0x000e8428`、`@0x000e843c` `WebAdministration`、`@0x000e8450` `TCP`、`@0x000e8464` `Secured`、`@0x000e846c` `internalPort`、`@0x000e847c` `externalPort`；Qsync.exe 侧 `WebAdministration`/`Secured WebAdministration`/`internal_port`/`external_port`/`published`）
- `CCloudHttpvLINKInfo`：`getLANIP`/`getWANIP`/`getGatewayIP`/`getvLINKID`；响应字段 `vlinkId`/`vlinkType`/`vlinkVersion`/`lanIp`/`lanGW`/`wanIp`/`actTime`（`QsyncAPI.dll@0x000e81d8`~`@0x000e8214`）
  - 另在 `QsyncAPI.dll@0x000e889c`：`wan_ip`、`@0x000e88ac` `ddns`、`@0x000e88b8` `lan_ip`、`@0x000e8818` `cloud_link`（`type` 字段的三种取值）
- `CCloudLinkInfo`：`getCloudLinkID`/`setCloudLinkID`；字段 `cloud_link_id`（`QsyncAPI.dll@0x000e8830`）；协议前缀 `http`/`https`（`QsyncAPI.dll@0x000e8840`/`@0x000e884c`）与错误 `[WFM] CQIDGetCloudLinkInfoJson::Parser Unknown protocol type (%s)`(`@0x000e8858`)、`[WFM] CQIDGetCloudLinkInfoJson::Parser Unknown IP type (%s)`(`@0x000e88c8`)

### 4.2 候选连接地址列表的构造与顺序（QsyncLib.dll，核心证据）

`CQsyncConnection::UpdateAddressList` 位于 `QsyncLib.dll` VA `0x100412c0`~`0x10041bf0`。四类候选各自一条日志，且它们的**代码位置顺序就是枚举顺序**：

| 顺序 | 日志原文 | 文件偏移（VA） |
|---|---|---|
| 1 | `CQsyncConnection(%s)::UpdateAddressList GetDeviceInformation(GetWayIP=%s)` | `QsyncLib.dll@0x004134b` (VA `0x1004134b`) |
| 2 | `CQsyncConnection(%s)::UpdateAddressList GetDeviceInformation(LANIP=%s)` | `QsyncLib.dll@0x004153d` (VA `0x1004153d`) |
| 3 | `CQsyncConnection(%s)::UpdateAddressList GetDeviceInformation(MyQNAPCloud=%s)` | `QsyncLib.dll@0x0041666` (VA `0x10041666`) |
| 4 | `CQsyncConnection(%s)::UpdateAddressList GetDeviceInformation(WANIP=%s)` | `QsyncLib.dll@0x0041769` (VA `0x10041769`) |

之后统一收尾：
- `QsyncLib.dll@0x00418fb` (VA `0x100418fb`) `CQsyncConnection(%s)::UpdateAddressList TotalProcessTime(MyQNAPcloud) = %lld ms`
- `QsyncLib.dll@0x0041a6c` (VA `0x10041a6c`) `CQsyncConnection(%s)::UpdateAddressList cancel ping thread num(%d)`
- `QsyncLib.dll@0x0041b61` (VA `0x10041b61`) `CQsyncConnection(%s)::UpdateAddressList StartPingAddress`

**循环结构证据**（`QsyncLib.dll@0x0041479`~`0x00415b4`）：四个 Log 点位于同一循环体内，循环递减计数并在 `0x100414b0` 以 `%d`→`0x10027aea` `Address%d` 之外的方式遍历一个 16 字节元素的列表（`[ebx+0x44a4]`/`[ebx+0x44a8]` 为 vector begin/end，元素步长 `0x10`，`sar eax,4`）。即代码把 `GetDeviceInformation(type)` 对 `type=0..3`（对应上表 1..4）逐轮调用，**首个成功者即被采用**（`test eax,eax / jne` 判定成功），符合"LAN 优先"的语义但**枚举顺序固定为 GatewayIP → LANIP → myQNAPcloud(DDNS) → WANIP**。

### 4.3 端口选择
- 地址串格式：`QsyncLib.dll@0x005566a4`（utf16）`%s%s:%d`、`@0x0040d29` `%s:%d`（VA `0x10040d29`）
- 端口来源即 `CCloudHttpPortMapping`：`InternalHttpPort`/`InternalHttpsPort`/`ExternalHttpPort`/`ExternalHttpsPort` 四个注册表值，写入点日志：
  - `QsyncLib.dll@0x00427834` `CQsyncConnection(%s)::SaveIPListRegistry QSYNC_LINK_NAS_INTERNAL_HTTP_PORT failed(%x)`
  - `@0x427891` `... QSYNC_LINK_NAS_INTERNAL_HTTPS_PORT failed(%x)`
  - `@0x4278ee` `... QSYNC_LINK_NAS_EXTERNAL_HTTP_PORT failed(%x)`
  - `@0x42794b` `... QSYNC_LINK_NAS_EXTERNAL_HTTPS_PORT failed(%x)`
- `Qsync.dll` 导入 `GetConnectPort(handle, QSYNCSYNCDLL_PORTTYPE, bool)`（`QsyncLib.dll` 导出序数 61），说明上层按 `PORTTYPE` 枚举取端口；**枚举取值未在字符串中给出，未确认**。
- 用户可覆盖端口：`QSYNC_LINK_USE_SPECIFY_HTTP_PORT` / `QSYNC_LINK_SPECIFY_LAN_HTTP_PORT` / `QSYNC_LINK_SPECIFY_INTERNET_HTTP_PORT` / `QSYNC_LINK_USE_SPECIFY_HTTPS_PORT` / `QSYNC_LINK_SPECIFY_LAN_HTTPS_PORT` / `QSYNC_LINK_SPECIFY_INTERNET_HTTPS_PORT`（`QsyncLib.dll@0x004187c8`、`@0x418876`、`@0x418916`、`@0x418996`、`@0x418a46`、`@0x418ae6`）+ `QSYNC_LINK_PORT`(`@0x41875b`)。
- 地址列表持久化：`QsyncLib.dll@0x00427a97` `AddressNUM`、`@0x427ab6` `QSYNC_LINK_NAS_ADDRESS_NUM`、`@0x427aea` `Address%d`、`@0x427b06` 格式 `%s,%d,%d`（= 地址串, 类型, 端口），并有 `QSYNC_LINK_DEFAULT_IP_ADDRESS`(`@0x418d1d`)、`QSYNC_LINK_DEFAULT_IP_ADDRESS_TYPE`(`@0x418da7`)、`QSYNC_LINK_IP_ADDRESS`(`@0x419000`)。

### 4.4 测速与排序（`StartPingAddress` / `InitStartPingAddress` / `CheckConnectSpeed`）
- `QsyncLib.dll@0x00556b1c` / `@0x556b24`（utf16）`CQsyncConnection(%s)::InitStartPingAddress` / `StartPingAddress`
- `QsyncLib.dll@0x00403eab7` `CQsyncConnection(%s)::InitStartPingAddress cancel ping thread num(%d)`
- `@0x43edd6` `... InitStartPingAddress(nFinishPing:%d,nIPcount:%d and sleep(100))`
- `@0x43eec8` `... InitStartPingAddress(Re-order :Addr=%s,RTT=%d)` / `@0x43f004` `... (Keep-order :Addr=%s,RTT=%d)`
- `@0x43f5c5` `... StartPingAddress cancel ping thread num(%d)`
- `@0x4401f1` `... StartPingAddress(nFinishPing:%d,nIPcount:%d and sleep(100))`
- `@0x44035a` `... StartPingAddress(Re-order :Addr=%s,RTT=%d)`、`@0x440402` `... (Keep-order :Host Name Addr=%s,RTT=%d)`、`@0x440467` `... (Keep-order :Addr=%s,RTT=%d)`
- `@0x4408d8` `... StartPingAddress TotalProcessTime(MyQNAPcloud) = %lld ms`
- `@0x440c42` `... PingAddressThreadProc WFMValidIP(%s)(%x)(%lld)`
- `@0x3f579` / `@0x408f3` `[LOGINLOG] Ping start` / `[LOGINLOG] Ping end`；`@0x40b38`/`@0x40bc3` `[LOGINLOG] Ping %s:%d start/end`
- 结论：存在 **Keep-order 与 Re-order 两种排序**（`[LOGINLOG]` 与 RTT 记录），测速结果用于把列表按 RTT 重排或保持原序；`CheckConnectSpeed(handle, bool&, bool&, bool*)` 是导出 API（序数 19），用于实时测速，日志 `QsyncLib.dll@0x00441a4` 等。
- `QsyncLib.dll@0x0046191`/`@0x4620d` 附近 `QBackUpdateIPConnectType`（VA `0x106246e2`），把最终 `CONNECT_IP_TYPE` 落盘。

### 4.5 `GetConnectType`（地址 → 连接类型）与 CloudLink 隧道类型
`QsyncLib.dll` 导出序数 62 的 `?GetConnectType@CQsyncSyncDll@@QAE?AWUNSYNCSYNCDLL_CONNECT_IP_TYPE@@PAXPB_W@Z` 落在 VA `0x10046c80`（文件偏移 `QsyncLib.dll@0x0045c80`，按 .text 映射 `VA=IB+0x1000+(off-0x400)` 反推）。反汇编 `QsyncLib.dll@0x0045c80`：
- `mov eax,[esi+0x76d0]`（`m_eCloudLinkTunnelType`），若为 `2`/`1`/`3` 分别 `lea esi,[eax+3]` → 返回 `5`/`4`/`6`；
- 其它值打日志 `QsyncLib.dll@0x0047c9d` `CQsyncConnection(%s)::CQsyncConnection::GetConnectType m_eCloudLinkTunnelType(%d) Unknown type` 并返回 `7`；
- 若隧道类型为 0，则遍历地址列表 `[esi+0x4074]`/`[esi+0x4078]`（16 字节元素，`strcmp` 于 `0x104a7900`）找到匹配地址，返回该元素 `[+4]` 处的类型值；
- 未命中时做 IP 判定：`0x101d27e0` 命中 → 返回 `3`。

结合隧道类型字符串（见 4.6），可读作：`1=P2P`、`2=Relay`、`3=Lan`，映射到返回值 `4/5/6`，`7=Unknown`。
`QBackUpdateIPConnectType` 用于落盘该类型（`QsyncLib.dll@0x0046191` 附近）。

### 4.6 CloudLink / vLink / P2P 中继（Q4 的最后一环）
`CQsyncConnection::OpenQUTKTunnel`（日志区 `QsyncLib.dll@0x0046704`~`@0x46fcf`）：
- `@0x46704` `CQsyncConnection(%s)::OpenQUTKTunnel ServicePort=%d`
- `@0x46726` `[LOGINLOG] QUTK start`、`@0x46789` `Cloudlink_p2p_create_session failed`、`@0x467ac` `m_pQUTKSession existed`、`@0x467d3` `Start to get port mapping`
- `@0x4692b`/`@0x469a5` `[LOGINLOG] QUTK Connect start/end`
- `@0x469d7` `Cloudlink_p2p_connect(-1)`、`@0x46a18` `Cloudlink_p2p_connect failed(result=%d)`、`@0x46a38` `Cloudlink_p2p_connect`
- `@0x46a53`/`@0x46a9b` `[LOGINLOG] QUTK StartProxy start/end`
- `@0x46ac8` `Cloudlink_p2p_start_tunnel failed(result=%d)`、`@0x46af2` `Cloudlink_p2p_start_tunnel`
- `@0x46b61` `m_dwQUTKMappedPort mapped`、`@0x46bf7` `[LOGINLOG] QUTK end(QUTKMappedPort=%d)`、`@0x46c3c` `failed(supportQUTK=%d/%d)`
- 连接类型判定：`@0x46ce7` `[LOGINLOG] Connect Type myQNAPcloud Link v2 - P2P`、`@0x46d17` `... - Relay`、`@0x46d47` `... - Lan`、`@0x46da5` `... - None`；`@0x46d7b` `GetCloudLinkTunnelTypeByQUTKConnType Unknown type(%d)`
- 状态回调：`@0x46e13` `QUTKTunnelStatusCallback(%d)` 与 `new`/`signaling`/`connecting`/`connected`/`disconnected`/`failed`/`auth error`/`unknown state(%d)`（`@0x46e48`~`@0x46f1b`），关闭线程 `@0x46fa8` `QUTKCloseSessionThread start`

**结论**：CloudLink/vLink 中继在 QsyncLib 里是"先试 CloudLink（QUTK=P2P 隧道），再回落普通地址"的结构（`(Try CloudLink first)` / `(Link with CloudLink mode first)` / `(Try CloudLink)` 三处日志）；隧道成功后**本地得到 `127.0.0.1:<QUTKMappedPort>` 代理地址**（`QsyncLib.dll@0x0043e1ca` `push 0x1054e508 '127.0.0.1'` + `@0x43e1d0 push 0x105566a4 '%s%s:%d'`，随后把结果作为地址传给连接封装），所以 CloudLink 模式下所有 NAS 请求都走本机回环。

---

## 5. `QIDAPI*` 系列（QsyncAPI.dll）

### 5.1 参数类型（从 MSVC 修饰名解码）

`?QIDAPIGetAllDeviceInfo@@YAKPB_W0KK0000_NK000PA_NPAI3PAPAPAU_NAS_DEVICE_INFORMATION_API_V11@@@Z`
→ `unsigned long QIDAPIGetAllDeviceInfo(wchar_t const*, wchar_t const*, unsigned long, unsigned long, wchar_t const*, wchar_t const*, wchar_t const*, wchar_t const*, bool, unsigned long, wchar_t const*, wchar_t const*, wchar_t const*, int*, bool*, int*, NAS_DEVICE_INFORMATION_API_V11***)`

统一命名（按位置，`PB_W`=调用方传入的地址/凭据信息，`PA_`=输出，`K`=`unsigned long`，`_N`=`bool`）：
- **入参 1..3**（所有 `QIDAPI*` 都有）：`%ls%ls:%d` 的三个分量 —— 见 `QsyncAPI.dll@0x000ea112` `%ls%ls:%d/oauth/token`、`@0x000e9bcc` `%ls%ls:%d/v1.1/device`。实际拼装点（`QsyncAPI.dll@0x0002b5b8` 一带，`QIDAPIAPPSignOut`）：先用 `cmovne` 在 `http://`(VA `0x100ea2d0`) 与 `https://`(VA `0x100ea27c`) 间二选一、端口在 `0x50`(=80)/`0x1bb`(=443) 间二选一，再 `sprintf(buf,"%ls%ls:%d/oauth/signout", scheme, host, port)`
  → **入参 1（`bool/`窄整型，用 `[ebp-0x2051]` 判定）实际是"是否 HTTPS"的 6 元组之一**，入参 2 是云服务器 host，入参 3 是端口。**注意：修饰名把前 6 个参数全写成 `PB_W`，与上面的 `%ls%ls:%d` 只有 3 个占位符不完全吻合，故"入参 1..6 是 3 组 (scheme,host,port) 候选"属强推断，单组语义已由反汇编证实，多组候选未完全确认。**
- **入参（QID 凭据）**：`client_id` / `client_secret` / `access_token` / `refresh_token`，来源见 QsyncLib 内联常量（`QsyncLib.dll@0x0041eee5`/`@0x41eeea`）与 `com.qnap.qsync.windows.2017`（app id，`QsyncLib.dll@0x0042236`、`@0x44705`）
- **`PA_N`** = `bool*`（成功标志/是否继续翻页）
- **`PAI3`** = `int*`（返回码/计数输出）
- **`PAPAPAU_NAS_DEVICE_INFORMATION_API_V11`** = `NAS_DEVICE_INFORMATION_API_V11**`（设备数组输出）

### 5.2 导出签名一览与对应 URL

| 导出（QsyncAPI.dll） | 解码签名要点 | 调用 URL 模板（UTF-16 常量，附文件偏移） |
|---|---|---|
| `?QIDAPIAPPSignin@@YAKPB_W0000_NK000PA_NPAU_CLOUDSERVER_INFORMATION@@@Z` (序数 5) | `ulong(wchar_t const *×6, bool, ulong, bool*, CLOUDSERVER_INFORMATION*)` | `%ls%ls:%d/oauth/token`(`QsyncAPI.dll@0x000ea112`) / `R%ls%ls:%d/oauth/token`（`R` 为内存前缀噪声） |
| `?QIDAPIAPPRefreshToken@@YAKPB_W00000_NK000PA_NPAU_CLOUDSERVER_INFORMATION@@@Z` (3) | `ulong(wchar_t const *×7, bool, ulong, bool*, CLOUDSERVER_INFORMATION*)` | 同上 `%ls%ls:%d/oauth/token`（body 用 `grant_type=refresh_token`） |
| `?QIDAPIAPPSignOut@@YAKPB_W00000_NK000PA_N@Z` (4) | `ulong(wchar_t const *×7, bool, ulong, bool*)` | `%ls%ls:%d/oauth/signout`(`QsyncAPI.dll@0x000ea648`) |
| `?QIDAPIGetTokenInfo@@YAKPB_W00000_NK000PA_NPAU_CLOUDSERVER_INFORMATION@@@Z` (12) | `ulong(wchar_t const *×7, bool, ulong, bool*, CLOUDSERVER_INFORMATION*)` | `%ls%ls:%d/oauth/tokeninfo?access_token=%ls`(`QsyncAPI.dll@0x000e9f30`) |
| `?QIDAPIGetAllDeviceCount@@YAKPB_W00000_NK000PA_NPAI3@Z` (6) | `ulong(wchar_t const *×7, bool, ulong, bool*, int*)` | `%ls%ls:%d/v1.1/device/count`(`QsyncAPI.dll@0x000eac20`) |
| `?QIDAPIGetAllDeviceInfo@@YAKPB_W0KK0000_NK000PA_NPAI3PAPAPAU_NAS_DEVICE_INFORMATION_API_V11@@@Z` (7) | `ulong(wchar_t const *×2, ulong, ulong, wchar_t const *×4, bool, ulong, wchar_t const *×3, int*, bool*, int*, NAS_DEVICE_INFORMATION_API_V11***)` | `%ls%ls:%d/v1.1/device`(`QsyncAPI.dll@0x000eadcc`) |
| `?QIDAPIGetDeviceInfoByName@@YAKPB_W000000_NK000PA_NPAI3PAPAPAU_NAS_DEVICE_INFORMATION_API_V11@@@Z` (10) | 同上多一个 `wchar_t const*`（设备名） | `R%ls%ls:%d/v1.1/device/search?device_name=%ls`(`QsyncAPI.dll@0x000ea96e`) |
| `?QIDAPIGetDeviceID@@YAKPB_W00000_NK000PA_NPAU_NAS_DEVICE_INFORMATION@@@Z` (9) | `ulong(wchar_t const *×7, bool, ulong, bool*, NAS_DEVICE_INFORMATION*)` | `R%ls%ls:%d/v1/users/deviceId/%ls`(`QsyncAPI.dll@0x000eafce`) —— **该模板无代码引用，未确认** |
| `?QIDAPIGetCloudLinkSetting@@YAKPB_W000000_NK000PA_NPAU_CLOUD_LINK_INFORMATION@@@Z` (8) | `ulong(wchar_t const *×8, bool, ulong, bool*, CLOUD_LINK_INFORMATION*)` | 无独立模板；走 `%ls%ls:%d/v1.1/device/%ls/network`(`QsyncAPI.dll@0x000ea716`) 与 vlink（见下），**未完全确认** |
| `?QIDAPIGetPublicIP@@YAKPB_W00000_NK000PA_NPAU_LOCAL_DEVICE_INFORMATION@@@Z` (11) | `ulong(wchar_t const *×7, bool, ulong, bool*, LOCAL_DEVICE_INFORMATION*)` | `%ls%ls:%d/v1.1/utility/geo/search`(`QsyncAPI.dll@0x000eb688`)；反汇编确认（`QsyncAPI.dll@0x0003017e`） |
| `?QIDFreeCloudInfo@@YAXPAU_CLOUD_LINK_INFORMATION@@@Z` (13) | 释放 | — |
| `?QIDFreeDeviceInfo@@YAXIPAPAPAU_NAS_DEVICE_INFORMATION_API_V11@@@Z` (14) | `void(uint, NAS_DEVICE_INFORMATION_API_V11***)` 释放 | — |

`QIDAPIGetPublicIP` 的字符串解析点：`QsyncAPI.dll@0x0011_0000`… 附近日志 `QsyncAPI.dll@0x000e8xxx`（utf16/ascii 混合）`CQIDGetCloudInfoJson CQIDAPIGetPublicIPJson failed(%d)`、`... data is null`（`QsyncLib` 侧同名日志见 `QsyncLib.dll@0x0045808` 邻域）。

### 5.3 认证头（QsyncAPI.dll 侧）
`X-QNAP-TIME`、`X-QNAP-APP-ID`、`X-QNAP-APP-VER`、`X-QNAP-CHECK`、`X-QNAP-SUBAPP-ID`（`QsyncAPI.dll@0x000e9110` 一带），错误串：`X-QNAP-TIME is invalid.`、`The checksum X-QNAP-CHECK is invalid.`、`The app id is not found.`、`The vlink configuration is not found.`、`Get device name failed.`、`The device is not found.`、`The device status is not found.`、`Get device failed.`（`QsyncAPI.dll@0x000e82xxx`~`@0x000e8400`）、`Bearer `(`QsyncAPI.dll@0x000ea79c`)。
返回码字段：`StatusCode`、`message`（`QsyncAPI.dll@0x000e81c4`/`@0x000e81d0`）。

---

## 6. `MCNAPIGetVLinkInfo` / `MCNAPIGetServicePorts` 与 `cloudlinkP2P.dll`

### 6.1 签名与 URL
| 导出 | 签名要点 | URL |
|---|---|---|
| `?MCNAPIGetVLinkInfo@@YAKPB_W00000_NK000PA_NPAU_NAS_DEVICE_INFORMATION@@@Z` (序数 2) | `ulong(wchar_t const *×7, bool, ulong, bool*, NAS_DEVICE_INFORMATION*)` | `%ls%ls:%d/v1/services/vlink/%ls`(`QsyncAPI.dll@0x000ea290`，`vlinkId` 作为末参) |
| `?MCNAPIGetServicePorts@@YAKPB_W00000_NK000PA_NPAU_NAS_DEVICE_INFORMATION@@@Z` (序数 1) | 同上 | `%ls%ls:%d/v1/devices/services/portMapping/%ls`(`QsyncAPI.dll@0x000ea4e0`) |

两者都返回 `NAS_DEVICE_INFORMATION`；`vlink` 响应字段 `vlinkId`/`vlinkType`/`vlinkVersion`/`lanIp`/`lanGW`/`wanIp`/`actTime`（`QsyncAPI.dll@0x000e81d8`~`@0x000e8214`）；`portMapping` 响应字段 `serviceName`/`proto`/`subServiceName`/`internalPort`/`externalPort`（`QsyncAPI.dll@0x000e8428`~`@0x000e847c`），对应 `CCloudHttpPortMapping`。
`QsyncLib` 调用点：`QsyncLib.dll@0x00461b4` `(Get MCNAPIGetVLinkInfo failure, TotalQueryQCloudCount = %d, dwAPIResult = %d)`；重试计数 `TotalQueryQCloudCount`。

### 6.2 `cloudlinkP2P.dll` 的角色
- 该 DLL 是大体量（~13 MB）的 Go 编译产物（含大量 `cobra_annotation_*`、`__%s_handle_filename_extension_flag`、`cgo`/`lws` 痕迹），暴露 QUTK 会话 API：`Cloudlink_p2p_create_session`、`Cloudlink_p2p_connect`、`Cloudlink_p2p_start_tunnel`、`Cloudlink_p2p_close`、`Cloudlink_p2p_get_cloud_info`（调用方字符串全部在 `QsyncLib.dll`，见 4.6）。
- 内含 alpha/dev 云域名（原始字符串，含相邻串粘连，说明是 Go 字符串常量表拼接）：
  - `cloudlinkP2P.dll@...` `https://core2.api.dev.myqnapcloud.cn`（与 `__%s_handle_filename_extension_flag` 粘连）
  - `cloudlinkP2P.dll` `https://core2.dev.myqnapcloud.iohttps://core2.api.myqnapcloud.cn`（两个域名粘连）+ `%w:`
  - `cloudlinkP2P.dll` `https://edge.api.dev.myqnapcloud.cn__%[1]s_handle_go_custom_completioncobra_annotation_mutually_exclusivenetwork`
  - `cloudlinkP2P.dll` `https://edge.dev.myqnapcloud.iohttps://edge.api.myqnapcloud.cnfailed`
- **结论**：`cloudlinkP2P.dll` 是 myQNAPcloud Link v2（QUTK）的 P2P/中继客户端实现，负责与 `core2`/`edge` 云（含 dev/alpha 变体）建会话与打洞/中继；QsyncLib 只把它当作"打开本地端口映射 → 拿到 `127.0.0.1:<mappedPort>`"的黑盒（见 4.6）。P2P 协议细节未深挖。

---

## 7. 区域选择逻辑（`.com` / `.cn` / alpha / dev）

### 7.1 `Qsync.exe` 的两级（实为三级）选择

`CCloudHttpService_V2` 提供：
- `Qsync.exe` 导出 `?setRegion@CCloudHttpService_V2@@SAX_N@Z`（序数 142，`static void setRegion(bool)`）与 `?isAlphaAPI@CCloudHttpService_V2@@QAE_NXZ`（序数 102）
- 实现（VA `0x5fb460`，文件偏移 `0x1fa860`）只有两条指令：
  `mov al,[ebp+8]` / `mov [0xbcfe1c],al` → 即 **`setRegion(bool)` 就是在写全局字节 `0xbcfe1c`**；`isAlphaAPI` = `mov al,[ecx+0x10]; ret`（读对象成员 `+0x10`，该成员由 `setRegion` 的值注入）。

三级选择的实际代码（`Qsync.exe`，每处都是 `cmp [obj+0xb8],0` + `cmp [0xbcfe1c],0` 双层 `cmove`）：

**(a) 账号站**（文件偏移 `0x1ff9c0` 一带，VA `0x6005xx`）：
```
0x006005b7  cmp byte ptr [ebx+0xb8],0
0x006005c2  je  0x6005d0
0x006005c4  mov eax,0xb483b8     ; 'alpha-account.qnap.com'
0x006005c9  mov ecx,0xb483d0     ; 'alpha-account.qnap.com.cn'
0x006005ce  jmp 0x6005da
0x006005d0  mov eax,0xb483ec     ; 'account.qnap.com'
0x006005d5  mov ecx,0xb48400     ; 'account.qnap.com.cn'
0x006005da  cmp byte ptr [0xbcfe1c],0
0x006005e1  cmove eax,ecx        ; [0xbcfe1c]==0 -> 取 ecx(中国)，否则 eax(国际)
```
→ **账号站域名 = f(是否中国区 `[obj+0xb8]`, alpha 标志 `[0xbcfe1c]`)**：
`[0xbcfe1c]!=0` 走 alpha 站；`[obj+0xb8]!=0` → `.cn`，否则 `.com`。

**(b) QID API 域名**（文件偏移 `0x1fff90` 一带，VA `0x600bxx`）：
```
0x00600baf  cmp byte ptr [eax+0xb8],0
0x00600bbe  ...
0x00600bb8  mov eax,0xb48450     ; 'core.api.alpha-myqnapcloud.com'
0x00600bbd  mov ecx,0xb48470     ; 'core.api.alpha-myqnapcloud.cn'
0x00600bc4  mov eax,0xb48490     ; 'core.api.myqnapcloud.com'
0x00600bc9  mov ecx,0xb484ac     ; 'core.api.myqnapcloud.cn'
0x00600bce  cmp byte ptr [0xbcfe1c],0
0x00600bd5  cmove eax,ecx
0x00600bdc  call  [0x6dc218]     ; QString::operator=
0x00600be2  push 8 / push 'https://'(@0x6e5a94)
0x00600bf0  push 0x13 / push 0xb484f0   ; '%1%2:%3/v1.1/device'
```
→ **QID API 域名 = `https://` + (alpha ? `core.api.alpha-myqnapcloud.{com|cn}` : `core.api.myqnapcloud.{com|cn}`) + `:port` + `/v1.1/device`**，`obj+0xb8` 选 `.cn`/`.com`，`[0xbcfe1c]` 选 alpha/生产。

**(c) `core2` 域名族（`CCloudHttpService_V1/V2` 设备发现，文件偏移 `0x1ff9c0` 前的 `0x1f89xx`/`0x1f8fxx`/`0x1f9xxx`/`0x1fafxx`/`0x1ffxxx`/`0x2009xx`/`0x2016xx`/`0x201exx` 组）**：
`Qsync.exe@0x2f0f4c` `https://core2.api.alpha-myqnapcloud.com/`、`@0x2f0f78` `https://core2.myqnapcloud.io/`、`@0x2f0f98` `https://core2.api.alpha-myqnapcloud.cn/`、`@0x2f0fc0` `https://core2.api.myqnapcloud.cn/`。
代码引用点（`va` 立即数，均为成对 `cmove`）：`0x6f1d4c` → refs `0x7bff7,0x7c497,0x7c9e7`；`0x6f1d78` → `0x7bff2,0x7c492,0x7c9e2`；`0x6f1d98` → `0x7c044,0x7c4e4,0x7ca34`；`0x6f1dc0` → `0x7c03f,0x7c4df,0x7ca2f`。
成对顺序 `(alpha-.com, .io)` 与 `(alpha-.cn, .cn)` 说明同一 `cmove` 里 **`[0xbcfe1c]` 选 alpha，`[obj+0xb8]` 选 `.com`/`.cn`（国际族含 `.io`）**。

### 7.2 `QSystemLib.dll` 的完整区域常量表与 3 组 cmove
`QSystemLib.dll`（ImageBase `0x10000000`，32 位）中 16 个域名常量的 VA 与代码引用点（`cmove` 对）：

| 域名 | 文件偏移 | VA | 代码引用点（文件偏移） |
|---|---|---|---|
| `alpha-account.qnap.com/` | `0x2ac08` | `0x1002b808` | `0x6b9e` |
| `account.qnap.com/` | `0x2ac28` | `0x1002b828` | `0x6b99` |
| `alpha-account.qnap.com.cn/` | `0x2ac44` | `0x1002b844` | `0x6bdc` |
| `account.qnap.com.cn/` | `0x2ac68` | `0x1002b868` | `0x6bd7` |
| `auth.alpha.myqnapcloud.io/` | `0x2adac` | `0x1002b9ac` | `0x7ea3,0x84fa,0x8a81,0x8edc,0x955a,0xa1b1,0xbf10` |
| `auth.myqnapcloud.io/` | `0x2add0` | `0x1002b9d0` | `0x7e9e,0x84f5,0x8a7c,0x8ee1,0x9555,0xa1ac,0xbf0b` |
| `auth.api.alpha.myqnapcloud.cn/` | `0x2adf0` | `0x1002b9f0` | `0x853c,0x8ac7,0x8f27,0x95a4,0xa1f7` |
| `auth.api.myqnapcloud.cn/` | `0x2ae18` | `0x1002ba18` | `0x8537,0x8ac2,0x8f22,0x959f,0xa1f2` |
| `core2.alpha.myqnapcloud.io/` | `0x2aef0` | `0x1002baf0` | `0x99e7,0xa6f7,0xa9f7,0xae17,0xb1e7,0xb6a7` |
| `core2.myqnapcloud.io/` | `0x2af14` | `0x1002bb14` | `0x99e2,0xa6f2,0xa9f2,0xae12,0xb1e2,0xb6a2` |
| `core2.api.alpha.myqnapcloud.cn/` | `0x2af34` | `0x1002bb34` | `0x7edd,0x9a33,0xa743,0xaa43,0xae63,0xb233,0xb6f3,0xbf56` |
| `core2.api.myqnapcloud.cn/` | `0x2af5c` | `0x1002bb5c` | `0x7ed8,0x9a2e,0xa73e,0xaa3e,0xae5e,0xb22e,0xb6ee,0xbf51` |
| `edge.alpha.myqnapcloud.io/` | `0x2b048` | `0x1002bc48` | `0x9cf9` |
| `edge.myqnapcloud.io/` | `0x2b06c` | `0x1002bc6c` | `0x9cfe` |
| `edge.api.alpha.myqnapcloud.cn/` | `0x2b08c` | `0x1002bc8c` | `0x9d44` |
| `edge.api.myqnapcloud.cn/` | `0x2b0b4` | `0x1002bcb4` | `0x9d3f` |

**判定代码**（`QSystemLib.dll@0x0007f7f`~`0x0007f00` 与 `@0x0009070`~`0x0009147`，即 `QcQcloudAPIHelper` 构造/初始化）：

```
; --- 账号站，比较对象：[ebp+0x18]（第 1 个 bool 入参）
QSystemLib.dll@0x0007798  mov eax,0x1002b828        ; account.qnap.com/
QSystemLib.dll@0x000779d  mov edx,0x1002b808        ; alpha-account.qnap.com/
QSystemLib.dll@0x00077a9  cmove edx,eax             ; [ebp+0x18]==0 -> 生产
...
QSystemLib.dll@0x00077d2  cmp byte ptr [ebp+0x18],0
QSystemLib.dll@0x00077d6  mov ecx,0x1002b868        ; account.qnap.com.cn/
QSystemLib.dll@0x00077db  mov eax,0x1002b844        ; alpha-account.qnap.com.cn/
QSystemLib.dll@0x00077e0  cmove eax,ecx
QSystemLib.dll@0x00077e7  call QString::operator+=  ; 仅当 [ebp+0x1c]==0 时追加 .cn 站

; --- auth / QID API，比较对象：对象成员 +0x88 与 +0x89
QSystemLib.dll@0x0008a9d  mov eax,0x1002b9d0        ; auth.myqnapcloud.io/
QSystemLib.dll@0x0008aa2  mov edx,0x1002b9ac        ; auth.alpha.myqnapcloud.io/
QSystemLib.dll@0x0008aa7  cmove edx,eax             ; [esi+0x88]==0 -> 生产
QSystemLib.dll@0x0008ac3  cmp byte ptr [esi+0x89],0
QSystemLib.dll@0x0008ace  jne 0x10008aee           ; +0x89!=0 -> 不做追加
QSystemLib.dll@0x0008ad7  mov ecx,0x1002bb5c        ; core2.api.myqnapcloud.cn/
QSystemLib.dll@0x0008adc  mov eax,0x1002bb34        ; core2.api.alpha.myqnapcloud.cn/
QSystemLib.dll@0x0008ae1  cmove eax,ecx
QSystemLib.dll@0x0008ae8  call QString::operator+=
QSystemLib.dll@0x0008af6  push 0xd / push 0x1002bbf0 ; "client_credentials"

; --- auth（另一路，比较对象：+0x88/+0x89）
QSystemLib.dll@0x00090ed  cmp byte ptr [edi+0x88],0
QSystemLib.dll@0x00090f4  mov eax,0x1002b9d0
QSystemLib.dll@0x00090f9  mov edx,0x1002b9ac
QSystemLib.dll@0x00090fe  cmove edx,eax
QSystemLib.dll@0x0009136  mov ecx,0x1002ba18        ; auth.api.myqnapcloud.cn/
QSystemLib.dll@0x000913b  mov eax,0x1002b9f0        ; auth.api.alpha.myqnapcloud.cn/
QSystemLib.dll@0x0009140  cmove eax,ecx
```

**解读（`QSystemLib.dll`）**：
- `+0x88` = 国际/中国（`0`→国际 `.io` 族，`非0`→中国 `.cn` 族）；
- `+0x89` = "是否带 `api` 子域/alpha 可用"开关：`+0x89 != 0` 时直接使用 `.io` 生产域名，**不追加**中国 `api` 变体；
- 账号站另有独立 bool 入参 `[ebp+0x18]`（alpha）与 `[ebp+0x1c]`（是否追加 `.cn` 站）。
- `QSystemLib.dll@0x0008840` 的"国内/国外 + 端口"分支同 `Qsync.exe`：`https://`(`@0x1002b...`) vs `http://`，端口 `0x50`/`0x1bb`。

### 7.3 Qsync.exe 的 `alpha` 开关来源
`[0xbcfe1c]` 的 6 个写入/读取点（全文件唯一写点在 `Qsync.exe@0x001fa867` = `setRegion` 的 `mov [0xbcfe1c],al` 处）：
`refs = [0x1fa867(写, setRegion), 0x1ff9dc, 0x1fffd0, 0x200a46, 0x2016ea, 0x201f16(均为 cmove 读)]`。
其余读点分别位于：账号站选择(`0x1ff9dc`)、QID API 域名选择(`0x1fffd0`)、设备/记录族(`0x200a46`、`0x2016ea`)、登出族(`0x201f16`)。
**调用 `setRegion` 的上层（UI 或启动时区域判定）未定位到直接调用点（`setRegion` 只被导出/间接调用），"由谁调用、依据什么（`RegionSettingDlg` `slotRegionChanged` 或系统区域）设置"未确认。** 相关 UI 线索：`Qsync.exe` 字符串 `.?AVRegionSettingDlg@@`（`str_Qsync.exe.txt` 第 4854 行）、`1slotRegionChanged()`（第 7314 行）、`Region`/`RegionSettingDlg`（第 30840/30841 行）、`Select your region.`（第 31324 行）、`[slotRegionChanged]`（第 34628 行）、`In compliance with regional Internet service regulations, QNAP configures service according to your region...`（第 27714 行）。

### 7.4 dev 变体
`.dev.` 域名只在 `cloudlinkP2P.dll` 中出现（`https://core2.api.dev.myqnapcloud.cn`、`https://core2.dev.myqnapcloud.io`、`https://edge.api.dev.myqnapcloud.cn`、`https://edge.dev.myqnapcloud.io`，`cloudlinkP2P.dll@0x...`，见第 6.2 节）；`Qsync.exe` / `QsyncLib.dll` / `QsyncAPI.dll` / `QSystemLib.dll` 中**未发现** `.dev.` 变体。

---

## 8. 端到端时序小结（含出处）

```
[启动] Qsync.exe CCloudHttpService_V2::setRegion(bool alpha)   -> 写 Qsync.exe@0x001fa867 的全局 0xbcfe1c
       域名三选一：账号站 / core2 / core.api（第 7 问）

[登录] 若走 QID 浏览器授权：
   1. 起本地回调 http://127.0.0.1:{4300|4343|14300|14343}/oauth2/callback
        Qsync.exe@0x2f12a4 / @0x2f12b8 / @0x0047f268 / @0x0047f30f / @0x2f1408
   2. GET {account}/oauth/auth?response_type=code&client_id=593a...&redirect_uri=...&code_challenge_method=S256&code_challenge=...
        Qsync.exe@0x2f12cc / @0x2f12f8 / @0x2f1314 / @0x2f1328 / @0x004803c1..@0x480408
   3. 回调收 code   Qsync.exe@0x0047f48f ('code')
   4. POST {account}/oauth/token  body=grant_type=authorization_code&client_id=593a...&client_secret=g9Ls...&code=..&code_verifier=..&redirect_uri=..
        Qsync.exe@0x2f14b8 / @0x0047f5fc / @0x0047f608 / @0x0047f656
   5. GET {account}/oauth/tokeninfo?access_token=..   -> user/email/id/display_name
        Qsync.exe@0x2f135c / @0x2f0de0..@0x2f0df0
   6. 刷新: POST /oauth/token body=grant_type=refresh_token&...   Qsync.exe@0x00747570
      登出: POST {account}/oauth/signout                          Qsync.exe@0x00747638

[设备发现]
   7. GET {core2|core.api}/api/v1.1/device           -> device_id/device_name/host_name/lan_ips/wan_ips/domain_name/local_services{internal_port,external_port,published}
        Qsync.exe@0x007476f0 / %ls%ls:%d/v1.1/device (QsyncAPI.dll@0x000eadcc)
   8. GET .../v1.1/device/search?device_name=..      Qsync.exe@0x007476c4 / QsyncAPI.dll@0x000ea96e
   9. GET .../v1.1/device/count                      QsyncAPI.dll@0x000eac20
  10. GET .../v1.1/utility/geo/search  (public_ip)   QsyncAPI.dll@0x000eb688
  11. GET .../v1/services/vlink/{vlinkId}            QsyncAPI.dll@0x000ea290
  12. GET .../v1/devices/services/portMapping/{id}   QsyncAPI.dll@0x000ea4e0
  13. GET .../v1.1/device/{id}/network               QsyncAPI.dll@0x000ea716

[连接]
  14. CQsyncConnection::UpdateAddressList 按 GatewayIP -> LANIP -> myQNAPcloud(DDNS) -> WANIP 逐类求值
        QsyncLib.dll@0x004134b / @0x004153d / @0x0041666 / @0x0041769
      DDNS 主机名 = domain_name + '.myqnapcloud.com'/'.myqnapcloud.cn'   QsyncLib.dll@0x0043523 / @0x0043563
  15. GetConnectType 判定地址类型（P2P=4 / Relay=5 / Lan=6 / 其它=7）  QsyncLib.dll@0x0045c80
  16. 若走 CloudLink：OpenQUTKTunnel -> cloudlinkP2P.dll -> 本地 127.0.0.1:QUTKMappedPort
        QsyncLib.dll@0x0046704..@0x0046fcf / @0x0043e1ca / @0x0043e1d0
        （连接类型日志 P2P/Relay/Lan/None: QsyncLib.dll@0x0046ce7 / @0x0046d17 / @0x0046d47 / @0x0046da5）
  17. StartPingAddress 按 RTT Keep-order/Re-order 择优  QsyncLib.dll@0x0044035a / @0x00440402 / @0x00440467
  18. QBackUpdateIPConnectType 落盘连接类型  QsyncLib.dll@0x106246e2 邻域
```

---

## 9. 明确"未确认"项

1. `Qsync.exe` 全文件**没有**裸 ASCII `POST` 字符串（`re.search(rb'POST')` 无命中）；`GET` 只在 Qt 内部命中（`Qsync.exe@0x00413f26`、`@0x00418e8c`）。Qt 走 `QNetworkAccessManager::post/get`（`Qsync.exe` 导入 `Qt5Network.dll`），因此"登录/token 换取是 POST、tokeninfo/设备列表是 GET"是从代码结构（`Content-Type: application/x-www-form-urlencoded` 表单 body + URL 查询串 `?access_token=%1`）推断，**非字面证据**。
2. `QIDAPI*` 前 6 个 `PB_W` 入参是否真的构成 3 组 (scheme, host, port) 候选，只证实了单组 `%ls%ls:%d` 的三分量语义；多组候选未完全确认。
3. `QIDAPIGetDeviceID` 的 `%ls%ls:%d/v1/users/deviceId/%ls`、`QIDAPIGetCloudLinkSetting` 的具体 endpoint 未在代码中定位到引用。
4. `QSYNCSYNCDLL_PORTTYPE` / `QSYNCSYNCDLL_CONNECT_IP_TYPE` 的枚举名与数值未在字符串中直接给出（仅由日志与返回常量推断：CloudLink 隧道 1/2/3 → 4/5/6，未知 → 7）。
5. `setRegion`（全局 `0xbcfe1c`）的上层调用者与判定依据（UI `RegionSettingDlg` vs 系统区域）未定位。
6. 7 段 16 进制 UUID（`Qsync.exe@0x0074728c` 等）与 DCS 问卷字段的精确对应关系只到"成对出现在 `deviceVagueUID`/`uuid`/`questionnaire_uuid` 附近"的程度。
7. 用户提到的 `https://core2.api.myqnapcloud.cn/` 等 URL 在 `Qsync.exe` 里以**带尾斜杠的完整基址**存在（`Qsync.exe@0x2f0fc0`），不在 `%1%2:%3/...` 模板体系内；两套字符串（`core2.../` 基址族 与 `core.api...` + `%1%2:%3/...` 模板族）分别对应 `CCloudHttpService_V1/V2`（`getDeviceInfo` 等）与 `QCloudHttp`/`CDCSCloudHttpService`/`QsyncAPI` 两批调用方，精确的调用方归属需逐函数核对（本报告已给出主要归属，未逐一穷举）。
