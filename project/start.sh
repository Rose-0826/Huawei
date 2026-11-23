#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

MODE="auto"
for arg in "$@"; do
  case "$arg" in
    --mock|-m) MODE="mock" ;;
    --real|-r) MODE="real" ;;
    --help|-h)
      echo "用法：./start.sh [--mock|--real]"
      echo "  --mock   强制 Mock 模式"
      echo "  --real   强制真实模型（读取 .env）"
      echo "  默认：有 .env 用真实模型，没有则 Mock"
      exit 0
      ;;
    *)
      echo "未知参数：$arg（用 --help 查看用法）" >&2
      exit 2
      ;;
  esac
done

if ! command -v python3 >/dev/null 2>&1; then
  echo "找不到 python3，请先安装 Python 3.10+。" >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi

. .venv/bin/activate
echo "安装依赖……"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

if [ "$MODE" = "real" ] && [ ! -f .env ]; then
  echo "指定了 --real，但 project/.env 不存在。请先 cp .env.example .env 并填写 MAAS_*。" >&2
  exit 1
fi

if [ "$MODE" = "mock" ] || { [ "$MODE" = "auto" ] && [ ! -f .env ]; }; then
  export MOCK_LLM=1
  echo "模式：Mock（不请求真实模型）"
else
  unset MOCK_LLM || true
  echo "模式：真实模型（读取 project/.env）"
fi

echo "打开：http://127.0.0.1:8000/blood"
echo "按 Ctrl+C 停止。"
exec python -m app.main