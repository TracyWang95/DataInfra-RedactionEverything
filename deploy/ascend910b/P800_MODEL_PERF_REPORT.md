# P800 昇腾模型性能测试报告

| 项 | 值 |
|---|---|
| 测试时间 | 2026-08-01 08:33:05 – 08:34:22 UTC |
| 主机 | Ascend P800 / 8×910B4，驱动 npu-smi 25.2.3 |
| 样本文件 | `172f5ac7`（`pdf_scanned`，5 页，1240×1753） |
| 启用类型 | 姓名 / 身份证 / 护照 / 电话 / 邮箱 / 地址 / 银行卡 / 机构名称 / 日期 + 公章 / 签名 |
| 数据来源 | backend、`redaction-ocr-npu`、`redaction-has-npu`、`redaction-la-npu` 容器日志 |

## 1. 结论摘要

- OCR 已切换为 NPU（官方 `paddle-npu` CANN 8.0 镜像 + `paddle-custom-npu`），Structure 单页约 **2.3–7.6s**（均值 **4.7s**），相对此前 CPU Structure ~100s/页约 **20×+** 加速。
- 端到端识别 5 页总墙钟 **76.6s**（均值 **15.3s/页**），吞吐约 **3.9 页/分钟**；合计检出敏感框 **14**。
- 当前瓶颈为 **LocateAnything**（均值 **7.5s/页**，公章+签名串行，空检时常 fast→hybrid 回退）。
- OCR+HaS 与视觉两路实际 **串行叠加**（`dual ≈ ocr_has + visual`），未真正并行吃满三卡。

## 2. 测试环境

| 服务 | 模型 | 运行时 | NPU | HBM（约） |
|---|---|---|---|---|
| HaS NER | HaS_Text_0209_0.6B | vllm-ascend | NPU0 | 25.1 / 64 GB |
| LocateAnything | LocateAnything-3B | transformers + torch_npu | NPU1 | 23.3 / 64 GB |
| PaddleOCR | PP-StructureV3 + PP-OCRv6_medium | paddle-custom-npu / CANN 8.0 | NPU2 | 6.4 / 64 GB |

健康检查：`all_online=true`，OCR `device=npu:0`。

## 3. 总体指标

| 指标 | 数值 |
|---|---|
| 识别总墙钟（5 页串行） | **76.63 s** |
| 平均每页墙钟 | **15.33 s** |
| 吞吐 | **3.91 页/分钟** |
| 检出敏感框合计 | **14**（P1:12 + P4:2） |
| OCR Structure 均值 | **4.70 s** |
| HaS NER 均值 | **2.51 s** |
| LocateAnything 均值 | **7.47 s** |
| 脱敏执行 | `bbox_count=14`，`pdf_scanned` → `output_file_id=8c26aaaf-…` |

## 4. 分阶段耗时（按页）

| 页 | 墙钟(s) | OCR(s) | struct/char(s) | OCR块 | HaS(s) | 实体 | OCR+HaS(s) | 视觉(s) | 视觉框 | 检出框 |
|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 20.20 | 5.61 | 1.64 / 3.61 | 22 | 7.06 | 10 | 13.39 | 6.74 | 1 | 12 |
| 2 | 17.05 | 7.57 | 0.96 / 6.25 | 24 | 1.39 | 0 | 9.29 | 7.70 | 0 | 0 |
| 3 | 15.00 | 5.16 | 0.96 / 3.85 | 23 | 1.37 | 0 | 7.19 | 7.75 | 0 | 0 |
| 4 | 12.31 | 2.88 | 0.72 / 1.81 | 18 | 1.38 | 0 | 4.79 | 7.46 | 2 | 2 |
| 5 | 12.07 | 2.27 | 1.02 / 0.90 | 65 | 1.35 | 0 | 4.31 | 7.70 | 0 | 0 |
| **合计/均值** | **76.63 / 15.33** | **/ 4.70** | — | **152** | **/ 2.51** | **10** | **/ 7.79** | **/ 7.47** | **3** | **14** |

对应 request_id：

| 页 | request_id |
|---|---|
| 1 | `3f06ea243963` |
| 2 | `8531318a0e37` |
| 3 | `ba47ca6acd20` |
| 4 | `374dbadb3ab0` |
| 5 | `7200a762fb0d` |

## 5. 分模型说明

### 5.1 OCR（NPU2）

- Structure 范围 2.27–7.57s；P2 char-box 偏高（6.25s），为 Structure 内部第二遍，非 CPU 回退。
- 相对 CPU 过渡方案（单页 Structure ~100–113s）约 **20×+**。
- 日志示例：`[OCR-prof] structure=…s char=…s peer=n`。

### 5.2 HaS NER（NPU0）

- 有实体页（P1）7.06s，含多轮补召回；空结果页约 1.35–1.39s。
- P1：NER 10 entities → 匹配 11 OCR 框。
- vLLM 观测（空闲采样）：prompt ~35–55 tok/s，generation ~3–9 tok/s。

### 5.3 LocateAnything（NPU1）

- 单页视觉阶段约 6.7–7.8s，占页墙钟约 **49%**。
- 空检时常 `fast-first empty → hybrid`（单类约 5.7–7.6s）。
- P1 公章 1 框；P4 公章 2 框；签名 0。

## 6. 流水线结构

- **串行叠加**：Dual pipeline 墙钟 ≈ `ocr_has + visual`（例 P1：13.39 + 6.74 ≈ 20.13 ≈ 20.16）。
- 三服务分挂 NPU0/1/2，但业务层两路未并行，三卡峰值未能同时吃满。
- 识别完成后执行脱敏：`execute_redaction`，`bbox_count=14`，相对识别耗时可忽略。

## 7. 与 CPU-OCR 过渡方案对比

| 指标 | CPU Structure（过渡） | NPU Structure（本次） | 变化 |
|---|---|---|---|
| 单页 OCR Structure | ~100–113s | ~4.7s 均值 | 约 20×+ |
| 单页端到端识别 | ~140s+（历史样例） | ~15.3s | 约 7–10× |
| 5 页文档识别 | 外推 10min+ | ~77s | 可交互 |
| OCR 服务健康 | online / cpu | online / npu:0 | ACL 500001 已修复 |

## 8. 优化建议

1. **真并行**：OCR+HaS 与 LocateAnything 并行（dual = max 而非 sum），预估单页再降约 6–8s。
2. **视觉空检**：收紧签名/公章的 fast→hybrid 回退策略，视觉均值有望降到约 2–4s。
3. **OCR char**：当前 `peer=n`；可考虑 `OCR_PEER` 分实例或降低 char 路径成本（P2 char=6.25s）。

---

*报告生成自本机实测日志；Canvas 版本见 Cursor canvas `p800-model-perf-report.canvas.tsx`。*
