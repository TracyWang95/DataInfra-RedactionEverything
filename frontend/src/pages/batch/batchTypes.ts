import type { FileListItem } from '../../types';
import type { BatchWizardPersistedConfig, BatchWizardMode } from '../../services/batchPipeline';
import type { RecognitionPreset } from '../../services/presetsApi';

export type Step = 1 | 2 | 3 | 4 | 5;

export interface PipelineCfg {
  mode: 'ocr_has' | 'has_image';
  name: string;
  description: string;
  enabled: boolean;
  types: { id: string; name: string; color: string; enabled: boolean }[];
}

export interface TextEntityType {
  id: string;
  name: string;
  color: string;
  regex_pattern?: string | null;
  use_llm?: boolean;
}

export interface BatchRow extends FileListItem {
  analyzeStatus: 'pending' | 'parsing' | 'analyzing' | 'awaiting_review' | 'review_approved' | 'redacting' | 'completed' | 'failed';
  analyzeError?: string;
  isImageMode?: boolean;
  reviewConfirmed?: boolean;
}

export const ANALYZE_STATUS_LABEL: Record<BatchRow['analyzeStatus'], string> = {
  pending: '等待中',
  parsing: '解析中',
  analyzing: '识别中',
  awaiting_review: '待审阅',
  review_approved: '待脱敏',
  redacting: '脱敏中',
  completed: '已完成',
  failed: '失败',
};

/** 识别已完成、可进入审阅/已审阅的状态集合 */
export const RECOGNITION_DONE_STATUSES: ReadonlySet<BatchRow['analyzeStatus']> = new Set([
  'awaiting_review', 'review_approved', 'redacting', 'completed',
]);

export const STEPS: { n: Step; label: string }[] = [
  { n: 1, label: '任务与配置' },
  { n: 2, label: '上传' },
  { n: 3, label: '批量识别' },
  { n: 4, label: '审阅确认' },
  { n: 5, label: '导出' },
];

export type { BatchWizardPersistedConfig, BatchWizardMode, RecognitionPreset };
