"""咖啡探索搭子 —— 离线单元测试（硬化）。

覆盖：工具分派 / schema 校验、记忆读写、偏好推断、权限边界、推荐校验（防编造）、
技能加载、外部工具降级、反馈校验。不调用真实模型，无需 API Key。

运行：.venv/bin/python -m pytest -q
"""

from __future__ import annotations

import builtins
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent  # noqa: E402


class FakeBlock:
    """模拟 Anthropic SDK 的 tool_use block。"""

    def __init__(self, name: str, input: dict):
        self.name = name
        self.input = input


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """每个用例用独立临时目录，不污染真实 data/。"""
    monkeypatch.setattr(agent, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(agent, "TRAJECTORY_DIR", tmp_path / ".trajectories")
    yield


# ---------------------------------------------------------------------------
# 记忆读写（s09）
# ---------------------------------------------------------------------------

def test_save_and_query_record_with_rich_fields():
    agent._tool_save_record("测试豆", "bean", flavor="酸、甜",
                            origin="埃塞", processing="水洗", roast="浅烘",
                            price="88", location="上海", rating="4.5")
    result = agent._tool_query_records(keyword="测试豆")
    assert "测试豆" in result
    assert "产地：埃塞" in result
    assert "处理：水洗" in result
    assert "烘焙：浅烘" in result
    assert "价格：88" in result
    assert "位置：上海" in result
    assert "评分：4.5" in result


def test_query_records_filters():
    agent._tool_save_record("A豆", "bean", flavor="酸")
    agent._tool_save_record("B豆", "bean", flavor="苦", origin="印尼")
    assert "A豆" in agent._tool_query_records(flavor="酸")
    assert "B豆" not in agent._tool_query_records(flavor="酸")
    assert "B豆" in agent._tool_query_records(origin="印尼")


def test_query_records_cold_start():
    assert "冷启动" in agent._tool_query_records()


# ---------------------------------------------------------------------------
# 偏好推断（s09）
# ---------------------------------------------------------------------------

def test_preference_excludes_disliked():
    agent._tool_save_record("酸豆", "bean", flavor="酸、柑橘")
    agent._tool_save_record("苦豆", "bean", flavor="苦、草本")
    agent._tool_save_feedback("苦豆", "dislike", flavor="苦")
    data = json.loads(agent._tool_load_preference())
    assert "苦豆" in data["排除清单（踩过）"]
    assert any("苦" in t or "草本" in t for t in data["避开风味"])


def test_flavor_split():
    assert agent._split_flavors("酸、柑橘、花香") == ["酸", "柑橘", "花香"]
    assert agent._split_flavors("酸, 甜") == ["酸", "甜"]


def test_profile_report():
    agent._tool_save_record("酸豆", "bean", flavor="酸")
    report = agent.build_profile_report()
    assert "口味画像" in report
    assert "酸豆" in report


# ---------------------------------------------------------------------------
# schema 校验（s02）
# ---------------------------------------------------------------------------

def test_validate_input_missing_required():
    tool = agent.TOOLS["save_record"]
    with pytest.raises(ValueError):
        agent._validate_input(tool, {})
    agent._validate_input(tool, {"name": "x", "type_": "bean"})


def test_validate_input_wrong_type():
    tool = agent.TOOLS["save_record"]
    with pytest.raises(ValueError):
        agent._validate_input(tool, {"name": "x", "type_": "bean", "rating": 5})


# ---------------------------------------------------------------------------
# 权限边界（s03 + s04）
# ---------------------------------------------------------------------------

def test_pre_tool_hook_blocks_money():
    block = FakeBlock("save_record", {"name": "x", "type_": "bean", "note": "帮我下单买豆"})
    out = agent._pre_tool_hook(block)
    assert out is not None and "已拦截" in out


def test_pre_tool_hook_blocks_sensitive():
    block = FakeBlock("save_record", {"name": "x", "type_": "bean", "note": "医疗建议"})
    assert agent._pre_tool_hook(block) is not None


def test_pre_tool_hook_ask_consent(monkeypatch):
    block = FakeBlock("save_record", {"name": "x", "type_": "bean"})
    monkeypatch.setattr(builtins, "input", lambda prompt="": "y")
    assert agent._pre_tool_hook(block) is None  # 同意 → 放行
    monkeypatch.setattr(builtins, "input", lambda prompt="": "n")
    assert "拒绝" in agent._pre_tool_hook(block)  # 拒绝 → 阻断


# ---------------------------------------------------------------------------
# 推荐校验（防编造）
# ---------------------------------------------------------------------------

def test_validate_recommendation_pass():
    text = "推荐【店铺】Manner【豆子】耶加雪菲【理由】因为偏酸有柑橘香"
    out = agent._tool_validate_recommendation(text, candidates="Manner；耶加雪菲")
    assert out.startswith("通过")


def test_validate_recommendation_missing_element():
    out = agent._tool_validate_recommendation("就买这个吧", candidates="Manner")
    assert "不通过" in out


def test_validate_recommendation_untraceable():
    text = "推荐【店铺】Manner【豆子】耶加雪菲【理由】因为好喝"
    out = agent._tool_validate_recommendation(text, candidates="蓝瓶咖啡")
    assert "未溯源" in out


# ---------------------------------------------------------------------------
# 技能加载（s07）
# ---------------------------------------------------------------------------

def test_skill_catalog_and_load():
    assert "flavor" in agent.KNOWLEDGE.catalog()
    assert "风味" in agent.KNOWLEDGE.load("flavor")
    assert "未找到" in agent.KNOWLEDGE.load("不存在的话题")


# ---------------------------------------------------------------------------
# 外部工具降级（s14）
# ---------------------------------------------------------------------------

def test_search_nearby_degrades_without_key(monkeypatch):
    monkeypatch.delenv("AMAP_API_KEY", raising=False)
    assert "降级" in agent._tool_search_nearby_cafes()


# ---------------------------------------------------------------------------
# 反馈校验
# ---------------------------------------------------------------------------

def test_save_feedback_kind_validation():
    assert "Error" in agent._tool_save_feedback("x", "wrong")
    assert "正反馈" in agent._tool_save_feedback("x", "like")
    assert "负反馈" in agent._tool_save_feedback("x", "dislike")
