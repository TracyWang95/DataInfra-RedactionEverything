from types import SimpleNamespace

from app.services.vlm_vision_service import VlmVisionService


def test_signature_prompt_includes_configured_checklist_rows() -> None:
    prompt = VlmVisionService().build_prompt([
        SimpleNamespace(
            id="signature",
            name="签字",
            checklist=[
                {
                    "rule": "手写签名或手写姓名",
                    "positive_prompt": "签署区域内的有效签名笔迹",
                    "negative_prompt": "打印体姓名、公司名称、机构名称、印章内外环文字",
                }
            ],
            negative_prompt_enabled=True,
            negative_prompt="不要框空白签署栏、下划线、表格边框、印章。",
        )
    ])

    assert "Configured visual checklist from UI:" in prompt
    assert "手写签名或手写姓名" in prompt
    assert "签署区域内的有效签名笔迹" in prompt
    assert "打印体姓名、公司名称、机构名称、印章内外环文字" in prompt
    assert "不要框空白签署栏、下划线、表格边框、印章。" in prompt


def test_custom_vlm_prompt_uses_generic_output_contract() -> None:
    prompt = VlmVisionService().build_prompt([
        SimpleNamespace(
            id="approval_note",
            name="审批批注",
            checklist=[
                {
                    "rule": "检测手写审批意见",
                    "positive_prompt": "边缘或空白处的手写批注",
                    "negative_prompt": "打印正文和表格边框",
                }
            ],
            negative_prompt_enabled=True,
            negative_prompt="不要输出签字或印章。",
        )
    ])

    assert "Configured visual checklist from UI:" in prompt
    assert "approval_note" in prompt
    assert "检测手写审批意见" in prompt
    assert "边缘或空白处的手写批注" in prompt
    assert "不要输出签字或印章。" in prompt
    assert '"type_id":"<allowed type_id>"' in prompt
    assert '"type_id":"signature"' not in prompt
