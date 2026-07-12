"""自定义视觉类型的 grounding 查询词按官方 CATEGORIES 语义收窄为短类别短语.

NVIDIA LocateAnything 模型卡: detection 的 [CATEGORIES] 是"comma-separated
list"短类别短语; 把整段 checklist(Check/Exclude 行)拼进 description 正是历史
A/B 证伪的冗长负例用法(压制真检测)。修法: _checklist_prompt 为每个类型输出
"Query: <查询词>" 行(row.query 优先, 否则 name), LA 端只 ground 这个短语;
Check/Exclude 行保留在 prompt 里作为响应 schema 上下文, 不再进 grounding 描述。
"""
from types import SimpleNamespace

from app.services.vision.locate_requests import _checklist_prompt


def _item(id: str, name: str, checklist=None):
    return SimpleNamespace(
        id=id, name=name, checklist=checklist or [], rules=[], description="",
        negative_prompt="", negative_prompt_enabled=False,
    )


def test_prompt_carries_a_query_line_defaulting_to_name():
    prompt = _checklist_prompt([_item("custom_visual_features_红手印", "红手印")])
    assert "  Query: 红手印" in prompt


def test_row_query_field_wins_for_custom_types_too():
    item = _item(
        "custom_visual_features_红手印", "红手印",
        checklist=[{"rule": "红色的手印", "query": "red inked palm print"}],
    )
    prompt = _checklist_prompt([item])
    assert "  Query: red inked palm print" in prompt
    assert "  Query: 红手印" not in prompt


def test_allowed_type_ids_and_schema_unchanged():
    prompt = _checklist_prompt([_item("custom_visual_features_工牌", "工牌")])
    assert "Allowed type_id: custom_visual_features_工牌" in prompt
    assert '"objects"' in prompt
