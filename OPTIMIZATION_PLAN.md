# Legal-Redaction 最终优化方案

> 适用场景：本地 4090 单机部署，聚焦可维护性，不增加复杂度
> 基于：全面代码审查 + 74 项 E2E 测试基线 + 5 项手动测试痛点

---

## 一、已完成的修复（3 commits，保留）

| # | 内容 | Commit |
|---|------|--------|
| ✅ | E2E 测试套件 74 项（含全链路 5 步 + GPU 显存监控） | `5700398` |
| ✅ | Step3 只保留后台队列模式，去掉本地识别 | `09ac3f6` |
| ✅ | 任务队列加固：去重、失败兜底、取消检测、状态聚合 | `09ac3f6` + `737a4ba` |
| ✅ | 审阅逐份锁定：确认脱敏后才能下一张 | `09ac3f6` |
| ✅ | 精简按钮：去掉"返回识别"，全部完成才能进入审核 | `09ac3f6` |
| ✅ | 图片类型检测修复（is_scanned PDF） | `09ac3f6` |

---

## 二、Codex Review 发现的回归 Bug（必修）

> 以下 5 项由 Codex (GPT-5.4) 审核 uncommitted diff 时发现，均为之前 39-fix overhaul 引入的功能回归。

#### CR-1. [P1] JSON→SQLite 迁移丢失历史文件
- **文件**: `backend/app/api/files.py:229-231`
- **问题**: 迁移时用原始相对路径 `./uploads/...` 检查文件是否存在，在不同工作目录下启动时路径不匹配，导致历史上传记录被跳过不迁移
- **修复**: 在存在性检查前先调用 `_repair_file_store_paths()` 或用 `os.path.realpath()` 规范化路径

#### CR-2. [P1] skip_item_review 任务卡在 awaiting_review
- **文件**: `backend/app/services/task_queue.py:212-214`
- **问题**: `_run_recognition` 完成后统一设为 `awaiting_review`，但 `skip_item_review=true` 的任务应该直接进入脱敏，现在无人审批导致任务永远卡住
- **修复**: 识别完成后检查 job 的 `skip_item_review` 配置，若为 true 则直接入队 redaction 任务

#### CR-3. [P1] 重启恢复入队逻辑错误
- **文件**: `backend/app/main.py:146-157`
- **问题**: 启动恢复只入队 `pending/processing/queued/parsing/ner/vision` 状态且全部当作 `recognition` 任务。`review_approved` 状态的 item 不会被恢复（脱敏丢失），已在脱敏中的 item 被错误重跑识别
- **修复**: 区分 task_type — `review_approved` 应入队为 `redaction`，已完成识别的不重跑

#### CR-4. [P2] requeue-failed 状态转换失败
- **文件**: `backend/app/api/jobs.py:472-474`
- **问题**: 用 `QUEUED` 状态重排队，但状态机只允许 `FAILED→PENDING`，导致 `InvalidStatusTransition` 异常
- **修复**: 改为 `update_item_status(..., JobItemStatus.PENDING)`

#### CR-5. [P2] 文件上传 job 注册 400 错误被吞为 500
- **文件**: `backend/app/api/files.py:690-699`
- **问题**: `_register_file_with_job()` 抛出的 400（job 不存在/非 draft）被外层 `except Exception` 捕获后转为 500
- **修复**: 在 except 中先 `isinstance(e, HTTPException)` 检查，若是则直接 re-raise

---

## 三、待实施优化项

### P0 — 快速修复（每项 < 30 分钟，低风险）

#### P0-1. 微服务 CORS 限制
- **文件**: `backend/ocr_server.py:31`, `backend/has_image_server.py:36`
- **现状**: `allow_origins=["*"]`
- **改为**: `allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"]`
- **改动量**: 2 行

#### P0-2. 添加 404 路由
- **文件**: `frontend/src/router.tsx`
- **现状**: 无效 URL 显示空白页
- **改为**: 添加 `path: '*'` 通配路由，显示 404 页面
- **改动量**: 1 个新组件 + router 1 行

#### P0-3. OnboardingGuide 国际化
- **文件**: `frontend/src/components/OnboardingGuide.tsx`
- **现状**: 5 步引导内容硬编码中文
- **改为**: 使用 `t()` 调用，已有 i18n key（onboarding.skip/prev/next/start）
- **改动量**: ~20 行

#### P0-4. OnboardingGuide 键盘可访问性
- **文件**: `frontend/src/components/OnboardingGuide.tsx`
- **现状**: 无焦点陷阱、无 Escape 关闭、无 role="dialog"
- **改为**: 添加 `role="dialog"` + `aria-modal="true"` + Escape 监听
- **改动量**: ~15 行

#### P0-5. 清理 console.log 残留
- **文件**: `frontend/src/pages/Playground.tsx` 约 650、958 行
- **改动量**: 删除 3-5 行

---

### P1 — 可维护性改善（每项 1-2 小时）

#### P1-1. 拆分 Batch.tsx（当前 3,639 行）
- **目标**: 每文件 < 800 行
- **拆分方案**:
  - `hooks/useBatchWizardState.ts` — 提取 wizard 状态管理（cfg, rows, step, furthestStep）
  - `hooks/useBatchRecognition.ts` — 提取识别/轮询逻辑（submitQueueToWorker, polling）
  - `hooks/useBatchReview.ts` — 提取审阅状态（reviewIndex, reviewBoxes, reviewEntities, undo/redo）
  - `batch/BatchStep4ImageReview.tsx` — 图像审阅 UI
  - `batch/BatchStep4TextReview.tsx` — 文本审阅 UI
  - `batch/BatchStep5Export.tsx` — 导出 UI
- **注意**: 纯重构，不改功能，每拆一块跑 E2E 验证

#### P1-2. 拆分 Playground.tsx（当前 1,592 行）
- **目标**: < 800 行
- **拆分方案**:
  - `hooks/usePlaygroundRecognition.ts` — 提取上传+识别逻辑
  - 已有拆分（PlaygroundUpload, PlaygroundResult, PlaygroundToolbar, PlaygroundEntityPanel）继续用
- **注意**: Playground 已经拆出了不少子组件，主要提取 hooks

#### P1-3. 提取魔法数字为常量
- **前端**: 创建 `frontend/src/constants/`
  - `timeouts.ts`: VISION_TIMEOUT_MS=400000, FETCH_TIMEOUT_MS=25000, POLL_INTERVAL_MS=3000
  - `colors.ts`: 实体类型颜色映射
- **后端**: 创建 `backend/app/constants/`
  - `thresholds.py`: FUZZY_MATCH_THRESHOLD=0.85, IOU_THRESHOLD=0.3, MIN_BBOX_WIDTH=20
  - `entity_formats.py`: PHONE_DIGIT_COUNT=11, ID_CARD_DIGIT_COUNT=18

#### P1-4. 消除 `any` 类型
- **文件**: `PlaygroundResult.tsx`（6 处）、`router.tsx`（1 处）、`batchPipeline.ts`（1 处）
- **改为**: 定义具体类型接口
- **改动量**: 9 处，新增 2 个 interface

---

### P2 — 后端代码质量（每项 2-4 小时）

#### P2-1. 重构 `_match_entities_to_ocr()`
- **文件**: `backend/app/services/hybrid_vision_service.py` 493-636 行
- **现状**: 144 行、7+ 层嵌套
- **拆为**:
  - `_find_exact_match()` — 精确字符串匹配
  - `_find_fuzzy_match()` — SequenceMatcher 模糊匹配
  - `_find_in_table_fallback()` — HTML 表格回退

#### P2-2. 重构 `_replace_in_paragraph()`
- **文件**: `backend/app/services/redactor.py` 416-533 行
- **现状**: 118 行、5+ 层嵌套
- **拆为**:
  - `_map_char_positions()` — 字符到 run 的位置映射
  - `_apply_replacement()` — 执行替换

#### P2-3. 细化异常处理
- **文件**: `backend/app/services/hybrid_vision_service.py`（5 处裸 `except Exception`）
- **改为**: `except (OCRServiceError, TimeoutError, ValueError)` 等具体类型
- **保留**: 最外层 catch-all 但加 `logger.exception()` 完整栈

#### P2-4. 去重类型映射
- **现状**: 类型名→枚举的映射字典在 3 处重复（_match_entities_to_ocr / _run_has_text / 颜色映射）
- **改为**: 抽到 `backend/app/models/type_config.py`，统一引用

---

### P3 — 测试补充（持续，按需）

#### P3-1. 后端单元测试
- `hybrid_vision_service.py` 核心函数测试（_match_entities_to_ocr, _run_has_text_analysis）
- `redactor.py` 各脱敏模式测试（smart/mask/structured）

#### P3-2. 前端组件测试
- ImageBBoxEditor 交互测试
- useRedaction store 边界测试

---

## 四、不做的项（本地 4090 不需要）

| 项目 | 不做原因 |
|------|----------|
| CSRF 保护 | 本地单用户，无跨站风险 |
| Rate Limit X-Forwarded-For | 不经过反向代理 |
| JWT 密钥 DPAPI/ACL | 本地，hidden 足够 |
| 验证错误按 DEBUG 隐藏 | 本地工具，无安全风险 |
| WCAG 无障碍审计 | 个人工具 |
| Celery + Redis | 已有 asyncio 队列，单机够用 |

---

## 五、实施顺序

```
Phase 0 (半天)  CR-1 ~ CR-5   Codex 发现的回归 Bug（最高优先级）
Phase 1 (1天)   P0-1 ~ P0-5   快速修复 5 项
Phase 2 (2-3天) P1-1           拆分 Batch.tsx（最大改动）
Phase 3 (1天)   P1-2 ~ P1-4   拆分 Playground + 常量 + 类型
Phase 4 (2天)   P2-1 ~ P2-4   后端重构
Phase 5 (持续)  P3-1 ~ P3-2   补测试
```

每个 Phase 完成后跑 `npm run test:e2e` 验证不回归。

---

## 六、E2E 测试安全网

| 测试文件 | 覆盖 | 数量 |
|----------|------|------|
| api-health.spec.ts | 后端 10 个 API 端点 | 10 |
| navigation.spec.ts | 侧边栏 8 链接 + 暗色模式 + 响应式 | 14 |
| playground.spec.ts | 单文件上传→识别→脱敏完整流程 | 7 |
| batch-smoke.spec.ts | BatchHub 基本功能 | 7 |
| batch.spec.ts | 批量任务创建 + API | 7 |
| batch-fullchain.spec.ts | **全链路 5 步（真实 3 文件）** | 1 |
| batch-workflow.spec.ts | 多任务排队 + GPU 显存 | 5 |
| history.spec.ts | 处理历史 | 6 |
| jobs.spec.ts | 任务中心 | 8 |
| settings.spec.ts | 识别项 + 脱敏清单 | 7 |
| model-settings.spec.ts | 文本/视觉模型配置 | 4 |
| **合计** | | **76** |

运行命令：
```bash
cd frontend && PLAYWRIGHT_SKIP_WEBSERVER=1 npm run test:e2e
```
