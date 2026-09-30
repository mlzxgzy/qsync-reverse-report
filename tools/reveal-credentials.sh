#!/usr/bin/env bash
# 从你自己合法获得的 Qsync 安装副本中提取 OAuth 客户端凭据。
# 报告中以掩码显示，避免在公开仓库里散布第三方凭据。
#
# 用法: ./tools/reveal-credentials.sh "/path/to/Qsync/Qsync.exe"
set -euo pipefail
BIN="${1:-}"
if [ -z "$BIN" ] || [ ! -f "$BIN" ]; then
  echo "用法: $0 <Qsync.exe 路径>" >&2; exit 1
fi
echo "=== client_id ==="
LC_ALL=C strings -a -n 8 "$BIN" | grep -xE '[0-9a-f]{24}' | head -5
echo "=== client_secret（48 字符 base62）==="
LC_ALL=C strings -a -n 40 "$BIN" | grep -xE '[0-9A-Za-z]{48}' | head -5
echo
echo "提示：报告中 client_id 在 Qsync.exe 文件偏移 0x002f0e6c 附近（字面量紧随 \"client_id\" 键名之后）；"
echo "     client_secret 在 0x002f0e98 附近。用 xxd/strings 按偏移查看即可确认。"
