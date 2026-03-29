export const zh: Record<string, string> = {
  // Navigation
  'nav.playground': 'Playground',
  'nav.batch': '批量任务',
  'nav.batch.sub': '新建或继续向导',
  'nav.history': '处理历史',
  'nav.jobs': '任务中心',
  'nav.jobs.sub': '文本/图像批量队列',
  'nav.redactionList': '脱敏清单',
  'nav.redactionList.sub': '命名预设与选用',
  'nav.recognitionSettings': '识别项配置',
  'nav.recognitionSettings.sub': '文本 / 图像识别规则',
  'nav.modelConfig': '模型配置',
  'nav.textModel': '文本模型配置',
  'nav.visionModel': '视觉服务配置',

  // Playground
  'playground.title': '智能脱敏工作台',
  'playground.upload.hint': '拖拽或点击上传文件',
  'playground.upload.formats': '支持 Word、PDF、图片文件',
  'playground.recognize': '开始识别',
  'playground.recognizing': '正在识别...',
  'playground.redact': '执行脱敏',
  'playground.redacting': '正在脱敏...',
  'playground.reupload': '重新上传',
  'playground.undo': '撤销',
  'playground.redo': '重做',
  'playground.selectAll': '全选',
  'playground.deselectAll': '取消全选',
  'playground.entities': '识别实体',
  'playground.boundingBoxes': '检测区域',

  // Common
  'common.confirm': '确认',
  'common.cancel': '取消',
  'common.delete': '删除',
  'common.save': '保存',
  'common.export': '导出',
  'common.import': '导入',
  'common.loading': '加载中...',
  'common.noData': '暂无数据',
  'common.success': '操作成功',
  'common.error': '操作失败',
  'common.retry': '重试',

  // File types
  'file.word': 'Word 文档',
  'file.pdf': 'PDF 文档',
  'file.image': '图片',

  // Entity types
  'entity.PERSON': '姓名',
  'entity.ID_CARD': '身份证号',
  'entity.PHONE': '电话号码',
  'entity.ADDRESS': '地址',
  'entity.ORG': '机构名称',
  'entity.BANK_CARD': '银行卡号',
  'entity.CASE_NUMBER': '案件编号',
  'entity.DATE': '日期',
  'entity.AMOUNT': '金额',

  // Replacement modes
  'mode.smart': '智能替换',
  'mode.mask': '掩码替换',
  'mode.custom': '自定义替换',
  'mode.structured': '结构化标签',

  // Jobs
  'job.status.draft': '草稿',
  'job.status.queued': '排队中',
  'job.status.running': '运行中',
  'job.status.awaiting_review': '待审核',
  'job.status.redacting': '脱敏中',
  'job.status.completed': '已完成',
  'job.status.failed': '失败',
  'job.status.cancelled': '已取消',

  // Settings
  'settings.title': '系统设置',
  'settings.presets': '预设管理',
  'settings.presets.export': '导出预设',
  'settings.presets.import': '导入预设',

  // Report
  'report.title': '脱敏质量报告',
  'report.totalEntities': '识别实体总数',
  'report.redactedEntities': '已脱敏数',
  'report.coverage': '覆盖率',
  'report.typeDistribution': '类型分布',
  'report.confidenceDistribution': '置信度分布',
  'report.high': '高',
  'report.medium': '中',
  'report.low': '低',

  // Health
  'health.title': '服务状态',
  'health.allOnline': '全部服务正常',
  'health.someOffline': '部分服务异常',
  'health.backendDown': '后端未连接',
  'health.checking': '检测服务中...',
  'health.detecting': '检测中...',
  'health.online': '在线',
  'health.offline': '离线',
  'health.backendProbe': '后端探测',
  'health.frontendRoundTrip': '前端往返',
  'health.gpuMemory': 'GPU 显存',
  'health.gpuNotDetected': '未检测',
  'health.probeTime': '探测时间',
  'health.refreshTitle': '立即刷新服务状态',

  // Offline
  'offline.banner': '网络连接已断开，部分功能可能不可用',

  // Onboarding
  'onboarding.skip': '跳过引导',
  'onboarding.prev': '上一步',
  'onboarding.next': '下一步',
  'onboarding.start': '开始使用',

  // Page headers
  'page.batch.title': '批量任务',
  'page.batch.sub': '选择类型并创建工单',
  'page.batchText.title': '批量处理',
  'page.batchText.sub': '纯文本 / 可选中文字的 PDF',
  'page.batchImage.title': '批量处理',
  'page.batchImage.sub': '图片类文本',
  'page.batchSmart.title': '智能批量',
  'page.batchSmart.sub': '混合文件自动识别',
  'page.redactionList.title': '脱敏清单配置',
  'page.redactionList.sub': '命名预设与选用，同步 Playground / 批量向导',
  'page.recognitionSettings.title': '识别项配置',
  'page.recognitionSettings.sub': '敏感信息类型、正则与语义规则',
  'page.jobDetail.title': '任务详情',
  'page.jobDetail.sub': '队列进度 · 进入编辑 · 逐份确认',
  'page.jobs.title': '任务中心',
  'page.jobs.sub': '文本批量 / 图像批量 · 队列与审阅',
  'page.history.title': '处理历史',
  'page.history.sub': '已上传文件 · 分页 · 批量 ZIP',
  'page.textModel.title': '文本模型配置',
  'page.textModel.sub': '文本 NER · HaS（llama-server）',
  'page.visionModel.title': '视觉服务配置',
  'page.visionModel.sub': 'HaS Image · PaddleOCR-VL 登记与检测',

  // Sidebar
  'sidebar.subtitle': '匿名化数据基础设施',
  'sidebar.devInProgress': '开发中',
};
