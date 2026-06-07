# 视觉链路重构总结

日期：2026-06-05

## 目标

当前视觉链路目标收敛为：

- 主语义链路：PaddleOCR-VL 1.6 + HaS Text
- 视觉特征链路：LocateAnything 负责全图视觉特征定位
- 移除 Structure 默认链路：PP-StructureV3 不再参与默认推理、预热和服务状态展示
- 前后端概念统一：原 YOLO、VLM、自定义视觉清单统一收敛为“视觉特征”

目标工程形态：

1. 文件只渲染/读取一次，形成统一 `ImageFrame`。
2. OCR-VL 输出文本块和 PaddleOCR-VL 视觉能力结果，例如印章。
3. HaS Text 只基于 OCR 文本块做语义实体判断，再回填 OCR 坐标。
4. LocateAnything 接收全图和选中的视觉特征标签，一次请求完成视觉特征定位。
5. 后处理层统一做坐标标准化、去重、来源优先级、置信度和状态上报。

## 当前服务拓扑

测试时算法服务均运行在 WSL 内，Windows 侧 `127.0.0.1` 偶发端口转发不稳定，WSL IP 直连稳定。

| 服务 | 端口 | 作用 | 状态 |
| --- | ---: | --- | --- |
| PaddleOCR-VL vLLM | 8118 | PaddleOCR-VL 1.6 模型服务 | 在线 |
| OCR wrapper | 8082 | `/ocr` 封装 OCR-VL | 在线 |
| HaS Text vLLM | 8080 | HaS 语义模型 | 在线 |
| LocateAnything | 8090 | 视觉特征定位 | 在线 |
| Backend | 8000 | 后端 API | 在线 |
| Frontend | 3000 | 前端 UI | 在线 |

注意：测试时 OCR wrapper `/health` 仍显示 `PaddleOCR-VL-1.6-0.9B + PP-StructureV3` 和 `structure_ready=true`，因为该进程是在关闭 Structure 配置前启动的。若要完全验证 Structure 移除，需要重启 OCR wrapper，并确认 health 不再暴露 Structure 状态。

## 已发生的配置变更

中断前已经写入以下配置改动，需要后续继续保留或按测试结论调整：

- `backend/app/core/config.py`
  - `VISION_DUAL_PIPELINE_PARALLEL=true`
  - `VISUAL_FEATURES_SIGNATURE_OCR_FAST_PATH=false`
  - `VISUAL_FEATURES_SIGNATURE_SKIP_WHEN_OCR_ANCHOR_FOUND=false`
- `.env`
  - `VISION_DUAL_PIPELINE_PARALLEL=true`
  - `OCR_STRUCTURE_ENABLED=false`
  - `OCR_STRUCTURE_WARMUP=0`
  - `VISUAL_FEATURES_SIGNATURE_OCR_FAST_PATH=false`
  - `VISUAL_FEATURES_SIGNATURE_SKIP_WHEN_OCR_ANCHOR_FOUND=false`
- `backend/.env`
  - 同步了并行和签字跳过逻辑开关

这些改动的意图是：不要因为 OCR 命中签字锚点就跳过 LocateAnything，确保 LocateAnything 仍参与视觉特征链路。

## 核心样例测试结论

样例：

- `D:\1.tiff`
- `D:\2.tiff`
- `D:\4.tiff`

### LocateAnything 单独推理

测试配置：

- 类别：`signature`
- 全图输入
- `max_image_side=1280`
- `max_new_tokens=8192`
- 对比 `fast`、`hybrid`、`fast_first`

| 文件 | 模式 | 耗时 | 签字框数 | 结论 |
| --- | --- | ---: | ---: | --- |
| `1.tiff` | fast | 7.795s | 0 | 漏检 |
| `1.tiff` | hybrid | 5.008s | 1 | 最好 |
| `1.tiff` | fast_first | 6.954s | 1 | 可用但比 hybrid 慢 |
| `2.tiff` | fast | 2.186s | 2 | 可用 |
| `2.tiff` | hybrid | 2.181s | 2 | 可用 |
| `2.tiff` | fast_first | 2.208s | 2 | 可用 |
| `4.tiff` | fast | 7.023s | 0 | 漏检 |
| `4.tiff` | hybrid | 4.972s | 0 | 漏检 |
| `4.tiff` | fast_first | 7.099s | 0 | 漏检 |

结论：

- `hybrid` 对当前签字任务并不慢，且 `1.tiff` 比 `fast_first` 更快。
- `fast` 会漏掉 `1.tiff` 签字，不适合作为唯一模式。
- `4.tiff` LocateAnything 签字漏检，需要继续调提示词、目标类别描述或引入 OCR-VL 签字锚点补充。

### OCR-VL 单独推理

| 文件 | 耗时 | OCR 块数 |
| --- | ---: | ---: |
| `1.tiff` | 4.932s | 25 |
| `2.tiff` | 3.545s | 8 |
| `4.tiff` | 14.209s | 3 |

结论：

- `1.tiff` 和 `2.tiff` OCR-VL 很快。
- `4.tiff` OCR-VL 输出大表格块，耗时约 14s，是该图主要耗时来源。
- PP-Structure 不参与时，PaddleOCR-VL 已能识别表格型内容，但有些坐标会是大块或虚拟表格单元，需要后处理细化。

### OCR-VL + HaS Text 语义链路

测试类型：

- 姓名
- 日期
- 年龄
- 婚姻状态
- 组织机构
- 健康信息
- 病历信息

| 文件 | 总耗时 | OCR-VL | HaS Text | 输出区域 |
| --- | ---: | ---: | ---: | ---: |
| `1.tiff` | 4.946s | 3.908s | 0.968s | 10 |
| `2.tiff` | 4.100s | 3.171s | 0.915s | 6 |
| `4.tiff` | 15.307s | 14.492s | 0.784s | 8 |

结论：

- HaS Text 热模型后通常低于 1s，不是主要瓶颈。
- `4.tiff` 的慢主要来自 OCR-VL 对整页表格/长文本块处理。
- `4.tiff` 的语义框来自 `table_cell_match`，高度较大，需要视觉检查是否过粗。

### OCR-VL 和 LocateAnything 并发推理

同一张图同时请求 OCR-VL `/ocr` 和 LocateAnything `/detect`，结果如下：

| 文件 | 并发总耗时 | OCR-VL 耗时 | Locate 耗时 | 结论 |
| --- | ---: | ---: | ---: | --- |
| `1.tiff` | 54.329s | 44.424s | 54.324s | 并发明显变慢 |
| `2.tiff` | 22.009s | 22.007s | 18.229s | 并发明显变慢 |
| `4.tiff` | 42.288s | 42.287s | 34.133s | 并发明显变慢 |

结论：

- 在单张 16GB 4090 Laptop GPU 上，OCR-VL 和 LocateAnything 真正同时跑会互相抢 GPU，尾延迟大幅上升。
- 算法上不能简单把 OCR-VL 和 LocateAnything GPU 推理完全并行。
- 更合理的工程策略是“逻辑并行、GPU 推理闸门串行”：请求层可以并发调度，但进入 GPU 模型的重活要通过单 GPU 调度器控制，避免两个大 VLM 同时吃显存和算力。

## 当前算法判断

### 1. OCR-VL + HaS 是主链路

PaddleOCR-VL 1.6 已经能覆盖大多数文本、表格和印章能力。HaS Text 的增量耗时较小，适合作为语义判断主链路。

推荐：

- 默认启用 OCR-VL + HaS。
- HaS 给足类型 budget，但对页面文本做 compact 和 block 去重，避免长表格拖慢。
- 印章归 OCR-VL 能力处理，不交给 LocateAnything。

### 2. LocateAnything 是视觉特征补充链路

LocateAnything 适合处理签字、纸张、二维码、证件、人脸等视觉目标，但目前签字仍不稳定：

- `1.tiff`：`hybrid` 能命中。
- `2.tiff`：三种模式都能命中两个签字。
- `4.tiff`：三种模式都漏检。

推荐：

- 默认签字使用 `hybrid`，不是 `fast_first`。
- `fast` 只适合简单图，不适合作为默认签字模式。
- 对签字继续测试提示词，例如：
  - `actual visible handwritten signatures or handwritten signer names`
  - `handwritten doctor signatures near signature labels`
  - `all handwritten signer names or signatures on the form`
- 对固定标签和用户新增标签，LocateAnything 应一次接收全图和标签列表。

### 3. PP-StructureV3 应从默认链路删除

现阶段建议：

- 默认不启动 PP-StructureV3。
- 默认不预热 PP-StructureV3。
- 前端本地服务状态不再展示 PP-StructureV3。
- 后端 pipeline 描述不再写 PP-StructureV3。
- OCR wrapper 需要重启以释放已加载的 Structure 状态。

保留代码时也应置于明确的 opt-in/debug 分支，不能进入默认运行链路。

## 推荐的目标 Pipeline

```text
Input file/page
  -> render/read image once
  -> ImageFrame(width, height, bytes, page)

Branch A: OCR semantic path
  -> PaddleOCR-VL /ocr
  -> OCRTextBlock[]
  -> OCR visual regions from PaddleOCR-VL, especially SEAL
  -> HaS Text semantic NER
  -> Entity-to-OCR coordinate resolver
  -> semantic regions

Branch B: visual feature path
  -> LocateAnything /detect
  -> full image + selected visual labels
  -> visual feature regions

Fusion
  -> normalize type ids
  -> source priority
  -> IoU / containment dedupe
  -> confidence and reason
  -> UI review regions
```

源优先级建议：

1. PaddleOCR-VL visual region for `SEAL`
2. LocateAnything for non-text visual features such as `SIGNATURE`, `PAPER`, `QR_CODE`
3. OCR-VL + HaS for semantic text regions
4. Local heuristic supplements only作为兜底，不作为主规则

## 性能建议

基于样例结果，不建议默认让 OCR-VL 和 LocateAnything GPU 推理同时执行。

建议策略：

- 单文件单页内：GPU 重活串行，减少尾延迟。
- 多文件批量：用队列控制 GPU 并发为 1，CPU 后处理可以并行。
- OCR-VL 和 HaS 可以串行，因为 HaS 热模型约 1s。
- LocateAnything 签字默认 `hybrid`，`max_image_side=1280`。
- LocateAnything `max_new_tokens=8192` 保持不变。
- 对 `4.tiff` 这类大表格页，优先优化 OCR-VL 输出块拆分和坐标回填，而不是增加 Locate 并发。

预估稳定耗时：

- `1.tiff`：OCR+HaS 约 5s + Locate hybrid 约 5s，串行约 10s。
- `2.tiff`：OCR+HaS 约 4s + Locate hybrid 约 2s，串行约 6s。
- `4.tiff`：OCR+HaS 约 15s + Locate hybrid 约 5s，串行约 20s。

如果强行并发，当前实测分别变成 54s、22s、42s，不适合默认。

## 主要风险点

1. `4.tiff` LocateAnything 签字漏检。
2. PaddleOCR-VL 对表格页可能返回大块 HTML/table，坐标细分依赖后处理。
3. 当前 OCR wrapper 进程仍然加载了 PP-StructureV3，需要重启后确认真正移除。
4. Windows `127.0.0.1` 到 WSL 的算法端口转发偶发拒绝，后端应优先使用 WSL IP 或稳定代理。
5. 真并发会导致共享 GPU 争用，不能只看显存剩余量判断并发能力。

## 下一步工程任务

先稳定算法，再做程序重构，建议顺序：

1. 重启 OCR wrapper，确认 PP-StructureV3 不加载、不预热、不显示。
2. 继续跑 `D:\ceshi` 下图片样例，记录 OCR+HaS、Locate、融合后的框。
3. 对 `4.tiff` 签字漏检单独调 LocateAnything prompt 和模式。
4. 对 PaddleOCR-VL 大表格块做通用坐标细化方案，避免过粗框。
5. 建立 `VisionPipeline` 新结构：
   - `ImageFrame`
   - `OcrSemanticStage`
   - `VisualFeatureStage`
   - `RegionFusionStage`
   - `PipelineTelemetry`
6. 前端统一 UI：
   - “图像文字识别”改为 OCR-VL + HaS
   - “视觉特征”统一包含固定 22 类和用户新增标签
   - 本地服务状态不再显示 Structure
7. 再做 Playwright 全流程检查。

## 当前建议结论

稳定版本建议先采用：

- OCR-VL + HaS：默认主链路
- LocateAnything：默认签字用 `hybrid`，全图 + 标签列表
- PP-StructureV3：默认完全关闭
- GPU 推理：不要真并发，采用单 GPU 调度器串行重活
- 融合：OCR-VL 负责印章，LocateAnything 负责签字等视觉特征，HaS 负责语义文本

