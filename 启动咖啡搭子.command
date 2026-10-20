#!/bin/bash
# 咖啡探索搭子 —— 双击启动器（Mac）
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "首次运行，正在初始化环境（约 1 分钟）..."
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

echo "☕ 正在启动咖啡探索搭子..."
exec .venv/bin/python agent.py
