# ☕ 咖啡探索搭子（Coffee Buddy）

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-blue.svg)
![Tests](https://github.com/zhujy9413-commits/coffee-buddy/actions/workflows/test.yml/badge.svg)

一个**个人 Agent**：整理咖啡馆、豆单与菜单，记住口味偏好，推荐下一次尝试并解释理由。

由 [Agent Blueprint](../agent-blueprint/) 推导出的 **Step 5 骨架**（第一层「骨架」），集成 8 个组件：
`s01 循环 + s02 工具 + s03 权限 + s04 钩子 + s07 技能 + s09 记忆 + s14 外部工具 + s15 集成`。

> 📄 需求与决策以 [PRD.md](PRD.md) 为唯一事实基线。

## 快速开始

```sh
# 1. 建环境（Python 3.10+）
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. 配置
cp .env.example .env      # 填 ANTHROPIC_API_KEY（DeepSeek 用上面的 base_url 即可）
                          # AMAP_API_KEY 可选

# 3. 运行
.venv/bin/python agent.py
```

## 对话示例

```
>> 记一下：Manner 的埃塞俄比亚水洗豆，偏酸，有柑橘香
   [权限确认] 是否允许 save_record(...)？[y/N] y
>> 想喝偏酸的豆子
   （Agent 自动：查记录 → 查偏好 → 补知识 → 组织推荐 → 自检 → 输出）
```

## 口味画像

```sh
.venv/bin/python agent.py --profile   # 打印口味画像报告（偏好/避开/排除清单/最近记录）
```

## 测试（硬化）

```sh
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

## 目录结构

```
agent.py              # 主程序：单一循环 + 8 组件集成
coffee_knowledge/     # 咖啡知识卡（s07 按需加载）：风味/产地/处理/烘焙/冲煮
data/                 # 本地记忆（s09，自动生成）：records.json / feedback.json
.trajectories/        # 轨迹数据（可观测性，自动生成）
.env.example          # 配置模板
config.example.yaml   # 可选声明式配置
```

## 工具清单

| 工具 | 权限 | 说明 |
|---|---|---|
| query_records | allow | 查本地记录，取候选集（可按风味/关键词/产地/烘焙/位置过滤） |
| load_preference | allow | 读口味偏好 + 「踩」排除清单 |
| load_coffee_knowledge | allow | 按需加载咖啡知识卡 |
| search_nearby_cafes | allow | 高德 POI 搜索（未配 Key 自动降级） |
| save_record | **ask** | 写记录，需用户确认（可带产地/处理/烘焙/冲煮/价格/位置/评分） |
| save_feedback | **ask** | 写正/负反馈，需用户确认 |
| validate_recommendation | allow | 输出前自检三要素 + 可溯源 |

## 边界（写死在代码里，不只是提示词）

- 拦截下单/付款/政治/医疗等关键词（s04 PreToolUse 硬拦截）
- 写入类操作必须用户确认（s03 权限）
- 推荐理由必须可溯源，禁止编造（validate_recommendation）
- 数据默认只存本机 `data/`（s09 本地记忆）

## 下一步（硬化 → 产品化）

本骨架可运行。后续按需加入：错误处理与超时细化、单测（工具分派/权限边界）、
更多外部数据源（MCP server）、后台任务与定时推荐等。
