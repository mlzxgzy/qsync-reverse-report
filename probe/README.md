# probe/ —— 协议动态验证工具

`qs_probe.py` 用来对**你自己的** QNAP NAS 复现本报告还原出的 API，把原始响应落盘。
它的存在是为了解决**静态分析无法确定的参数**（见 08 篇 8.7 验证计划）。

⚠️ 仅用于你拥有或获授权管理的设备。

## 为什么需要它

以下问题只有真实请求才能回答，二进制里查不到：

| 问题 | 脚本怎么帮你 |
|---|---|
| `authLogin.cgi` 的密码字段到底叫什么（`pwd`? `pass`? `auth_pass`? 还是 AES 封装） | `login` 会依次尝试 4 个候选字段并报告哪个通过 |
| 响应是 XML 还是 JSON、字段名与嵌套 | 原始响应全文落盘 |
| `qbox_get_max_log` 返回结构 | `probe` 直接打印 |
| `qbox_get_sync_log` 的事件格式与 `number` 批量 | `probe` 会带 `get_detail=1&sub_folder=/` 调一次 |
| 地址候选集字段（DDNS / WAN / LAN / 端口） | `probe` 调 `get_domain_ip_list` |
| 版本化能力 | `probe` 调 `versioning_probe` |
| `%ls` URL 前缀到底填什么 | `--prefix` 参数，直连留空 |

## 用法

```bash
# 1) 只验证登录（会打印 authLogin 的原始响应，并试出正确密码字段名）
python3 qs_probe.py --host 192.168.1.10 --port 8080 --user admin --password 'xxx' login

# 2) HTTPS + 自签证书
python3 qs_probe.py --host nas.example.com --port 443 --https --insecure \
                   --user admin --password 'xxx' login

# 3) 登录 + 批量调用只读端点
python3 qs_probe.py --host 192.168.1.10 --user admin --password 'xxx' probe

# 4) 自定义查询（需要已有 sid）
python3 qs_probe.py --host 192.168.1.10 raw 'func=qbox_get_qbox_info&sid=XXXX'
```

输出：stdout 同时写入 `probe-out/<时间戳>/*.http`（含完整响应头与正文）。

## 建议的验证顺序

1. **登录**：`login`。若 4 个密码字段都失败，看响应里的 `error_code` / `need_2sv`：
   - `need_2sv=1` → 你的账号开了二步验证，用 `--param` 传 `code` / `security_answer` 等
   - `error_code` 指向账号密码错 → 换账号
   - 都正常但仍失败 → 密码确实做了 AES 封装，需要按 02 篇 2.4 节继续逆向
2. **拿 SID 后**：`probe`，重点看 `qbox_get_max_log`、`qbox_get_syncing_folder_list`、`get_domain_ip_list`
3. **变更事件**：在 NAS 上改一个文件，再跑一次 `probe`，对比两次 `qbox_get_sync_log` 的差异
4. **传输参数**：用 NAS 自带工具或 `tcpdump` 抓 Windows Qsync 的下载/上传，量出分片大小与轮询间隔

## 与主报告的关系

- 端点与参数全部来自 `../04-API-参考手册.md`
- 登录流程见 `../02-登录与鉴权.md`
- 验证项目的完整清单见 `../08-Linux实现建议.md` §8.7
