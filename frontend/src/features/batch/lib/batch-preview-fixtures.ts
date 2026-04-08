// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type { BoundingBox as EditorBox } from '@/components/ImageBBoxEditor';
import type { RecognitionPreset } from '@/services/presetsApi';
import type { BatchWizardPersistedConfig, BatchWizardMode } from '@/services/batchPipeline';
import { FileType } from '@/types';
import type { BatchRow, PipelineCfg, ReviewEntity, Step, TextEntityType } from '../types';

export const PREVIEW_BATCH_JOB_ID = 'preview-smart-batch';

const previewNow = '2026-04-05T18:10:00+08:00';

const previewImageSvg = encodeURIComponent(`
  <svg xmlns="http://www.w3.org/2000/svg" width="1200" height="900" viewBox="0 0 1200 900">
    <defs>
      <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="#f8fafc" />
        <stop offset="100%" stop-color="#e5edf5" />
      </linearGradient>
    </defs>
    <rect width="1200" height="900" rx="32" fill="url(#bg)" />
    <rect x="80" y="90" width="1040" height="120" rx="24" fill="#ffffff" stroke="#dbe3eb" stroke-width="2" />
    <rect x="80" y="250" width="1040" height="150" rx="24" fill="#ffffff" stroke="#dbe3eb" stroke-width="2" />
    <rect x="80" y="440" width="1040" height="310" rx="28" fill="#ffffff" stroke="#dbe3eb" stroke-width="2" />
    <rect x="150" y="505" width="240" height="86" rx="18" fill="#111827" opacity="0.08" />
    <rect x="680" y="520" width="190" height="72" rx="16" fill="#111827" opacity="0.08" />
    <rect x="870" y="610" width="130" height="60" rx="16" fill="#111827" opacity="0.08" />
    <rect x="438" y="144" width="210" height="32" rx="10" fill="#0f766e" opacity="0.16" />
    <rect x="202" y="310" width="320" height="32" rx="10" fill="#b45309" opacity="0.16" />
    <rect x="618" y="320" width="276" height="32" rx="10" fill="#7c3aed" opacity="0.16" />
  </svg>
`);

const previewImageRedactedSvg = encodeURIComponent(`
  <svg xmlns="http://www.w3.org/2000/svg" width="1200" height="900" viewBox="0 0 1200 900">
    <defs>
      <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="#f8fafc" />
        <stop offset="100%" stop-color="#e5edf5" />
      </linearGradient>
      <pattern id="mosaic" width="14" height="14" patternUnits="userSpaceOnUse">
        <rect width="14" height="14" fill="#111827" opacity="0.24" />
        <rect width="7" height="7" fill="#111827" opacity="0.14" />
        <rect x="7" y="7" width="7" height="7" fill="#111827" opacity="0.08" />
      </pattern>
    </defs>
    <rect width="1200" height="900" rx="32" fill="url(#bg)" />
    <rect x="80" y="90" width="1040" height="120" rx="24" fill="#ffffff" stroke="#dbe3eb" stroke-width="2" />
    <rect x="80" y="250" width="1040" height="150" rx="24" fill="#ffffff" stroke="#dbe3eb" stroke-width="2" />
    <rect x="80" y="440" width="1040" height="310" rx="28" fill="#ffffff" stroke="#dbe3eb" stroke-width="2" />
    <rect x="150" y="505" width="240" height="86" rx="18" fill="url(#mosaic)" />
    <rect x="680" y="520" width="190" height="72" rx="16" fill="url(#mosaic)" />
    <rect x="870" y="610" width="130" height="60" rx="16" fill="url(#mosaic)" />
  </svg>
`);

const previewFileDefs = [
  { id: 'preview-file-contract', name: '合同审阅-样例-A.docx', size: 184320, type: FileType.DOCX, entityCount: 4, image: false },
  { id: 'preview-file-contract-2', name: '补充协议-样例-E.docx', size: 246784, type: FileType.DOCX, entityCount: 5, image: false },
  { id: 'preview-file-contract-3', name: '财务函件-样例-F.docx', size: 203648, type: FileType.DOCX, entityCount: 4, image: false },
  { id: 'preview-file-case', name: '案件材料-样例-B.pdf', size: 912384, type: FileType.PDF, entityCount: 3, image: false },
  { id: 'preview-file-case-2', name: '证据目录-样例-G.pdf', size: 864256, type: FileType.PDF, entityCount: 6, image: false },
  { id: 'preview-file-case-3', name: '出庭笔录-样例-H.pdf', size: 1024512, type: FileType.PDF, entityCount: 5, image: false },
  { id: 'preview-file-scan', name: '扫描签章-样例-C.pdf', size: 1264032, type: FileType.PDF_SCANNED, entityCount: 3, image: true },
  { id: 'preview-file-scan-2', name: '盖章申请-样例-I.pdf', size: 1116928, type: FileType.PDF_SCANNED, entityCount: 4, image: true },
  { id: 'preview-file-scan-3', name: '档案扫描-样例-J.pdf', size: 1380352, type: FileType.PDF_SCANNED, entityCount: 6, image: true },
  { id: 'preview-file-photo', name: '现场照片-样例-D.png', size: 742112, type: FileType.IMAGE, entityCount: 2, image: true },
  { id: 'preview-file-photo-2', name: '证件照片-样例-K.png', size: 682144, type: FileType.IMAGE, entityCount: 3, image: true },
  { id: 'preview-file-photo-3', name: '门牌影像-样例-L.png', size: 755904, type: FileType.IMAGE, entityCount: 3, image: true },
] as const;

const previewRowsBase: BatchRow[] = previewFileDefs.map((file) => ({
  file_id: file.id,
  original_filename: file.name,
  file_size: file.size,
  file_type: file.type,
  created_at: previewNow,
  has_output: false,
  entity_count: file.entityCount,
  analyzeStatus: 'pending',
  isImageMode: file.image,
  reviewConfirmed: false,
}));

const regexPreviewTemplates = [
  { id: 'ID_CARD', name: '身份证号', pattern: '\\b\\d{17}[\\dXx]\\b' },
  { id: 'BANK_CARD', name: '银行卡号', pattern: '\\b\\d{12,19}\\b' },
  { id: 'PHONE', name: '手机号码', pattern: '\\b1[3-9]\\d{9}\\b' },
  { id: 'EMAIL', name: '电子邮箱', pattern: '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}' },
  { id: 'CASE_CODE', name: '案件编号', pattern: '[（(]?20\\d{2}[）)]?[\\u4e00-\\u9fa5A-Za-z]{1,8}\\d{2,6}号' },
  { id: 'PASSPORT', name: '护照号码', pattern: '[A-Z0-9]{8,17}' },
  { id: 'PLATE', name: '车牌号码', pattern: '[\\u4e00-\\u9fa5][A-Z][A-Z0-9]{5,6}' },
  { id: 'CREDIT_CODE', name: '统一社会信用代码', pattern: '[0-9A-Z]{18}' },
  { id: 'SOCIAL_SECURITY', name: '社保编号', pattern: '\\b\\d{10,18}\\b' },
  { id: 'POST_CODE', name: '邮政编码', pattern: '\\b\\d{6}\\b' },
] as const;

const semanticPreviewTemplates = [
  '当事人姓名',
  '企业名称',
  '项目名称',
  '详细地址',
  '合同金额',
  '法院名称',
  '部门名称',
  '受益人姓名',
  '项目地点',
  '开户银行',
] as const;

export const previewTextTypes: TextEntityType[] = Array.from({ length: 120 }, (_, index) => {
  if (index < 60) {
    const template = regexPreviewTemplates[index % regexPreviewTemplates.length];
    const cycle = Math.floor(index / regexPreviewTemplates.length);
    const suffix = cycle === 0 ? '' : ` ${String(cycle + 1).padStart(2, '0')}`;
    return {
      id: cycle === 0 ? template.id : `${template.id}_${cycle + 1}`,
      name: `${template.name}${suffix}`,
      color: '#0f766e',
      regex_pattern: template.pattern,
      order: index + 1,
    };
  }

  const semanticIndex = index - 60;
  const template = semanticPreviewTemplates[semanticIndex % semanticPreviewTemplates.length];
  const cycle = Math.floor(semanticIndex / semanticPreviewTemplates.length);
  const suffix = cycle === 0 ? '' : ` ${String(cycle + 1).padStart(2, '0')}`;
  return {
    id: cycle === 0 ? `SEM_${semanticIndex + 1}` : `SEM_${semanticIndex + 1}_${cycle + 1}`,
    name: `${template}${suffix}`,
    color: '#2563eb',
    use_llm: true,
    order: index + 1,
  };
});

const previewOcrNames = ['公章文字', '手写姓名', '边注文字', '回单抬头'] as const;
const previewImageNames = ['签名区域', '印章区域', '人脸区域', '车牌区域'] as const;

export const previewPipelines: PipelineCfg[] = [
  {
    mode: 'ocr_has',
    name: 'OCR + HaS',
    description: '文字检测通道',
    enabled: true,
    types: Array.from({ length: 12 }, (_, index) => ({
      id: `ocr_type_${index + 1}`,
      name:
        previewOcrNames[index % previewOcrNames.length] +
        (index >= previewOcrNames.length ? ` ${String(Math.floor(index / previewOcrNames.length) + 1).padStart(2, '0')}` : ''),
      color: '#0f766e',
      enabled: true,
      order: index + 1,
    })),
  },
  {
    mode: 'has_image',
    name: 'HaS Image',
    description: '图像特征通道',
    enabled: true,
    types: Array.from({ length: 12 }, (_, index) => ({
      id: `image_type_${index + 1}`,
      name:
        previewImageNames[index % previewImageNames.length] +
        (index >= previewImageNames.length ? ` ${String(Math.floor(index / previewImageNames.length) + 1).padStart(2, '0')}` : ''),
      color: '#b45309',
      enabled: true,
      order: index + 1,
    })),
  },
];

const allPreviewTextIds = previewTextTypes.map((type) => type.id);
const allPreviewOcrIds = previewPipelines.find((pipeline) => pipeline.mode === 'ocr_has')?.types.map((type) => type.id) ?? [];
const allPreviewImageIds = previewPipelines.find((pipeline) => pipeline.mode === 'has_image')?.types.map((type) => type.id) ?? [];

export const previewPresets: RecognitionPreset[] = [
  {
    id: 'preview-text-preset',
    name: '合同文本预设',
    kind: 'text',
    selectedEntityTypeIds: allPreviewTextIds,
    ocrHasTypes: [],
    hasImageTypes: [],
    replacementMode: 'structured',
    created_at: previewNow,
    updated_at: previewNow,
  },
  {
    id: 'preview-vision-preset',
    name: '扫描图像预设',
    kind: 'vision',
    selectedEntityTypeIds: [],
    ocrHasTypes: allPreviewOcrIds,
    hasImageTypes: allPreviewImageIds,
    replacementMode: 'structured',
    created_at: previewNow,
    updated_at: previewNow,
  },
];

export const previewBatchConfig: BatchWizardPersistedConfig = {
  selectedEntityTypeIds: allPreviewTextIds,
  ocrHasTypes: allPreviewOcrIds,
  hasImageTypes: allPreviewImageIds,
  replacementMode: 'structured',
  imageRedactionMethod: 'mosaic',
  imageRedactionStrength: 25,
  imageFillColor: '#000000',
  presetTextId: 'preview-text-preset',
  presetVisionId: 'preview-vision-preset',
  executionDefault: 'queue',
};

const previewTextEntities: ReviewEntity[] = [
  {
    id: 'preview-entity-person',
    text: '张宁',
    type: 'SEM_1',
    start: 7,
    end: 9,
    selected: true,
    page: 1,
    confidence: 0.98,
    source: 'llm',
  },
  {
    id: 'preview-entity-id',
    text: '310101199201013422',
    type: 'ID_CARD',
    start: 19,
    end: 37,
    selected: true,
    page: 1,
    confidence: 0.99,
    source: 'regex',
  },
  {
    id: 'preview-entity-case',
    text: '（2026）民终083号',
    type: 'CASE_CODE',
    start: 47,
    end: 60,
    selected: true,
    page: 1,
    confidence: 0.95,
    source: 'llm',
  },
];

const previewCaseEntities: ReviewEntity[] = [
  {
    id: 'preview-entity-bank',
    text: '6214850200123456789',
    type: 'BANK_CARD',
    start: 28,
    end: 47,
    selected: true,
    page: 1,
    confidence: 0.97,
    source: 'regex',
  },
  {
    id: 'preview-entity-person-2',
    text: '王敏',
    type: 'SEM_1',
    start: 58,
    end: 60,
    selected: true,
    page: 1,
    confidence: 0.92,
    source: 'llm',
  },
];

const previewImageBoxes: EditorBox[] = [
  {
    id: 'preview-box-signature',
    x: 0.125,
    y: 0.46,
    width: 0.2,
    height: 0.095,
    type: 'image_type_1',
    text: '签名',
    selected: true,
    source: 'has_image',
    confidence: 0.96,
  },
  {
    id: 'preview-box-stamp',
    x: 0.565,
    y: 0.48,
    width: 0.16,
    height: 0.08,
    type: 'image_type_2',
    text: '公章',
    selected: true,
    source: 'has_image',
    confidence: 0.94,
  },
  {
    id: 'preview-box-face',
    x: 0.725,
    y: 0.6,
    width: 0.11,
    height: 0.07,
    type: 'image_type_3',
    text: '头像',
    selected: false,
    source: 'has_image',
    confidence: 0.9,
  },
];

export function buildPreviewBatchRoute(mode: BatchWizardMode = 'smart', step: Step = 1): string {
  return `/batch/${mode}?preview=1&jobId=${encodeURIComponent(PREVIEW_BATCH_JOB_ID)}&step=${step}`;
}

export function isPreviewBatchJobId(jobId: string | null | undefined): boolean {
  return jobId === PREVIEW_BATCH_JOB_ID;
}

export function buildPreviewBatchRows(step: Step): BatchRow[] {
  if (step >= 5) {
    return previewRowsBase.map((row) => ({
      ...row,
      analyzeStatus: 'completed',
      reviewConfirmed: true,
      has_output: true,
    }));
  }

  if (step >= 4) {
    return previewRowsBase.map((row, index) => ({
      ...row,
      analyzeStatus: index === 0 ? 'completed' : 'awaiting_review',
      reviewConfirmed: index === 0,
      has_output: index === 0,
    }));
  }

  if (step >= 3) {
    return previewRowsBase.map((row, index) => ({
      ...row,
      analyzeStatus: index === 3 ? 'analyzing' : 'awaiting_review',
      reviewConfirmed: false,
      has_output: false,
    }));
  }

  return previewRowsBase.map((row) => ({ ...row }));
}

export function getPreviewReviewPayload(fileId: string): {
  content: string;
  entities: ReviewEntity[];
  boxes: EditorBox[];
  imageSrc: string;
  previewSrc: string;
} {
  if (fileId === 'preview-file-contract') {
    return {
      content: '合同主体张宁，身份证号为310101199201013422，关联案件编号为（2026）民终083号，需在导出前统一处理。',
      entities: previewTextEntities,
      boxes: [],
      imageSrc: '',
      previewSrc: '',
    };
  }

  if (fileId === 'preview-file-case') {
    return {
      content: '回款账户6214850200123456789已写入附件，复核人员王敏需要确认最终脱敏结果。',
      entities: previewCaseEntities,
      boxes: [],
      imageSrc: '',
      previewSrc: '',
    };
  }

  return {
    content: '',
    entities: [],
    boxes: previewImageBoxes,
    imageSrc: `data:image/svg+xml;charset=UTF-8,${previewImageSvg}`,
    previewSrc: `data:image/svg+xml;charset=UTF-8,${previewImageRedactedSvg}`,
  };
}

export function buildPreviewDownloadBlob(redacted: boolean, rows: BatchRow[]): Blob {
  const lines = [
    redacted ? '批量脱敏预览导出' : '批量原件预览导出',
    '',
    ...rows.map((row) => `- ${row.original_filename}`),
  ];
  return new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' });
}
