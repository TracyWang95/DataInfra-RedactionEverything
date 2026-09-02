# DICOM 匿名化验证与兼容性方案

本文定义 DICOM 升级的可重复验证基线。目标不是证明“能打开 `.dcm`”，而是证明从导入、风险识别、匿名化、人工复核、导出到第三方回读的整条链路，在单文件与批量检查中都保持隐私安全、对象引用关系和临床可用性。

## 1. 测试数据治理

仓库不提交任何临床 DICOM 二进制文件。公开样本由
`backend/tests/assets/dicom/manifest.json` 固定到上游 commit、字节数和 SHA-256，下载到 Git 忽略的 `cache/` 目录。人工合成样本仅使用明确的假身份，用来验证已知 PHI、烧录文字、恶意输入和失败路径。

公开语料来源：

| 来源 | 用途 | 隐私与许可处理 |
|---|---|---|
| pydicom 官方测试文件 | CT/MR/CR、大小端、显式/隐式 VR、压缩、SR、Overlay、异常文件、DICOMDIR | 上游说明图像经过缩小，并替换了看似真实的患者姓名；固定 commit 和上游许可证/第三方说明 |
| pydicom-data | Enhanced CT 多帧、功能组 | MIT；固定 commit；所选对象声明 `BurnedInAnnotation=NO` |
| GDCMData | 无前缀 CR、含 Overlay/私有标签的 DX | 上游没有顶层数据集许可证，因此只允许本地拉取，禁止进入发布包；已人工检查所选身份为 `Anonymized` 或 `Overlay Patient` 测试值 |
| 本项目合成器 | 明确的假 PHI、像素文字、嵌套序列、单次/批量、ZIP、截断和非 DICOM | 100% 合成，允许在测试期间生成；生成目录不入库 |

GDCMData 中另一个 DX JPEG 2000 文件包含看起来像真实姓名和出生日期的值，即使它在公开仓库中也不纳入语料。这是数据进入测试集前必须进行人工隐私审查的示例。

医院真实数据只能进入访问受控、非仓库位置，并至少具备：授权/伦理或数据使用依据、最小必要范围、访问审计、到期删除策略、不得进入日志/CI artifact 的技术控制。

## 2. 覆盖矩阵

| 维度 | 样本/方法 | 验证点 | 发布门禁 |
|---|---|---|---|
| CT | `CT_small`, Enhanced CT、5 实例 CT 序列 | 普通 CT、多帧功能组、批量层级、私有标签 | 可解析、可匿名化、第三方可回读；帧数与空间属性保持 |
| MR | 显式/隐式 VR、小端/大端、JPEG 2000、RLE、Overlay | 传输语法兼容、像素解码、Overlay 清理、私有元素处理 | 合法输入无静默丢失；不支持的重编码必须阻断而非降级 |
| CR | DICOMDIR 三序列、无 `DICM`/无 File Meta CR | DICOMDIR 引用、强制读取边界、CR SOP Class | 无前缀合法对象可识别；任意二进制不能因 `force=True` 被误收 |
| DX | GE 测试 DX | DX SOP Class、Overlay、私有标签、`BurnedInAnnotation=NO` | DX 元数据与像素均可处理，Overlay/private 风险进入复核 |
| 压缩 | JPEG Baseline、JPEG 2000 Lossless、RLE、Deflated | 解码插件能力、读写、传输语法记录 | 能解码才进入像素匿名化；缺少 codec 时明确失败/隔离 |
| 多帧 | RLE Secondary Capture、Enhanced CT | 帧数、维度、逐帧风险、功能组 | 所有帧均扫描；禁止只处理首帧 |
| 结构化内容 | Comprehensive SR、嵌套私有 SQ、Request Attributes | 递归序列、文本内容、私有 Creator/元素 | 递归处理，不允许只扫顶层标签 |
| 非结构化内容 | 合成烧录姓名/MRN、真实像素、Overlay | OCR/视觉检测、像素遮挡、前后预览 | 未解决高风险不得导出；修改后仍保持尺寸/位深/帧数 |
| 特殊文件 | 无前缀、缺 Transfer Syntax、非法 VR、截断像素 | 严格读取与受控回退、隔离原因、错误码 | 非法输入不能造成 500、任务卡死或部分成功被误报为成功 |
| 批量 | DICOMDIR、5 实例序列、合成 2 患者/2 Study/3 Series/4 Instance | 去重、分组、UID 映射、失败隔离、ZIP | 实例不丢不重；同一输入 UID 映射一致；跨源 UID 不碰撞 |
| 非 DICOM | 空文件、随机字节伪装 `.dcm`、ZIP 内文本 | 魔术字节、必要 UID、归档过滤 | 必须拒绝或隔离，不得仅凭扩展名接受 |

## 3. 分层测试

### L0：语料供应链

- manifest schema、样本 ID 和路径唯一。
- URL 必须是 HTTPS、指向 40 位 commit，禁止 `main/master/latest`。
- 下载后必须同时匹配字节数与 SHA-256，失败文件不得落为最终文件名。
- ZIP 解压和样本目标路径必须阻止 `..` 与绝对路径逃逸。
- 测试报告只记录标识字段“存在/不存在”，不记录值。

### L1：解析和风险扫描

- 严格读取有 File Meta 的合法对象。
- 仅在受控条件下尝试无前缀数据集；强制解析后仍必须验证 SOP Class、SOP Instance UID、核心结构，避免把随机字节误判成 DICOM。
- 遍历所有嵌套 Sequence、SR Content、私有元素、Overlay、Icon、封装文档和像素帧。
- 输出 transfer syntax、模态、多帧、颜色模型、位深和 codec 能力，不静默转换。
- `BurnedInAnnotation=NO` 不能替代像素风险策略；`YES` 必须进入 Clean Pixel/人工复核流程。

### L2：匿名化核心

- DICOM PS3.15 profile 的 X/Z/D/U/K/C/R 动作按 Tag 和条件执行。
- 写入 `PatientIdentityRemoved (0012,0062)=YES`，并写入脱敏方法文本或代码序列。
- Patient/Study/Series/SOP/Frame of Reference UID 使用租户和任务范围内的一致映射；不同原 UID 不得碰撞。
- 日期偏移对同一患者一致，纵向间隔不变；无效/部分日期有确定策略。
- 私有标签默认删除；“安全私有标签”必须经过厂商、版本、Tag、VR 和用途白名单。
- 像素修改必须逐帧执行，且正确更新 `BurnedInAnnotation`、损失压缩/派生图像等相关声明。
- 源对象不可原地覆盖；失败不得留下看似完成的半成品。

### L3：单次和批量工作流

单次：上传 → 解析 → 风险 → preflight → review → anonymize → report → export → 回读。

批量：多文件/文件夹/ZIP/DICOMDIR → 去重 → Study/Series/Instance 分组 → 局部失败隔离 → 统一 UID/日期映射 → 批量导出。

需专项验证：

- 同一文件重复上传的幂等性与去重策略。
- 同一 Study 分多批到达后的合并策略。
- 两名患者错误复用 UID 时的隔离与告警。
- ZIP 路径穿越、超大解压比、嵌套 ZIP、符号链接、文件数上限。
- 任务取消、进程重启、磁盘不足、codec 崩溃后的恢复。
- 一个坏实例不会把其他 Study 标记为匿名化成功，也不会被导出时遗漏告警。

### L4：API 契约

基础路径为 `/api/v1/dicom`，必须包含：

| 方法 | 路径 | 核心契约 |
|---|---|---|
| POST | `/ingest` | `files[]` 或 `archive` 二选一，profile 必填/有默认值；返回任务和 Study 汇总 |
| GET | `/studies` | 分页、过滤、租户隔离，不返回未授权标识值 |
| GET | `/studies/{study_id}` | Study/Series/Instance 层级与计数 |
| GET | `/studies/{study_id}/metadata` | 标签差异/风险视图；原始 PHI 权限控制 |
| GET | `/studies/{study_id}/risks` | 风险严重度、来源、状态、帧号/Tag 定位 |
| GET | `/studies/{study_id}/instances/{instance_id}/preview` | 窗宽窗位、帧索引、缓存控制、授权 |
| POST | `/studies/{study_id}/preflight` | 可导出性和阻断原因，幂等 |
| POST | `/studies/{study_id}/review` | 乐观锁/版本号，审计操作者和变更 |
| POST | `/studies/{study_id}/anonymize` | 异步任务、重复提交幂等、profile 版本固定 |
| GET | `/jobs/{job_id}` | 进度、实例成功/失败数、可重试状态 |
| GET | `/jobs/{job_id}/report` | 不泄漏原始 PHI，含规则版本、风险和验证结果 |
| GET | `/jobs/{job_id}/export` | 仅完成且无未解决高风险时可下载；安全文件名与 Content-Disposition |

API 兼容测试还应覆盖 400/401/403/404/409/413/415/422/429/5xx 映射、请求大小、分页上限、并发更新、租户越权、审计日志和 trace ID。OpenAPI 中上传必须声明 multipart，ZIP 与多文件参数不得同时悄悄取其一。

### L5：第三方兼容

每个有效输出至少由两套实现读取：平台侧 pydicom，以及独立 DCMTK `dcmdump`。医院试点再增加实际 PACS/阅片器。

- `validate_corpus.py --independent` 不保存 `dcmdump` 输出，只保存退出码、长度和诊断哈希，避免外部工具把 PHI 写入报告。
- `compare_outputs.py` 检查源/输出的临床属性、像素尺寸、帧数、UID 映射和脱敏声明。
- DICOMweb 使用 `dicomweb_probe.py` 验证 QIDO-RS、WADO-RS；STOW-RS 必须显式 `--allow-write`。
- DIMSE 使用 `dimse_probe.py` 验证 C-ECHO；C-STORE 必须显式 `--allow-write`。
- 生产接入需记录 PACS 厂商、版本、支持的 SOP Class/Transfer Syntax、最大 PDU、字符集和错误状态矩阵。

## 4. 执行命令

```powershell
# 安装/确认 Python 依赖（生产依赖由 DICOM core 统一锁定）
.venv\Scripts\python.exe -m pip install pydicom pylibjpeg pylibjpeg-libjpeg pylibjpeg-openjpeg

# 下载并验证固定公开语料
.venv\Scripts\python.exe tools\dicom_compat\fetch_samples.py

# 生成明确的假 PHI、批量和异常输入
.venv\Scripts\python.exe tools\dicom_compat\generate_synthetic_cases.py --clean

# 下载用户目录内的固定 DCMTK 3.7.0，不修改系统 PATH
.venv\Scripts\python.exe tools\dicom_compat\fetch_dcmtk.py

# 语料、像素 codec 和 DCMTK 双实现验证
.venv\Scripts\python.exe tools\dicom_compat\validate_corpus.py `
  --decode-pixels --independent --require-independent `
  --report backend\tests\assets\dicom\reports\corpus.json

# DICOM 专项 pytest
Push-Location backend
..\.venv\Scripts\python.exe -m pytest tests -k dicom -q
Pop-Location
```

平台匿名化输出生成后执行：

```powershell
.venv\Scripts\python.exe tools\dicom_compat\compare_outputs.py `
  --source <受控源目录> --output <匿名化输出目录> `
  --mapping <源输出映射.json> `
  --report backend\tests\assets\dicom\reports\roundtrip.json
```

映射文件的 `pixel_modified` 必须由实际像素处理结果生成，不能为通过测试而手工全部设为 `true`。

## 5. 发布门禁

P0（阻断发布）：

- 任何定义为 valid 的样本无法读取或输出无法由 DCMTK 回读。
- 直接标识原值未改变，或缺少 `PatientIdentityRemoved=YES`/脱敏方法。
- 同一源 UID 映射出多个目标 UID、不同源 UID 发生碰撞，或引用关系断裂。
- 私有标签、SR/嵌套文本、Overlay、像素烧录信息存在未解决高风险却允许导出。
- 帧数、Rows/Columns、空间方向、像素间距、位深发生未声明变化。
- 跨租户访问、报告/日志泄漏 PHI、源文件被覆盖。
- 批量漏实例、重复实例，或部分失败被汇总成成功。

P1（医院试点前必须关闭）：

- 目标 PACS 的 DICOMweb/DIMSE、字符集、传输语法和 SOP Class 兼容问题。
- 性能、取消/恢复、磁盘容量、超大 Study 和高并发压测未达基线。
- 医生没有完成 CT/MR/CR/DX 的关键病灶、测量、窗宽窗位和序列连续性复核。

## 6. 性能与稳定性基线

不要用单个小样本宣称性能。至少分层记录：实例数、总字节、压缩方式、帧数、像素总量、是否 OCR/视觉处理、GPU/CPU 型号、并发数。

建议场景：1 实例冒烟、100 实例普通 Study、1,000 实例大 Study、10 个并发 Study、含 100+ 帧多帧对象、ZIP 10,000 文件上限边界。指标包括 p50/p95/p99 处理时延、吞吐、峰值内存/GPU 显存、临时磁盘放大倍数、失败/重试率和取消回收时间。具体 SLA 在目标医院样本基线后冻结。

## 7. 当前验证记录

验证记录应由命令输出和 `reports/*.json` 自动产生，不手工改写成“通过”。每次发布保存：代码 commit、manifest commit、依赖锁、DCMTK 版本、机器配置、测试起止时间、通过/失败/跳过数量、失败样本 ID 和批准人。

2026-08-10 本地开发验证结果：

| 项目 | 结果 |
|---|---|
| 固定公开语料 | 28/28 下载完成，大小及 SHA-256 全部匹配；24 个合法/受控强制读取样本，4 个已知异常样本 |
| 模态与内容 | CT 7、MR 7、CR 4、DX 1，另含 OT/SR；13 个像素样本、5 个压缩样本、2 种多帧样本、DICOMDIR/批量序列 |
| pydicom | 3.0.2；合法样本读取失败 0，要求像素解码的样本失败 0 |
| 外部实现 | OFFIS DCMTK `dcmdump` 3.7.0；28 次执行，合法样本失败 0；异常样本允许被拒绝 |
| DICOM 后端专项 | `pytest tests -k dicom -q`：91 passed、0 failed、0 skipped（另有 577 个非 DICOM 测试未选中） |
| 后端全量 | `pytest tests -q`：666 passed、2 skipped；仅 3 条既有非阻塞 warning |
| 前端 | Vitest 29 passed；TypeScript + Vite production build 通过 |
| Linux 远端专项 | GPU 主机上像素写入/OCR 适配测试 11 passed |
| 远程 GPU 运行态 | GPU 6/7 的 HaS、四路 OCR、LocateAnything、LM 及三组负载均衡健康端点均为 HTTP 200；共享与隔离开发页面只显示 GPU 6/7，三类服务均为 GPU 在线 |
| Playwright 像素黄金链 | 浏览器上传合成 CT 烧录文字对象；真实 GPU 预检得到 2 区，任务 completed，validation passed，下载成功；报告 `pixel_regions_redacted=2` |
| 独立像素回读 | 输出修改 718 个像素，变化仅在片头 bbox `[13,12]-[120,44]`，第 50 行后的影像逐像素不变；帧形状/类型不变，源 SHA-256 不变 |
| 二次 OCR | 同一 GPU 流程在源图检出 2 个含假姓名/MRN 的 OCR 块；导出图 OCR 块 0、语义区域 0、敏感匹配 0 |
| DICOM 声明/外部回读 | pydicom 与 DCMTK 3.7.0 均读取成功；`PatientIdentityRemoved=YES`、`BurnedInAnnotation=NO`、方法码包含 `113100/113101` |
| 报告最小披露 | Playwright 响应确认不含源 Study/SOP UID、源/输出 SHA-256 或绝对路径，且聚合 `patient_identity_removed=true` |
| 静态检查 | DICOM core/API/tests 全部通过 Ruff；前端构建通过 |
| 机器可审计报告 | `backend/tests/assets/dicom/reports/corpus.json`；该目录不入 Git，报告不含标识字段值 |

上述结果验证的是公开去标识语料、明确合成输入、核心服务和本地 API 契约，不代表医院现场验收。

未配置 PACS/DICOMweb 测试端点时，网络兼容性必须记为“未执行”，不能记为通过。未取得医院数据授权时，医院真实数据验证同样记为“待试点”，公开去标识语料通过不等于医院全量模态已通过。
