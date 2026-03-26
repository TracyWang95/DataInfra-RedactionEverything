# 冒烟测试模板

本文档用于验证项目基本功能是否正常。

---

## 前置条件

1. 所有服务已启动：
   - HaS Image / YOLO（端口 8081，`has_image_server.py`）
   - HaS NER（端口 8080）
   - 后端 API（端口 8000）
   - 前端（端口 3000）

2. 运行环境检查：
   ```powershell
   .\scripts\check_env.ps1
   ```

---

## 测试步骤

### 1. 文件上传

1. 打开 http://localhost:3000
2. 上传 `testdata/ce.png`
3. 预期：文件预览正常显示

### 2. 敏感信息识别

1. 勾选需要识别的类型（如：姓名、身份证、手机号）
2. 点击「开始识别」或等待自动识别
3. 预期：识别出多个敏感区域（> 0 个边界框）

### 3. 交互式编辑

1. 点击某个识别框，验证可选中
2. 拖动边界框，验证可调整位置
3. 使用 Ctrl+Z / Ctrl+Y 验证撤销/重做

### 4. 执行脱敏

1. 选择需要脱敏的区域
2. 点击「执行脱敏」
3. 预期：脱敏后图像显示，敏感区域被遮盖

### 5. 结果下载

1. 点击「下载」按钮
2. 预期：下载脱敏后的文件

---

## 自动化测试脚本（可选）

```python
import httpx
import pathlib

base = "http://127.0.0.1:8000/api/v1"

# 1. 上传
p = pathlib.Path("testdata/ce.png")
files = {"file": (p.name, p.read_bytes(), "image/png")}
r = httpx.post(f"{base}/files/upload", files=files, timeout=60)
assert r.status_code == 200, f"Upload failed: {r.text}"
file_id = r.json()["file_id"]
print(f"✓ Upload: {file_id}")

# 2. 解析
r = httpx.get(f"{base}/files/{file_id}/parse", timeout=60)
assert r.status_code == 200, f"Parse failed: {r.text}"
print("✓ Parse")

# 3. 识别
pipes = httpx.get(f"{base}/vision-pipelines", timeout=30).json()
ocr_types = [t["id"] for p in pipes if p["mode"] == "ocr_has" for t in p["types"] if t["enabled"]]
has_image_types = [t["id"] for p in pipes if p["mode"] == "has_image" for t in p["types"] if t["enabled"]]

r = httpx.post(
    f"{base}/redaction/{file_id}/vision?page=1",
    json={"selected_ocr_has_types": ocr_types, "selected_has_image_types": has_image_types},
    timeout=120
)
assert r.status_code == 200, f"Vision failed: {r.text}"
boxes = r.json().get("bounding_boxes", [])
print(f"✓ Vision: {len(boxes)} boxes")
assert len(boxes) > 0, "No boxes detected"

# 4. 脱敏
for b in boxes:
    b["selected"] = True

r = httpx.post(
    f"{base}/redaction/execute",
    json={
        "file_id": file_id,
        "entities": [],
        "bounding_boxes": boxes,
        "config": {"replacement_mode": "structured", "entity_types": [], "custom_replacements": {}}
    },
    timeout=120
)
assert r.status_code == 200, f"Redact failed: {r.text}"
count = r.json().get("redacted_count", 0)
print(f"✓ Redact: {count} areas")
assert count > 0, "No areas redacted"

print("\n🎉 All tests passed!")
```

---

## 测试用例说明

`testdata/ce.png` 包含以下可识别内容（示例）：

- 姓名：张三
- 手机号：13800138000
- 身份证：110101199003071234
- 公司名：测试科技有限公司
- 地址：北京市海淀区中关村
- 银行卡号：6222020200012345678

预期识别结果：6 个敏感区域
