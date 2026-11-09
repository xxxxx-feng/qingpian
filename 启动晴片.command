#!/bin/zsh
set -euo pipefail

TOOL_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$TOOL_ROOT"

if [[ -d "$TOOL_ROOT/dist/晴片.app" ]]; then
  open "$TOOL_ROOT/dist/晴片.app"
  exit 0
fi

PYTHON_BIN=""
for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3 \
  /opt/homebrew/bin/python3 /usr/local/bin/python3 "$HOME/.local/bin/python3.12"; do
  if command -v "$candidate" >/dev/null 2>&1 && \
    "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v "$candidate")"
    break
  fi
done

if [[ -z "$PYTHON_BIN" ]]; then
  print "请先安装 Python 3.10 或更新版本：https://www.python.org/downloads/"
  read -r "reply?按回车退出…"
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  "$PYTHON_BIN" -m venv .venv
fi
if ! .venv/bin/python -c 'import PIL, numpy, pillow_heif, PySide6.QtWidgets' >/dev/null 2>&1; then
  print "首次启动正在安装依赖，需要联网；照片处理始终在本机进行。"
  if ! .venv/bin/python -m pip install -r requirements.txt; then
    print "依赖安装失败。请检查网络后重试。"
    read -r "reply?按回车退出…"
    exit 1
  fi
fi
exec .venv/bin/python app.py

