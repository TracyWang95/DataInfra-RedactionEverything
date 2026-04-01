/**
 * 任务中心的状态文案面向产品语义，而不是直接暴露底层流水线名词。
 */

export type JobStatusTone = 'neutral' | 'brand' | 'warning' | 'review' | 'success' | 'danger' | 'muted';

export type JobStatusMeta = {
  label: string;
  description: string;
  tone: JobStatusTone;
};

const AGGREGATE_JOB_STATUS_META: Record<string, JobStatusMeta> = {
  draft: {
    label: '待配置',
    description: '配置阶段',
    tone: 'neutral',
  },
  queued: {
    label: '等待执行',
    description: '队列调度',
    tone: 'brand',
  },
  processing: {
    label: '处理中',
    description: '系统处理中',
    tone: 'warning',
  },
  running: {
    label: '处理中',
    description: '系统处理中',
    tone: 'warning',
  },
  awaiting_review: {
    label: '待复核',
    description: '人工介入',
    tone: 'review',
  },
  redacting: {
    label: '生成结果中',
    description: '结果生成',
    tone: 'brand',
  },
  completed: {
    label: '已完成',
    description: '结果可用',
    tone: 'success',
  },
  failed: {
    label: '处理异常',
    description: '需重试',
    tone: 'danger',
  },
  cancelled: {
    label: '已取消',
    description: '已终止',
    tone: 'muted',
  },
};

const JOB_ITEM_ONLY_META: Record<string, JobStatusMeta> = {
  pending: {
    label: '待纳入处理',
    description: '等待执行',
    tone: 'neutral',
  },
  processing: {
    label: '处理中',
    description: '识别/脱敏中',
    tone: 'warning',
  },
  parsing: {
    label: '解析版面中',
    description: '读取内容',
    tone: 'warning',
  },
  ner: {
    label: '识别实体中',
    description: '抽取实体',
    tone: 'warning',
  },
  vision: {
    label: '图像识别中',
    description: '识别图像',
    tone: 'warning',
  },
  review_approved: {
    label: '待生成结果',
    description: '等待输出',
    tone: 'review',
  },
};

function fallbackStatusMeta(status: string): JobStatusMeta {
  return {
    label: status,
    description: '状态已更新，请刷新列表查看最新进度',
    tone: 'neutral',
  };
}

export function getAggregateJobStatusMeta(status: string): JobStatusMeta {
  return AGGREGATE_JOB_STATUS_META[status] ?? fallbackStatusMeta(status);
}

export function getJobItemStatusMeta(status: string): JobStatusMeta {
  return AGGREGATE_JOB_STATUS_META[status] ?? JOB_ITEM_ONLY_META[status] ?? fallbackStatusMeta(status);
}

/** Job 行 / 详情页头部：仅聚合状态（与 Jobs、BatchHub 一致） */
export function formatAggregateJobStatus(status: string): string {
  return getAggregateJobStatusMeta(status).label;
}

/** 文件明细行：聚合状态 + 子项专有状态 */
export function formatJobItemStatus(status: string): string {
  return getJobItemStatusMeta(status).label;
}
