// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type { JobDetail, JobItemRow } from '@/services/jobsApi';
import { buildBatchWorkbenchUrl } from '@/utils/jobPrimaryNavigation';

export type JobRecoveryCategory =
  | 'file_missing'
  | 'text_model'
  | 'vision_model'
  | 'parsing'
  | 'redaction'
  | 'unknown';

export type JobRecoveryAction = {
  category: JobRecoveryCategory;
  count: number;
  filenames: string[];
  titleKey: string;
  descKey: string;
  ctaKey: string;
  to: string;
};

export type JobRecoveryPlan = {
  failedItems: JobItemRow[];
  actions: JobRecoveryAction[];
  partialReviewAction: {
    count: number;
    to: string;
  } | null;
};

const CATEGORY_COPY: Record<JobRecoveryCategory, Pick<JobRecoveryAction, 'titleKey' | 'descKey' | 'ctaKey'>> = {
  file_missing: {
    titleKey: 'jobDetail.recovery.fileMissing.title',
    descKey: 'jobDetail.recovery.fileMissing.desc',
    ctaKey: 'jobDetail.recovery.fileMissing.cta',
  },
  text_model: {
    titleKey: 'jobDetail.recovery.textModel.title',
    descKey: 'jobDetail.recovery.textModel.desc',
    ctaKey: 'jobDetail.recovery.textModel.cta',
  },
  vision_model: {
    titleKey: 'jobDetail.recovery.visionModel.title',
    descKey: 'jobDetail.recovery.visionModel.desc',
    ctaKey: 'jobDetail.recovery.visionModel.cta',
  },
  parsing: {
    titleKey: 'jobDetail.recovery.parsing.title',
    descKey: 'jobDetail.recovery.parsing.desc',
    ctaKey: 'jobDetail.recovery.parsing.cta',
  },
  redaction: {
    titleKey: 'jobDetail.recovery.redaction.title',
    descKey: 'jobDetail.recovery.redaction.desc',
    ctaKey: 'jobDetail.recovery.redaction.cta',
  },
  unknown: {
    titleKey: 'jobDetail.recovery.unknown.title',
    descKey: 'jobDetail.recovery.unknown.desc',
    ctaKey: 'jobDetail.recovery.unknown.cta',
  },
};

const CATEGORY_ORDER: JobRecoveryCategory[] = [
  'file_missing',
  'text_model',
  'vision_model',
  'redaction',
  'parsing',
  'unknown',
];

export function buildJobRecoveryPlan(job: JobDetail): JobRecoveryPlan {
  const failedItems = job.items.filter((item) => item.status === 'failed');
  const firstAwaitingReview = job.items.find((item) => item.status === 'awaiting_review')?.id;
  const awaitingReviewCount =
    job.nav_hints?.awaiting_review_count ?? job.progress.awaiting_review ?? 0;
  const grouped = new Map<JobRecoveryCategory, JobItemRow[]>();

  failedItems.forEach((item) => {
    const category = classifyFailedItem(item);
    grouped.set(category, [...(grouped.get(category) ?? []), item]);
  });

  const actions = CATEGORY_ORDER.flatMap((category) => {
    const items = grouped.get(category);
    if (!items?.length) return [];
    const copy = CATEGORY_COPY[category];
    return [
      {
        category,
        count: items.length,
        filenames: items.slice(0, 3).map((item) => item.filename || item.file_id),
        ...copy,
        to: buildRecoveryTarget(job, category, items[0]?.id),
      },
    ];
  });

  return {
    failedItems,
    actions,
    partialReviewAction:
      awaitingReviewCount > 0
        ? {
            count: awaitingReviewCount,
            to: buildBatchWorkbenchUrl(
              job.id,
              job.job_type,
              4,
              firstAwaitingReview ?? job.nav_hints?.first_awaiting_review_item_id ?? undefined,
              job.config,
            ),
          }
        : null,
  };
}

function buildRecoveryTarget(
  job: JobDetail,
  category: JobRecoveryCategory,
  itemId?: string,
): string {
  if (category === 'text_model') return '/model-settings/text';
  if (category === 'vision_model') return '/model-settings/vision';
  if (category === 'file_missing') return buildBatchWorkbenchUrl(job.id, job.job_type, 2, undefined, job.config);
  if (category === 'redaction') {
    return buildBatchWorkbenchUrl(job.id, job.job_type, 4, itemId, job.config);
  }
  return buildBatchWorkbenchUrl(job.id, job.job_type, 3, undefined, job.config);
}

export function classifyFailedItem(item: JobItemRow): JobRecoveryCategory {
  const haystack = [
    item.error_message,
    item.progress_stage,
    item.file_type,
    item.filename,
    item.status,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();

  if (/(file not found|missing file|no such file|path not found|orphan|文件不存在|找不到文件)/.test(haystack)) {
    return 'file_missing';
  }
  if (/(ocr|vision|image|has image|paddle|pp-structure|scan|stamp|seal|bbox|bounding|图片|图像|扫描|印章|公章)/.test(haystack)) {
    return 'vision_model';
  }
  if (/(ner|llm|llama|has ner|semantic|entity|text model|实体|语义|文本模型)/.test(haystack)) {
    return 'text_model';
  }
  if (/(redact|redaction|output|render|mask|mosaic|download|匿名化|脱敏|生成产物)/.test(haystack)) {
    return 'redaction';
  }
  if (/(parse|extract|convert|unsupported|format|read|decode|解析|格式|读取|转换)/.test(haystack)) {
    return 'parsing';
  }
  return 'unknown';
}
