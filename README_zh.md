# DataInfra-RedactionEverything

本项目是本地优先的文档匿名化与脱敏系统，覆盖混合文件、扫描件、图片和 PDF。

当前运行时已经收敛为一条新的视觉链路：

- PaddleOCR-VL 1.6：负责图片文字和文档元素抽取。
- PP-StructureV3：补强版面、表格和结构化扫描件内容。
- HaS Text：基于 OCR 文本做语义实体识别。
- LocateAnything-3B：统一处理视觉特征，包括 22 个固定预设和用户新增视觉标签。

旧的拆分视觉特征/清单模型路径已经移除。所有非文本视觉隐私目标统一叫“视觉特征”，前端配置、后端接口和算法入口都按这个模型纳管。

## 能力划分

| 能力 | 运行时 |
| --- | --- |
| 文档和扫描件文字 | PaddleOCR-VL 1.6 + PP-StructureV3 |
| 文本语义实体 | HaS Text |
| 表格和结构化版面 | PP-StructureV3 |
| 固定视觉特征 | LocateAnything-3B |
| 用户新增视觉标签 | LocateAnything-3B checklist grounding |
| 印章识别 | PaddleOCR-VL 优先，LocateAnything 作为补充视觉证据 |

## 视觉特征预设

内置 22 类固定视觉特征：

`face`, `fingerprint`, `palmprint`, `id_card`, `hk_macau_permit`, `passport`, `employee_badge`, `license_plate`, `bank_card`, `physical_key`, `receipt`, `shipping_label`, `official_seal`, `whiteboard`, `sticky_note`, `mobile_screen`, `monitor_screen`, `medical_wristband`, `qr_code`, `barcode`, `paper`, `signature`。

用户可以在识别项设置里新增视觉特征标签。新增标签会进入同一条视觉特征管道，由 LocateAnything 按配置清单定位。

## 本地启动

安装依赖后运行：

```bash
npm run dev
```

开发入口按顺序启动：

1. PaddleOCR-VL 1.6 vLLM 服务，端口 `8118`
2. HaS Text vLLM 服务，端口 `8080`
3. PaddleOCR/PP-Structure 包装服务，端口 `8082`
4. LocateAnything 视觉特征服务，端口 `8090`
5. 后端 API，端口 `8000`
6. 前端，端口 `3000`

启动流程会预热 PaddleOCR-VL、PP-StructureV3、HaS Text 和 LocateAnything，然后再提示可测试。

停止本地服务：

```bash
npm run stop
```

## 关键服务变量

```env
OCR_BASE_URL=http://127.0.0.1:8082
HAS_LLAMACPP_BASE_URL=http://127.0.0.1:8080/v1
VISUAL_FEATURES_BASE_URL=http://127.0.0.1:8090
LOCATE_ANYTHING_MAX_NEW_TOKENS=8192
```

## Docker

只启动前后端：

```bash
docker compose up -d
```

启动完整 GPU 模型栈：

```bash
docker compose --profile gpu up -d
```

GPU profile 会启动 `ocr`、`ner` 和 `visual-features`，其中视觉特征服务是 `8090` 端口的 LocateAnything。

## 架构

```text
Frontend
  |
Backend API
  |
  +-- OCR/layout pipeline: PaddleOCR-VL 1.6 + PP-StructureV3
  |       |
  |       +-- HaS Text semantic recognition
  |
  +-- Visual feature pipeline: LocateAnything-3B
          |
          +-- fixed 22 presets
          +-- user-defined visual labels
```

## 验证

```bash
python -m py_compile backend/app/core/config.py backend/app/main.py backend/scripts/ocr_server.py backend/scripts/locate_anything_server.py
npm --prefix frontend run build
```

运行时健康检查：

```bash
curl http://127.0.0.1:8000/health/services
```

期望服务只有 `paddle_ocr`、`has_ner`、`visual_features`。
