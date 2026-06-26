# RedactionEverything 功能流程（阶段模块版）

按**独立阶段模块**组织 Skill。不包含 UI 操作，不包含金融/法律/医疗等行业预设选择——识别类型由调用方根据当前文档内容传入。

## 设计原则

| 原则 | 说明 |
|------|------|
| 阶段独立 | 每个模块可单独调用、单独调试 |
| 适度粒度 | OCR 一次返回规范化结果；视觉检测合并为单模块 |
| 无 UI | 仅 API / 服务 / 脚本 |
| 无行业预设 | 实体类型、视觉类别按本次内容自选，不用 preset-scenario |

## 阶段模块一览

| 阶段 | 模块 Skill | 职责 |
|------|------------|------|
| 0 | `$redaction-model-service-check` | 模型服务健康 |
| 1 | `$redaction-ocr-module` | 图片 OCR → **规范化** blocks（含表格/表单召回） |
| 2 | `$redaction-text-entity-module` | 文本 → 敏感实体（自选 type 列表） |
| 3 | `$redaction-entity-box-map` | 实体 + OCR blocks → 字形框 |
| 4 | `$redaction-visual-detect-module` | 视觉区域（定位 + 印章 + 码区） |
| 5 | `$redaction-region-deduplicate` | 文本框与视觉框合并去重 |
| 6 | `$redaction-mask-plan-build` | 脱敏计划 |
| 7 | `$redaction-preview-image` / `$redaction-mask-*-render` | 预览或按格式渲染 |
| 8 | `$redaction-report-json` / `$redaction-compare-version` | 报告与对比 |

**已合并、勿再拆步调用：** `$redaction-image-ocr-result`、`$redaction-ocr-block-normalize`、`$redaction-ocr-table-form-recall` → `$redaction-ocr-module`；`$redaction-visual-region-locate`、`$redaction-seal-region-detect`、`$redaction-code-region-detect` → `$redaction-visual-detect-module`；`$redaction-text-ner-result` → `$redaction-text-entity-module`。

## 业务流程总调

| 业务 | 总调 Skill | 模块链 |
|------|------------|--------|
| 图片/扫描页 | `$redaction-anonymize-image-flow` | 1→2→3→4→5→6→7 |
| 纯文本 TXT | `$redaction-anonymize-text-flow` | 2→6→7(text) |
| Word DOCX | `$redaction-anonymize-docx-flow` | 2→6→7(docx) |
| PDF | `$redaction-anonymize-pdf-flow` | 文本层：2→6→7(pdf)；扫描页：1→2→3→4→5→6→7(pdf) |
| 非结构化批量 | `$redaction-anonymize-batch-flow` | batch-job → recognize → review-draft API → export |
| 结构化数据 | `$redaction-anonymize-structured-flow` | load → profile → policy → export |

## 图片链路示例（API）

```
POST /files/upload
POST /redaction/{file_id}/vision   # 内部：ocr-module + text-entity + box-map + visual-detect + dedupe
POST /redaction/{file_id}/preview-image  或  POST /redaction/execute
GET  /redaction/{file_id}/report
```

实体类型示例：判决书传 `PERSON, INSTITUTION_NAME, ADDRESS, DATE`；不必走行业预设。

## Excel

```bash
python3 .cursor/skills/redaction-skill-generate/scripts/generate_skill_workflows_excel.py
```

输出：`docs/redaction-skill-workflows.xlsx`
