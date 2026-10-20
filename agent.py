#!/usr/bin/env python3
"""
咖啡探索搭子 —— 生产级骨架（Step 5 第一层「骨架」）

基于 agent-blueprint 的 scaffold 模板搭建，集成 v2 方案选定的 8 个组件：
    s01 Agent Loop      —— 主循环：messages → model → tool_use → 结果 → 循环
    s02 工具系统        —— TOOLS 注册表 + schema 校验 + 统一错误回传
    s03 权限系统        —— 写入类操作需确认；金钱操作默认拒绝
    s04 钩子系统        —— PreToolUse（拦截/权限）+ PostToolUse（日志/轨迹）
    s07 技能加载        —— 咖啡专业知识按需加载（coffee_knowledge/）
    s09 记忆系统        —— 本地持久化记录 / 反馈，口味偏好按记录推断
    s14 MCP 插件        —— 外部工具命名空间接入（高德 POI 搜索，可降级）
    s15 集成 Harness    —— 单一循环 + 动态系统提示词 + 共享客户端

运行：
    python agent.py
依赖：
    pip install anthropic python-dotenv pyyaml
配置：
    cp .env.example .env   # 填 ANTHROPIC_API_KEY（DeepSeek 用 base_url 指向 anthropic 网关）
                           # AMAP_API_KEY 可选，不填则外部搜索自动降级为本地记录推荐
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml
from anthropic import Anthropic, APIStatusError, APITimeoutError, APIConnectionError
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv(override=True)

WORKDIR = Path(__file__).resolve().parent
DATA_DIR = WORKDIR / "data"
KNOWLEDGE_DIR = WORKDIR / "coffee_knowledge"
TRAJECTORY_DIR = WORKDIR / ".trajectories"
LOG = logging.getLogger("coffee-buddy")


def load_config() -> dict:
    config: dict = {
        "model": os.getenv("MODEL_ID", "deepseek-chat"),
        "max_tokens": int(os.getenv("MAX_TOKENS", "2000")),
        "timeout_seconds": float(os.getenv("TIMEOUT_SECONDS", "120")),
        "max_retries": int(os.getenv("MAX_RETRIES", "3")),
        "base_delay_seconds": float(os.getenv("BASE_DELAY_SECONDS", "0.5")),
    }
    config_path = WORKDIR / "config.yaml"
    if config_path.exists():
        with config_path.open(encoding="utf-8") as handle:
            file_config = yaml.safe_load(handle) or {}
        if isinstance(file_config, dict):
            for key, value in file_config.items():
                config.setdefault(key, value)
    return config


CONFIG = load_config()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))


# ---------------------------------------------------------------------------
# Memory store (s09) —— 本地 JSON 持久化
# ---------------------------------------------------------------------------

def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        LOG.warning("failed to read %s: %s", path, exc)
        return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _records() -> list[dict]:
    return _load_json(DATA_DIR / "records.json", [])


def _feedback() -> list[dict]:
    return _load_json(DATA_DIR / "feedback.json", [])


def _save_records(items: list[dict]) -> None:
    _save_json(DATA_DIR / "records.json", items)


def _save_feedback(items: list[dict]) -> None:
    _save_json(DATA_DIR / "feedback.json", items)


# ---------------------------------------------------------------------------
# Skill loading (s07) —— 咖啡专业知识按需加载
# ---------------------------------------------------------------------------

@dataclass
class KnowledgeCard:
    name: str
    description: str
    content: str


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, parts[2].strip()


class SkillLoader:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.cards: dict[str, KnowledgeCard] = {}
        self.scan()

    def scan(self) -> None:
        self.cards.clear()
        if not self.skills_dir.exists():
            return
        for manifest in sorted(self.skills_dir.glob("*.md")):
            content = manifest.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(content)
            name = str(meta.get("name", manifest.stem)).strip()
            desc = str(meta.get("description", "")).strip() or body.split("\n", 1)[0]
            self.cards[name] = KnowledgeCard(name=name, description=desc, content=content)

    def catalog(self) -> str:
        if not self.cards:
            return "(没有可用的咖啡知识卡)"
        return "\n".join(f"- {c.name}: {c.description}" for c in self.cards.values())

    def load(self, name: str) -> str:
        card = self.cards.get(name)
        if card:
            return card.content
        available = "、".join(self.cards) or "无"
        return f"未找到知识卡「{name}」，可用：{available}"


KNOWLEDGE = SkillLoader(KNOWLEDGE_DIR)


# ---------------------------------------------------------------------------
# Tool Registry (s02)
# ---------------------------------------------------------------------------

@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[..., str]
    permission: str = "allow"  # allow | ask | deny


def _validate_input(tool: Tool, args: dict) -> dict:
    props = tool.input_schema.get("properties", {})
    required = tool.input_schema.get("required", [])
    for field_name in required:
        if field_name not in args:
            raise ValueError(f"缺少必填字段：{field_name}")
    for key, value in args.items():
        expected = props.get(key, {}).get("type")
        if expected == "string" and not isinstance(value, str):
            raise ValueError(f"{key} 必须是字符串")
        elif expected == "integer" and not isinstance(value, int):
            raise ValueError(f"{key} 必须是整数")
        elif expected == "number" and not isinstance(value, (int, float)):
            raise ValueError(f"{key} 必须是数字")
        elif expected == "boolean" and not isinstance(value, bool):
            raise ValueError(f"{key} 必须是布尔值")
    return args


# -- 领域工具实现 ------------------------------------------------------------

def _split_flavors(value) -> list[str]:
    return [t for t in re.split(r"[、,，/／\s]+", str(value or "")) if t]


def _flavor_tally() -> tuple[Counter, Counter, list[str], int]:
    """从记录 + 反馈推断口味：返回 (正向风味计数, 负向风味计数, 排除清单, 总条数)。"""
    records = _records()
    feedback = _feedback()
    liked = {f["target"] for f in feedback if f.get("kind") == "like"}
    disliked = {f["target"] for f in feedback if f.get("kind") == "dislike"}
    pos: Counter = Counter()
    neg: Counter = Counter()
    for r in records:
        name = r.get("name", "")
        tags = _split_flavors(r.get("flavor"))
        if not tags:
            continue
        if name in disliked:
            neg.update(tags)
        elif name in liked or r.get("type") in ("taste", "口味"):
            pos.update(tags)
    return pos, neg, sorted(disliked), len(records)


def _tool_query_records(flavor: str = "", keyword: str = "", origin: str = "",
                        roast: str = "", location: str = "") -> str:
    records = _records()
    if flavor:
        records = [r for r in records if flavor in str(r.get("flavor", ""))]
    if keyword:
        kw = keyword.lower()
        records = [r for r in records
                   if kw in str(r.get("name", "")).lower() or kw in str(r.get("note", "")).lower()]
    if origin:
        records = [r for r in records if origin in str(r.get("origin", ""))]
    if roast:
        records = [r for r in records if roast in str(r.get("roast", ""))]
    if location:
        records = [r for r in records if location in str(r.get("location", ""))]
    if not records:
        return "(没有匹配的记录，请先用 save_record 录入，或说明冷启动)"
    lines = []
    for r in records:
        parts = [f"[{r.get('type', '?')}] {r.get('name')}",
                 f"风味：{r.get('flavor', '未标注')}"]
        if r.get("origin"):
            parts.append(f"产地：{r['origin']}")
        if r.get("processing"):
            parts.append(f"处理：{r['processing']}")
        if r.get("roast"):
            parts.append(f"烘焙：{r['roast']}")
        if r.get("brew"):
            parts.append(f"冲煮：{r['brew']}")
        if r.get("price"):
            parts.append(f"价格：{r['price']}")
        if r.get("location"):
            parts.append(f"位置：{r['location']}")
        if r.get("rating") not in (None, ""):
            parts.append(f"评分：{r['rating']}")
        if r.get("note"):
            parts.append(f"备注：{r['note']}")
        lines.append("- " + "；".join(parts))
    return "\n".join(lines)


def _tool_load_preference() -> str:
    pos, neg, disliked, total = _flavor_tally()
    pos_tags = [f"偏{t}" for t, _ in pos.most_common(3)]
    neg_tags = [t for t, _ in neg.most_common(3)]
    return json.dumps({
        "偏好推断": pos_tags or ["（暂无足够数据）"],
        "避开风味": neg_tags or ["（无）"],
        "排除清单（踩过）": disliked or ["（无）"],
        "已收录条数": total,
    }, ensure_ascii=False, indent=2)


def _tool_load_coffee_knowledge(topic: str) -> str:
    return KNOWLEDGE.load(topic)


def _tool_search_nearby_cafes(keywords: str = "咖啡馆", city: str = "") -> str:
    key = os.getenv("AMAP_API_KEY", "").strip()
    if not key:
        return ("未配置高德 Key（AMAP_API_KEY），外部搜索不可用。"
                "已按降级策略退回：仅用本地已记录数据推荐，并如实告知用户。")
    params = {
        "key": key,
        "keywords": keywords,
        "output": "json",
        "offset": "5",
        "extensions": "base",
    }
    if city:
        params["city"] = city
    url = "https://restapi.amap.com/v3/place/text?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") != "1":
            return f"高德接口返回异常：{data.get('info', 'unknown')}（已降级）"
        pois = data.get("pois", [])
        if not pois:
            return "(高德没有搜到相关结果)"
        lines = []
        for p in pois[:5]:
            lines.append(f"- {p.get('name')}｜{p.get('adname', '')}{p.get('address', '')}"
                         f"｜类型：{p.get('type', '')}")
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"高德搜索失败：{type(exc).__name__}: {exc}（已降级为本地记录推荐）"


def _tool_save_record(name: str, type_: str, flavor: str = "", note: str = "",
                      origin: str = "", processing: str = "", roast: str = "",
                      brew: str = "", price: str = "", location: str = "",
                      rating: str = "") -> str:
    records = _records()
    records.append({
        "type": type_, "name": name, "flavor": flavor, "note": note,
        "origin": origin, "processing": processing, "roast": roast,
        "brew": brew, "price": price, "location": location, "rating": rating,
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    _save_records(records)
    return f"已保存记录：{name}（{type_}）"


def _tool_save_feedback(target: str, kind: str, flavor: str = "") -> str:
    if kind not in ("like", "dislike"):
        return "Error: kind 只能是 like（正反馈）或 dislike（负反馈）"
    feedback = _feedback()
    feedback.append({"target": target, "kind": kind, "flavor": flavor,
                     "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
    _save_feedback(feedback)
    return f"已记录{'正' if kind == 'like' else '负'}反馈：{target}"


def _tool_validate_recommendation(text: str, candidates: str = "") -> str:
    """校验推荐是否包含三要素且理由可溯源到候选集，防止编造。"""
    problems = []
    candidate_list = [c.strip() for c in re.split(r"[\n;；]", candidates) if c.strip()]
    # 三要素：店铺 / 豆子 / 理由（中文启发式）
    has_bean = any(w in text for w in ("豆", "豆子", "咖啡豆"))
    has_reason = any(w in text for w in ("理由", "因为", "推荐", "适合", "风味"))
    has_shop = any(w in text for w in ("店", "咖啡馆", "馆")) or bool(candidate_list)
    if not has_bean:
        problems.append("缺少「豆子」要素")
    if not has_reason:
        problems.append("缺少「推荐理由」要素")
    if not has_shop:
        problems.append("缺少「店铺」要素")
    # 可溯源：候选核心名（去括号）的任一词元应出现在推荐文本中
    def _core(name: str) -> str:
        return name.split("（")[0].split("(")[0].strip()
    if candidate_list:
        missing = []
        for c in map(_core, candidate_list):
            tokens = [t for t in re.split(r"[\s、]+", c) if len(t) >= 2]
            if tokens and not any(t in text for t in tokens):
                missing.append(c)
        if missing:
            problems.append(f"以下候选未溯源：{missing}")
    else:
        problems.append("未提供候选集，推荐理由无法溯源（请先 query_records / search_nearby_cafes）")
    if problems:
        return "不通过：" + "；".join(problems) + "。请修正后重新校验。"
    return "通过：包含店铺/豆子/理由三要素，且候选对象可溯源，未编造。"


TOOLS: dict[str, Tool] = {
    "query_records": Tool(
        name="query_records",
        description="查询已记录的咖啡馆/豆子/菜单/口味记录，可按风味或关键词过滤。推荐前先用它取候选集。",
        input_schema={"type": "object",
                      "properties": {"flavor": {"type": "string"}, "keyword": {"type": "string"}},
                      "required": []},
        handler=lambda **a: _tool_query_records(**a),
        permission="allow",
    ),
    "load_preference": Tool(
        name="load_preference",
        description="读取推断出的口味偏好、避开的风味和「踩」过的排除清单。",
        input_schema={"type": "object", "properties": {}, "required": []},
        handler=lambda **a: _tool_load_preference(),
        permission="allow",
    ),
    "load_coffee_knowledge": Tool(
        name="load_coffee_knowledge",
        description="按需加载专业咖啡知识卡（风味/产地/处理方式/烘焙度/冲煮方式），用于写推荐理由。",
        input_schema={"type": "object",
                      "properties": {"topic": {"type": "string"}}, "required": ["topic"]},
        handler=lambda topic: _tool_load_coffee_knowledge(topic),
        permission="allow",
    ),
    "search_nearby_cafes": Tool(
        name="search_nearby_cafes",
        description="通过高德 POI 搜索附近咖啡馆（外部工具，命名空间 amap）。未配置 Key 会自动降级。",
        input_schema={"type": "object",
                      "properties": {"keywords": {"type": "string"}, "city": {"type": "string"}},
                      "required": []},
        handler=lambda **a: _tool_search_nearby_cafes(**a),
        permission="allow",
    ),
    "save_record": Tool(
        name="save_record",
        description="保存一条咖啡馆/豆子/菜单/口味记录（会改变后续推荐候选集）。可带产地、处理方式、烘焙度、冲煮方式、价格、位置、评分等字段。",
        input_schema={"type": "object",
                      "properties": {"name": {"type": "string"}, "type_": {"type": "string"},
                                     "flavor": {"type": "string"}, "note": {"type": "string"},
                                     "origin": {"type": "string"}, "processing": {"type": "string"},
                                     "roast": {"type": "string"}, "brew": {"type": "string"},
                                     "price": {"type": "string"}, "location": {"type": "string"},
                                     "rating": {"type": "string"}},
                      "required": ["name", "type_"]},
        handler=lambda **a: _tool_save_record(**a),
        permission="ask",
    ),
    "save_feedback": Tool(
        name="save_feedback",
        description="记录用户对推荐的正反馈(like)/负反馈(dislike)，下次推荐会避开负反馈对象。",
        input_schema={"type": "object",
                      "properties": {"target": {"type": "string"}, "kind": {"type": "string"},
                                     "flavor": {"type": "string"}},
                      "required": ["target", "kind"]},
        handler=lambda **a: _tool_save_feedback(**a),
        permission="ask",
    ),
    "validate_recommendation": Tool(
        name="validate_recommendation",
        description="在输出最终推荐前自检：是否包含店铺/豆子/理由三要素、理由是否可溯源到候选集。",
        input_schema={"type": "object",
                      "properties": {"text": {"type": "string"}, "candidates": {"type": "string"}},
                      "required": ["text"]},
        handler=lambda **a: _tool_validate_recommendation(**a),
        permission="allow",
    ),
}

TOOL_DEFS = [
    {"name": t.name, "description": t.description, "input_schema": t.input_schema}
    for t in TOOLS.values()
]


# ---------------------------------------------------------------------------
# Hooks (s04) + Permission (s03)
# ---------------------------------------------------------------------------

HOOKS: dict[str, list[Callable]] = {"PreToolUse": [], "PostToolUse": []}

# 敏感/越权主题：按产品边界直接拒绝
DENY_TOPICS = ("下单", "付款", "支付", "转账", "购买", "结账", "政治", "医疗", "药", "挂号")


def _pre_tool_hook(block) -> str | None:
    """PreToolUse：越权拦截 + 写入确认。返回非 None 表示阻断该工具调用。"""
    args = dict(getattr(block, "input", {}) or {})
    blob = json.dumps(args, ensure_ascii=False)
    for topic in DENY_TOPICS:
        if topic in blob:
            return f"已拦截：产品边界只做记录与推荐，不处理「{topic}」相关操作。"
    tool = TOOLS.get(block.name)
    if tool and tool.permission == "ask":
        answer = input(f"  [权限确认] 是否允许 {tool.name}({blob[:60]})？[y/N] ")
        if answer.strip().lower() not in {"y", "yes", "是"}:
            return f"用户拒绝了写入操作 {tool.name}"
    return None


def _post_tool_hook(block, output: str) -> None:
    LOG.info("tool=%s output=%s", block.name, output[:120])


for _event in ("PreToolUse", "PostToolUse"):
    HOOKS[_event]  # noqa: B018 —— 占位，保持结构清晰


# ---------------------------------------------------------------------------
# System prompt（动态，含知识目录）
# ---------------------------------------------------------------------------

def build_system_prompt() -> str:
    return f"""你是「咖啡探索搭子」，一名只做记录与推荐的个人咖啡助手。工作目录：{WORKDIR}。

身份：帮用户记录探店、买豆与口味评价，依据记录与推断出的口味偏好，给出带理由的店铺与豆子推荐。

规则：
1. 每次推荐必须同时包含【店铺】【豆子】【推荐理由】三要素，缺一不可。
2. 推荐理由必须可溯源到 query_records / search_nearby_cafes 的候选集或 load_coffee_knowledge 的知识卡，禁止编造不存在的店铺、豆子、菜单或价格；信息缺失时如实说「待确认」。
3. 在输出最终推荐前，必须先调用 validate_recommendation 自检，通过后才能给用户。
4. load_preference 里「排除清单（踩过）」的对象绝不能再推荐；避开「避开风味」。
5. 只做记录与推荐；拒绝任何下单、付款等金钱操作，不处理政治、医疗等敏感话题。
6. 需要写入时，直接调用 save_record / save_feedback 工具即可，权限系统会自动向用户请求确认，不要在文本里先问一遍；被拒绝就不再写入。
7. 外部搜索失败或本地无记录（冷启动）时，如实说明并退回仅用已有数据推荐，不虚构补充。

推荐时的标准步骤：query_records 或 search_nearby_cafes 取候选集 → load_preference 取偏好与排除清单 → 需要时 load_coffee_knowledge 补充专业知识 → 组织推荐 → validate_recommendation 自检 → 输出。

咖啡知识卡目录：
{KNOWLEDGE.catalog()}

工具：{', '.join(TOOLS)}。
"""


SYSTEM_PROMPT = build_system_prompt()


# ---------------------------------------------------------------------------
# Model call with retry
# ---------------------------------------------------------------------------

def _backoff(attempt: int) -> float:
    return CONFIG["base_delay_seconds"] * (2 ** attempt)


def call_model(messages: list[dict]) -> Any:
    last_error: Exception | None = None
    for attempt in range(CONFIG["max_retries"]):
        try:
            return client.messages.create(
                model=CONFIG["model"],
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=TOOL_DEFS,
                max_tokens=CONFIG["max_tokens"],
                timeout=CONFIG["timeout_seconds"],
            )
        except (APITimeoutError, APIConnectionError, APIStatusError) as exc:
            last_error = exc
            delay = _backoff(attempt)
            LOG.warning("模型调用失败（第 %d/%d 次）：%s；%.1fs 后重试",
                        attempt + 1, CONFIG["max_retries"], exc, delay)
            time.sleep(delay)
    raise RuntimeError(f"模型调用失败（已重试 {CONFIG['max_retries']} 次）：{last_error}")


# ---------------------------------------------------------------------------
# Trajectory capture（可观测性：轨迹数据）
# ---------------------------------------------------------------------------

def record_trajectory(entry: dict) -> None:
    try:
        TRAJECTORY_DIR.mkdir(parents=True, exist_ok=True)
        path = TRAJECTORY_DIR / f"trajectory-{time.strftime('%Y%m%d')}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
    except Exception as exc:  # noqa: BLE001
        LOG.warning("轨迹记录失败：%s", exc)


# ---------------------------------------------------------------------------
# Agent loop (s01 + s15)
# ---------------------------------------------------------------------------

def agent_loop(prompt: str, history: list[dict] | None = None) -> str:
    history = history if history is not None else []
    history.append({"role": "user", "content": prompt})

    while True:
        response = call_model(history)
        history.append({"role": "assistant", "content": response.content})

        tool_calls = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
        if not tool_calls:
            return "".join(b.text for b in response.content if getattr(b, "type", None) == "text")

        results = []
        for block in tool_calls:
            tool = TOOLS.get(block.name)
            # s04 PreToolUse：越权拦截 / 权限确认
            blocked = _pre_tool_hook(block)
            if blocked is not None:
                output = blocked
            elif tool is None:
                output = f"未知工具：{block.name}"
            else:
                try:
                    args = _validate_input(tool, dict(block.input))
                    output = tool.handler(**args)
                except Exception as exc:  # noqa: BLE001
                    output = f"Error: {type(exc).__name__}: {exc}"
            # s04 PostToolUse
            _post_tool_hook(block, output)
            record_trajectory({
                "ts": time.time(),
                "tool": block.name,
                "input": getattr(block, "input", {}),
                "output": output[:1000],
            })
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})

        history.append({"role": "user", "content": results})


def build_profile_report() -> str:
    """口味画像报告：聚合记录与反馈，输出可读文本（产品化·可视化）。"""
    pos, neg, disliked, total = _flavor_tally()
    records = _records()
    by_type = Counter(r.get("type", "?") for r in records)
    lines = ["☕ 咖啡探索搭子 · 口味画像", "=" * 34,
             f"已收录记录：{total} 条（" + "、".join(f"{k} {v}" for k, v in by_type.most_common()) + "）",
             ""]
    lines.append("偏好风味（正向）：")
    if pos:
        for tag, n in pos.most_common(6):
            lines.append(f"  {tag:<8} {'█' * n} {n}")
    else:
        lines.append("  （暂无足够数据）")
    lines.append("")
    lines.append("避开风味（负向）：")
    if neg:
        for tag, n in neg.most_common(6):
            lines.append(f"  {tag:<8} {'░' * n} {n}")
    else:
        lines.append("  （无）")
    lines.append("")
    lines.append("排除清单（踩过）：" + ("、".join(disliked) if disliked else "（无）"))
    recent = records[-3:][::-1]
    if recent:
        lines.append("")
        lines.append("最近记录：")
        for r in recent:
            lines.append(f"  - [{r.get('type')}] {r.get('name')}（{r.get('flavor', '未标注')}）")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _shutdown(signum, _frame):
    LOG.info("收到信号 %s，正在退出", signum)
    sys.exit(128 + signum)


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if "--profile" in sys.argv:
        print(build_profile_report())
        return
    LOG.info("咖啡探索搭子启动；model=%s workdir=%s", CONFIG["model"], WORKDIR)
    print(f"☕ 咖啡探索搭子就绪（模型：{CONFIG['model']}）。")
    print("   试试：「想喝偏酸的豆子」或「记一下：Manner 的埃塞水洗豆，偏酸」。")
    print("   输入 q 退出。\n")

    history: list[dict] = []
    while True:
        try:
            query = input(">> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if query in {"q", "quit", "exit", ""}:
            break
        try:
            print(agent_loop(query, history))
        except Exception as exc:  # noqa: BLE001
            LOG.error("agent loop 失败：%s", exc)
            print(f"Error: {exc}")
        print()


if __name__ == "__main__":
    main()
