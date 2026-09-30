# 免责声明 / Disclaimer

[中文](#中文) · [English](#english)

---

## 中文

### 1. 性质：非官方、无关联、无利益

本项目是一份**个人兴趣爱好驱动的技术学习与逆向分析笔记**。

- 与 **QNAP Systems, Inc.（威联通科技股份有限公司）** 及其关联公司**没有任何关系**：
  未获其授权、未受其委托、未与其合作、未受其资助。
- **无任何商业目的、无任何经济利益**：不销售、不含广告、不提供付费服务、不接收与本项目相关的赞助或报酬。
- 本项目**不是** QNAP 官方文档，也不代表 QNAP 的任何立场或观点。

### 2. 目的：为了在 Linux 上自用

分析动机单一且已公开说明：作者在 Linux 上使用 QNAP NAS，希望有一个支持「按需同步（on-demand）」
的第三方客户端，因此需要先弄清现有 Windows 客户端的行为与接口。
本项目是该准备工作的一部分，**结果供作者自用及技术同好参考**。

### 3. 分析边界：只做静态阅读，未触碰任何保护措施

本分析**仅使用公开可得的静态分析手段**（PE 结构解析、导入/导出表读取、字符串提取、x86 反汇编交叉引用）。

明确声明**未做**以下事情：

- ❌ 未运行该客户端程序（未执行 `Qsync.exe` / `QsyncSvc.exe` / `QsyncExt.dll` 等）
- ❌ 未进行任何网络抓包、代理拦截或流量解密
- ❌ 未连接、未登录任何真实 NAS，未接触任何服务器或他人数据
- ❌ 未绕过、未破解、未禁用任何技术保护措施（无许可证校验破解、无 DRM 规避、无签名伪造）
- ❌ 未修改、未重新打包、未重新分发 QNAP 的任何二进制文件
- ❌ 未获取、未使用任何他人的账号、凭据或私密数据

所使用的目标程序副本来自作者**自行安装**的软件包，仅用于本地阅读。

### 4. 知识产权归属

- **QNAP**、**Qsync**、**myQNAPcloud**、**QID** 等名称与标识是 QNAP Systems, Inc. 的商标或注册商标。
- 被分析软件的**全部著作权、商标权及其他一切权利，均归 QNAP Systems, Inc. 及其许可方所有**。
- 本项目**不主张**对被分析软件的任何权利，也**不授予**任何人对该软件的任何许可。
- 本项目中属于作者原创的部分（分析文字、图表、脚本）不代表对上述权利的放弃或让渡。
- 本仓库**不分发** QNAP 的二进制文件、安装包、反编译产物或大段原始字符串转储。
  仓库内的接口信息为**事实性技术信息**（URL 路径、参数名、函数名等），用于说明互操作性。

### 5. 凭据处理

报告中若涉及分析目标内含的客户端标识（如 OAuth `client_id`），**公开版本已做掩码处理**，
并提供脚本供你从**你自己合法获得的副本**中提取，以避免在公开渠道散布第三方凭据。

### 6. 无担保

本项目内容按「**现状**」提供，**不提供任何形式的明示或默示担保**，包括但不限于
准确性、完整性、适销性、特定用途适用性与不侵权担保。
逆向分析结论可能存在错误、随版本变化而失效，或存在理解偏差。
**任何人依据本项目内容所作的任何决定与行为的风险，由其自行承担。**

### 7. 使用者的责任

- 请**仅对你拥有所有权或已获明确授权管理的设备与软件**使用本项目内容。
- 使用本项目内容时，请**遵守当地法律法规**、**QNAP 的服务条款与许可协议**，
  以及你所处司法辖区关于逆向工程、互操作性、计算机软件保护的相关规定。
- **请勿**将本项目内容用于未授权访问、绕过授权、批量侵权或其他违法用途。
- 各方对逆向工程的合法边界规定不同，**在依据本项目开发或分发任何软件之前，请自行咨询专业法律意见**。

### 8. 侵权处理：通知即删

作者**无意侵犯任何人的合法权利**。若你认为本项目内容侵犯了你的权利，请通过
GitHub Issue 或仓库中提供的联系方式告知，并说明具体内容与权利依据。

**收到有效通知后，作者将立即删除相关内容或整个仓库，不寻求任何形式的法律对抗。**
本项目纯属兴趣学习，没有任何需要捍卫的经济利益。

---

## English

### 1. Nature: Unofficial, Unaffiliated, Non-commercial

This project is a **personal, hobby-driven set of technical notes on reverse engineering**.

- It is **not affiliated with, authorized by, sponsored by, endorsed by, or connected to
  QNAP Systems, Inc.** in any way.
- It has **no commercial purpose and no financial interest**: nothing is sold, there is no
  advertising, no paid service, and no sponsorship or compensation of any kind is received.
- This is **not** official QNAP documentation and does not represent QNAP's positions.

### 2. Purpose: personal use on Linux

The motivation is narrow and disclosed: the author uses a QNAP NAS from Linux and wants a
third-party client with **on-demand sync**. Understanding the existing Windows client's
behaviour and interfaces is a prerequisite. This project is part of that preparation.

### 3. Scope: static reading only; no protection measures touched

Only **publicly available static analysis techniques** were used (PE structure parsing,
import/export table reading, string extraction, x86 disassembly cross-referencing).

Explicitly **NOT** done:

- ❌ The client was never executed
- ❌ No packet capture, proxy interception, or traffic decryption
- ❌ No real NAS was contacted or logged into; no server or third-party data was touched
- ❌ No technical protection measure was circumvented, cracked, or disabled
      (no license-check bypass, no DRM circumvention, no signature forgery)
- ❌ No QNAP binary was modified, repackaged, or redistributed
- ❌ No third-party credentials or private data were obtained or used

The analysed copy came from software the author installed themselves, read locally.

### 4. Intellectual property

- **QNAP**, **Qsync**, **myQNAPcloud**, and **QID** are trademarks or registered trademarks of
  QNAP Systems, Inc.
- **All copyright, trademark, and other rights in the analysed software belong to
  QNAP Systems, Inc. and its licensors.**
- This project claims **no rights** in that software and grants **no licence** to it.
- Original portions of this project (written analysis, diagrams, scripts) do not waive or
  transfer any of the above rights.
- This repository **does not distribute** QNAP binaries, installers, decompilation output, or
  bulk raw string dumps. Interface information presented here is **factual technical
  information** (URL paths, parameter names, symbol names) provided to describe interoperability.

### 5. Credentials

Where the analysis touches a client identifier embedded in the target (e.g. an OAuth `client_id`),
the **public version is masked**, with a script provided so you can extract it from a copy you
legitimately obtained — avoiding the public dissemination of third-party credentials.

### 6. No warranty

Provided **"AS IS"**, **without warranty of any kind**, express or implied, including but not
limited to accuracy, completeness, merchantability, fitness for a particular purpose, and
non-infringement. Reverse-engineering findings may be wrong, may become obsolete with new
versions, or may reflect misunderstanding. **You bear all risk for any decision or action taken
based on this project.**

### 7. Your responsibility

- Use this material **only for devices and software you own or are explicitly authorized to administer**.
- Comply with **applicable law**, **QNAP's terms of service and licence agreements**, and the rules
  on reverse engineering, interoperability, and software protection in your jurisdiction.
- **Do not** use this material for unauthorized access, circumvention of authorization, mass
  infringement, or any other unlawful purpose.
- The legal boundaries of reverse engineering differ by jurisdiction. **Consult a qualified lawyer
  before developing or distributing any software based on this project.**

### 8. Takedown on notice

The author **has no intention of infringing anyone's rights**. If you believe this project
infringes your rights, please open a GitHub Issue or use the contact information in the repository,
identifying the specific content and the basis of your claim.

**Upon a valid notice, the author will remove the relevant content — or the entire repository —
promptly, and will not mount any legal defence.** This is a hobby project; there is no economic
interest worth defending.

---

*Last updated: 2026-09-30*
