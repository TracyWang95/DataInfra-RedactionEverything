# Legal-Redaction 项目企业级 SaaS Review 报告

> 项目：DataInfra-RedactionEverything（legal-redaction）
> 审核日期：2026-03-29
> 定位：企业级 SaaS 应用，个人端侧部署

---

## 一、产品功能层面 Review

### 1.1 核心功能完成度评估

| 功能模块 | 完成度 | 评价 |
|---------|--------|------|
| 单文件脱敏（Playground） | 90% | 核心流程完整，缺少撤销/重做 |
| 批量任务（Batch） | 85% | 流程完整，缺实时进度推送 |
| 图像隐私区域检测（YOLO 21类） | 90% | 模型能力强，类别覆盖全 |
| OCR + NER 混合识别 | 85% | 双 Pipeline 架构合理，融合策略可优化 |
| 脱敏模式（智能/掩码/自定义/结构化） | 95% | 四种模式覆盖主流场景 |
| 任务管理（Jobs） | 80% | 基本流程可用，缺少任务优先级和调度策略 |
| 处理历史（History） | 75% | 分页列表可用，缺高级筛选和统计 |
| 设置管理 | 80% | 基础配置可用，缺少导入/导出配置 |

### 1.2 产品功能缺失项（按优先级排序）

#### P0 — 上线前必须解决

1. **用户认证与权限体系缺失**
   - 当前零认证，所有 API 裸奔，任何人可访问全部文件和任务
   - 企业级 SaaS 必须具备：用户注册/登录、会话管理、角色权限（管理员/操作员/审计员）
   - 即使是个人端侧部署，也需要本地密码或 PIN 保护，防止同机其他用户访问敏感法律文档

2. **审计日志缺失**
   - 法律文档脱敏是高合规要求场景，必须记录谁在什么时间对哪个文件做了什么操作
   - 当前无任何操作日志、无变更历史、无审计追踪
   - 建议记录：文件上传/删除、脱敏执行、实体编辑、任务状态变更

3. **数据安全与隔离不足**
   - 文件元数据存于内存 dict + JSON 文件，无加密，无访问控制
   - 上传的敏感法律文档以明文保存在 `uploads/` 目录
   - 脱敏输出同样以明文保存在 `outputs/` 目录
   - 建议：静态加密（at-rest encryption）、文件访问日志、自动过期清理

4. **错误恢复与数据保护**
   - JSON 文件持久化非原子操作，Windows 下 `os.replace()` 非原子，断电可致数据丢失
   - 无自动备份机制，用户脱敏结果可能丢失
   - 建议：引入 SQLite 统一持久化、定期自动备份、操作事务化

#### P1 — 体验与竞争力

5. **缺少撤销/重做功能**
   - 用户在编辑实体和边界框时无法撤销误操作
   - 法律文档脱敏容错要求极高，误删实体后只能重新识别

6. **缺少实时任务进度推送**
   - 当前前端以 3.5 秒轮询获取任务状态，体验差且浪费资源
   - OCR 识别耗时 30-120 秒，用户长时间看不到进度
   - 建议：WebSocket 或 SSE 推送识别进度（当前文件/总文件数、当前阶段）

7. **缺少脱敏质量报告**
   - 脱敏完成后无统计报告（识别了多少实体、脱敏了多少、遗漏风险评估）
   - 企业用户需要合规报告作为审计依据
   - 建议增加：脱敏摘要报告（PDF 导出）、实体分布统计、置信度分布

8. **缺少模板/预设管理的导入导出**
   - 企业场景下需要在多台设备间同步识别预设和脱敏配置
   - 当前预设仅存于本地 JSON，无导入/导出功能

9. **缺少批量任务的优先级和调度策略**
   - 当前所有任务 FIFO 排队，无法区分紧急和常规
   - 建议支持优先级队列、并发度配置

10. **多语言支持不足**
    - 所有 UI 文案硬编码中文，无 i18n 框架
    - 企业级产品应至少支持中英双语

#### P2 — 锦上添花

11. **缺少文档对比版本管理** — 同一文件多次脱敏的版本对比
12. **缺少快捷键支持** — 高频操作（选中/取消实体、切换模式）无键盘快捷键
13. **缺少深色模式** — 长时间使用体验优化
14. **缺少使用引导** — 新用户首次使用无 Onboarding 向导
15. **缺少脱敏规则自定义正则编辑器** — 当前正则模式硬编码，用户无法自定义

---

## 二、后端 Review

### 2.1 架构设计问题

#### CRITICAL — 必须修复

1. **内存文件存储的竞态条件**
   - **位置**：`backend/app/api/files.py` 全局 `file_store` 字典
   - **问题**：全局可变字典无任何锁保护，并发请求可导致数据竞争和状态丢失
   - **影响**：多个并发上传/NER 操作可能相互覆盖，导致实体丢失
   - **建议**：引入 `asyncio.Lock()` 或迁移至数据库（SQLite/PostgreSQL）

2. **文件上传先写后验证**
   - **位置**：`backend/app/api/files.py:457-471`
   - **问题**：文件先完整读入内存并写入磁盘，再检查大小限制
   - **影响**：攻击者可反复上传大文件耗尽内存和磁盘
   - **建议**：流式读取，边读边验证大小，超限立即中断

3. **无身份认证中间件**
   - **位置**：`backend/app/main.py`
   - **问题**：所有 70+ 个 API 端点零认证，任何网络可达的人均可访问
   - **建议**：实现 JWT 认证中间件 + API Key 支持，至少支持本地密码保护

4. **文件类型仅靠扩展名判断**
   - **位置**：`backend/app/api/files.py:397-409`
   - **问题**：攻击者可伪造扩展名上传恶意文件（如 `.exe` 改为 `.pdf`）
   - **建议**：增加 magic bytes 校验（`python-magic` 库）

#### HIGH — 强烈建议修复

5. **路径遍历风险**
   - **位置**：`backend/app/api/files.py:780-785`（文件删除）
   - **问题**：删除文件时直接使用 `file_store` 中的路径，未验证是否在 `UPLOAD_DIR` 内
   - **建议**：使用 `os.path.commonpath()` 验证路径安全

6. **信息泄露 — 异常堆栈打印**
   - **位置**：`files.py:606`、`has_service.py:159`、`hybrid_vision_service.py:451`
   - **问题**：`traceback.print_exc()` 将内部路径、模块结构暴露到 stderr
   - **建议**：使用 `logging` 模块，生产环境不输出堆栈

7. **错误响应泄露内部信息**
   - **位置**：`files.py:463` 等多处
   - **问题**：`HTTPException(detail=f"文件保存失败: {str(e)}")` 将内部异常信息返回客户端
   - **建议**：返回通用错误消息，详细信息仅记日志

8. **subprocess shell=True 使用**
   - **位置**：`backend/app/main.py:238-244`
   - **问题**：GPU 检测使用 `shell=True`，存在命令注入风险
   - **建议**：使用列表形式调用，避免 `shell=True`

9. **无速率限制**
   - **问题**：所有端点无限流保护，可被 DoS 攻击
   - **建议**：集成 `slowapi` 中间件

10. **依赖版本过旧**
    - **位置**：`backend/requirements.txt`
    - **问题**：`fastapi==0.109.0`（当前 0.120+）、`Pillow==10.2.0`（有已知 CVE）、`python-jose==3.3.0`（已知安全问题）
    - **建议**：升级所有依赖至最新安全版本

#### MEDIUM — 建议修复

11. **JSON 持久化在 Windows 下非原子** — `os.replace()` 在 Windows 不保证原子性，建议 `fsync()` 后再替换
12. **无请求体大小限制** — FastAPI 未设置 `max_request_size`，大 JSON body 可致 OOM
13. **API 文档公开暴露** — `/docs` 和 `/redoc` 无需认证可访问，泄露全部 API 结构
14. **无 CSRF 保护** — 浏览器访问场景下存在跨站请求伪造风险
15. **无 HTTPS 强制** — 敏感法律文档以明文 HTTP 传输
16. **相对路径数据目录** — `DATA_DIR = "./data"` 取决于工作目录，建议使用绝对路径
17. **无孤儿文件清理** — 删除文件记录后磁盘文件残留，长期运行磁盘泄漏

### 2.2 代码质量问题

| 问题 | 位置 | 说明 |
|------|------|------|
| 宽泛的 `except Exception` | 多处 | 隐藏意外错误，应捕获具体异常 |
| `print()` 代替 `logging` | `main.py:54` 等 | 无日志级别、无结构化输出 |
| 硬编码中文错误消息 | 全部 API | 无法国际化，建议使用错误码 |
| `response_model=dict` | `jobs.py:277-383` | 失去类型安全和文档自动生成 |
| 无请求幂等性 | 所有 POST 端点 | 网络重试导致重复操作 |

---

## 三、前端 Review

### 3.1 安全问题

#### HIGH

1. **XSS 风险 — `document.write()` 使用**
   - **位置**：`frontend/src/pages/Playground.tsx:1738-1760`
   - **问题**：使用 `editorWindow.document.write()` 拼接 HTML，`fileInfo?.filename` 未转义
   - **建议**：使用 DOM API 创建元素，或对文件名进行 HTML 转义

2. **无 CSRF Token**
   - **位置**：`jobsApi.ts`、`batchPipeline.ts` 所有 POST/PUT/DELETE 请求
   - **问题**：变更操作无 CSRF 令牌保护

3. **console.log 信息泄露**
   - **位置**：`Playground.tsx:184,837`、`VisionModelSettings.tsx:87,132,147,183`、`api.ts:36`
   - **问题**：生产环境控制台输出敏感请求/响应数据
   - **建议**：条件编译或使用日志库，生产环境关闭

### 3.2 稳定性问题

#### HIGH

4. **缺少 React Error Boundary**
   - **问题**：任何组件未捕获异常将导致整个应用白屏
   - **建议**：在路由层添加 ErrorBoundary 组件

5. **fetch 后 JSON 解析无容错**
   - **位置**：`Playground.tsx:753,766,851`
   - **问题**：`await res.json()` 若返回非 JSON 内容将抛出未捕获异常
   - **建议**：统一使用带容错的 JSON 解析 helper

6. **未处理的 Promise 拒绝**
   - **位置**：`JobDetail.tsx:54-62`
   - **问题**：`void load()` 忽略了 Promise rejection，错误静默丢失
   - **建议**：添加 `.catch()` 处理

7. **组件卸载后的状态更新**
   - **位置**：`Playground.tsx:741-794`（`handleFileDrop`）
   - **问题**：多个 async 操作后 `setState`，组件可能已卸载
   - **建议**：使用 `useEffect` cleanup 或 abort controller 跟踪挂载状态

#### MEDIUM

8. **轮询未防重入**
   - **位置**：`JobDetail.tsx:54-62`（3.5s 轮询）
   - **问题**：前一个请求未返回时新请求已发出，可能请求堆积
   - **建议**：加 `isFetching` 标记防重入

9. **长操作期间 UI 未锁定**
   - **位置**：`Playground.tsx` 视觉识别（180 秒超时）
   - **问题**：用户可在识别过程中重复点击按钮触发重复操作
   - **建议**：操作进行中禁用相关按钮

10. **Toast 通知的内存泄漏**
    - **位置**：`Playground.tsx:712-727`
    - **问题**：手动创建 DOM 元素 + 嵌套 `setTimeout`，快速触发时堆积
    - **建议**：使用 React 状态管理 Toast 或第三方库（react-hot-toast）

### 3.3 性能问题

11. **Zustand Store 无选择器优化**
    - **位置**：`hooks/useRedaction.ts`
    - **问题**：所有状态在同一个 store，任意字段变更触发全量重渲染
    - **建议**：使用 selector 函数按需订阅

12. **无网络断线检测**
    - **问题**：断网时请求静默超时，用户无反馈
    - **建议**：添加 `navigator.onLine` 监听和离线提示

### 3.4 可访问性问题（Accessibility）

13. **图像编辑器缺少 ARIA 标签** — `ImageBBoxEditor.tsx:389` resize handles 无 `aria-label`
14. **文件上传区缺少键盘支持** — FileUploader 拖放区无 `role="button"` 和 keyboard handler
15. **自定义复选框缺少 aria-checked** — EntityEditor 选择框无正确的可访问性属性
16. **按钮缺少 accessible name** — 多处图标按钮无文字说明

### 3.5 部署配置问题

17. **Nginx 缺少安全头**
    - **位置**：`frontend/nginx.conf`
    - **缺失**：`Content-Security-Policy`、`X-Content-Type-Options`、`X-Frame-Options`、`Strict-Transport-Security`
    - **建议**：
      ```nginx
      add_header X-Content-Type-Options "nosniff" always;
      add_header X-Frame-Options "DENY" always;
      add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
      add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'" always;
      ```

18. **Docker 以 root 运行**
    - **位置**：`frontend/Dockerfile`
    - **问题**：无 `USER` 指令，容器内以 root 权限运行
    - **建议**：添加非 root 用户

---

## 四、接口（API）层面 Review

### 4.1 API 设计问题

#### CRITICAL

1. **错误响应格式不统一**
   - 当前状态：部分返回 `{"detail": "string"}`，部分返回 `{"detail": {"missing": [...]}}`
   - Pydantic 校验错误返回完全不同的格式
   - **建议统一为**：
     ```json
     {
       "error_code": "FILE_NOT_FOUND",
       "message": "文件不存在",
       "detail": {},
       "request_id": "uuid"
     }
     ```

2. **缺少 API 版本演进策略**
   - 当前仅 `/api/v1`，无版本迁移方案
   - 无 deprecation header 支持
   - **建议**：制定 API 生命周期策略，支持版本头协商

#### HIGH

3. **分页实现不一致**
   - `/files` 和 `/jobs` 支持分页
   - `/custom-types`、`/presets`、`/vision-types` 不支持分页
   - **建议**：所有列表端点统一支持 `page`/`page_size` 参数

4. **缺少幂等性机制**
   - 所有 POST 端点无幂等键（Idempotency-Key）支持
   - 网络重试将导致重复上传、重复创建任务
   - **建议**：关键 POST 端点支持 `X-Idempotency-Key` header

5. **任务状态机缺乏严格校验**
   - **位置**：`backend/app/api/jobs.py:304-384`
   - **问题**：状态转换未完整校验，并发请求可导致非法状态跳转
   - **建议**：实现显式状态机，拒绝非法转换
   - 合法流转：`DRAFT→QUEUED→PARSING→NER→VISION→AWAITING_REVIEW→REDACTING→COMPLETED`

6. **响应模型大量使用 `dict`**
   - **位置**：`jobs.py:277-383`、`entity_types.py`、`redaction.py:223-245`
   - **问题**：Swagger 文档不完整，前端无法自动生成类型
   - **建议**：所有端点定义明确的 Pydantic response_model

#### MEDIUM

7. **缺少缓存控制头** — 无 `ETag`/`Last-Modified`/`Cache-Control`，无并发编辑冲突检测
8. **静态文件绕过 API 安全层** — `/uploads` 和 `/outputs` mount 为 StaticFiles，不经过任何中间件
9. **超时配置不对齐** — 后端 OCR 超时 360s，前端 axios 超时 60s，前端会先超时
10. **无请求压缩** — 大实体列表和文件列表未启用 gzip/brotli 压缩
11. **缺少批量操作端点** — 无批量删除文件、批量删除任务等

### 4.2 前后端契约问题

| 问题 | 说明 |
|------|------|
| 前端假设 `error.response.data.detail` 格式 | 后端校验错误格式不同时前端崩溃 |
| 前端超时 < 后端超时 | OCR 360s vs axios 60s，前端先超时 |
| Toggle 端点返回 dict | 前端需要猜测返回结构 |
| 无 OpenAPI 生成的客户端 | 前后端类型定义手工维护，易不同步 |

### 4.3 服务间通信问题

| 问题 | 说明 |
|------|------|
| 服务地址硬编码 | 微服务 URL 写死在 config.py，不支持服务发现 |
| 无健康检查集成 | docker-compose 无 healthcheck，编排器无法感知服务存活 |
| 无重试机制 | OCR/NER/Vision 服务调用失败即终止，无指数退避重试 |
| 无熔断机制 | 某微服务宕机时请求持续堆积，影响整体性能 |

---

## 五、综合修复优先级路线图

### Phase 1 — 安全底线（上线前必须完成）

| # | 事项 | 涉及层 | 预估工作量 |
|---|------|--------|-----------|
| 1 | 实现用户认证（JWT + 本地密码） | 后端 + 前端 | 3-5 天 |
| 2 | 修复文件上传（流式验证 + magic bytes） | 后端 | 1 天 |
| 3 | 修复内存 file_store 竞态（asyncio.Lock 或迁移 SQLite） | 后端 | 2-3 天 |
| 4 | 添加审计日志 | 后端 | 2 天 |
| 5 | 统一错误响应格式 | 后端 + 前端 | 1-2 天 |
| 6 | 修复 XSS（document.write） | 前端 | 0.5 天 |
| 7 | 添加 React Error Boundary | 前端 | 0.5 天 |
| 8 | Nginx 安全头 | 前端部署 | 0.5 天 |
| 9 | 去除生产环境 console.log | 前端 | 0.5 天 |
| 10 | 禁用生产环境 `/docs`、`/redoc` | 后端 | 0.5 天 |

### Phase 2 — 稳定性与体验（上线后 1 个月内）

| # | 事项 | 涉及层 |
|---|------|--------|
| 11 | WebSocket/SSE 实时任务进度 | 后端 + 前端 |
| 12 | 请求幂等性 | 后端 + 前端 |
| 13 | 速率限制 | 后端 |
| 14 | 前端超时与后端对齐 | 前端 |
| 15 | 添加操作撤销/重做 | 前端 |
| 16 | 脱敏质量报告 | 后端 + 前端 |
| 17 | 依赖版本升级 | 后端 + 前端 |
| 18 | 所有 response_model 类型化 | 后端 |

### Phase 3 — 企业级完善（上线后 3 个月内）

| # | 事项 | 涉及层 |
|---|------|--------|
| 19 | RBAC 权限体系 | 后端 + 前端 |
| 20 | HTTPS 强制 + HSTS | 部署 |
| 21 | 结构化日志 + 监控指标 | 后端 |
| 22 | 服务发现 + 熔断 + 重试 | 后端 |
| 23 | 多语言 i18n | 前端 |
| 24 | 可访问性 (a11y) | 前端 |
| 25 | OpenAPI 自动生成前端 Client | 工具链 |
| 26 | 配置导入/导出 | 后端 + 前端 |

---

## 六、总结

### 优势

- **架构设计合理**：双 Pipeline 混合检测（OCR+NER+YOLO）是业界先进方案
- **完全离线**：所有模型本地运行，满足数据安全的刚性需求
- **合规标准**：基于 GB/T 37964-2019，实体类型覆盖全面（77+类）
- **脱敏模式丰富**：四种模式覆盖主流法律场景
- **前端交互完整**：实体编辑、图像标注、前后对比等核心交互均已实现

### 核心风险

- **安全性不达标**：零认证、零审计、零加密，法律文档处理场景不可接受
- **数据可靠性不足**：内存 dict + JSON 持久化，断电可致数据丢失
- **可观测性缺失**：无结构化日志、无监控指标、无告警机制
- **前端健壮性不足**：无 Error Boundary、fetch 无容错、无离线处理

### 一句话结论

> 产品功能和 AI 能力已达到可用水平，但安全性、数据可靠性和运维可观测性距离企业级 SaaS 标准仍有显著差距。建议优先完成 Phase 1 安全底线修复后再面向用户部署。
