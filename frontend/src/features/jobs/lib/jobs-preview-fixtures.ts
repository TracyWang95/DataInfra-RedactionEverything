// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type { JobDetail, JobItemRow, JobProgress, JobSummary, JobTypeApi } from '@/services/jobsApi';

const PREVIEW_JOB_COUNT = 42;

function buildProgress(total: number, index: number): JobProgress {
  const pattern = index % 5;

  if (pattern === 0) {
    return {
      total_items: total,
      pending: 0,
      queued: 0,
      parsing: 0,
      ner: 0,
      vision: 0,
      awaiting_review: 2,
      review_approved: 0,
      redacting: 0,
      completed: total - 2,
      failed: 0,
      cancelled: 0,
    };
  }

  if (pattern === 1) {
    return {
      total_items: total,
      pending: 0,
      queued: 1,
      parsing: 1,
      ner: 1,
      vision: 1,
      awaiting_review: 0,
      review_approved: 0,
      redacting: 0,
      completed: total - 4,
      failed: 0,
      cancelled: 0,
    };
  }

  if (pattern === 2) {
    return {
      total_items: total,
      pending: 0,
      queued: 0,
      parsing: 0,
      ner: 0,
      vision: 0,
      awaiting_review: 0,
      review_approved: 0,
      redacting: 0,
      completed: total,
      failed: 0,
      cancelled: 0,
    };
  }

  if (pattern === 3) {
    return {
      total_items: total,
      pending: 0,
      queued: 0,
      parsing: 0,
      ner: 0,
      vision: 0,
      awaiting_review: 0,
      review_approved: 0,
      redacting: 0,
      completed: total - 1,
      failed: 1,
      cancelled: 0,
    };
  }

  return {
    total_items: total,
    pending: 0,
    queued: 0,
    parsing: 0,
    ner: 0,
    vision: 0,
    awaiting_review: 0,
    review_approved: 1,
    redacting: 1,
    completed: total - 2,
    failed: 0,
    cancelled: 0,
  };
}

function buildStatus(index: number): string {
  const pattern = index % 5;
  if (pattern === 0) return 'awaiting_review';
  if (pattern === 1) return 'running';
  if (pattern === 2) return 'completed';
  if (pattern === 3) return 'failed';
  return 'redacting';
}

function buildPreviewJobs(): JobSummary[] {
  const now = new Date('2026-04-05T18:10:00+08:00').getTime();
  const titles = ['合同批量交付', '扫描卷宗交付', '照片复核批次', '诉讼材料批次', '综合档案批次'];

  return Array.from({ length: PREVIEW_JOB_COUNT }, (_, index) => {
    const totalItems = 8 + (index % 6);
    const progress = buildProgress(totalItems, index);
    const status = buildStatus(index);
    const titlePrefix = titles[index % titles.length];

    return {
      id: `preview-job-${index + 1}`,
      job_type: 'smart_batch',
      title: `${titlePrefix} ${String(index + 1).padStart(2, '0')}`,
      status,
      skip_item_review: false,
      config: {
        preferred_execution: index % 2 === 0 ? 'queue' : 'local',
        entity_type_ids: ['PERSON', 'ID_CARD', 'CASE_NUMBER', 'BANK_CARD'],
      },
      error_message: status === 'failed' ? '有 1 个文件需要重新处理。' : null,
      created_at: new Date(now - index * 1000 * 60 * 55).toISOString(),
      updated_at: new Date(now - index * 1000 * 60 * 24).toISOString(),
      progress,
      nav_hints: {
        item_count: totalItems,
        first_awaiting_review_item_id: status === 'awaiting_review' ? `preview-job-${index + 1}-item-1` : null,
        wizard_furthest_step: status === 'completed' ? 5 : 4,
        batch_step1_configured: true,
        redacted_count: progress.completed,
        awaiting_review_count: progress.awaiting_review,
      },
    };
  });
}

function buildPreviewItems(jobId: string): JobItemRow[] {
  return Array.from({ length: 7 }, (_, index) => ({
    id: `${jobId}-item-${index + 1}`,
    job_id: jobId,
    file_id: `${jobId}-file-${index + 1}`,
    sort_order: index + 1,
    status:
      index === 0 ? 'awaiting_review' :
      index === 6 ? 'completed' :
      index % 3 === 0 ? 'review_approved' :
      'completed',
    filename: `批量文件-${String(index + 1).padStart(2, '0')}${index % 2 === 0 ? '.pdf' : '.docx'}`,
    file_type: index % 2 === 0 ? 'pdf' : 'docx',
    has_output: index >= 3,
    entity_count: 4 + index,
    has_review_draft: index === 0,
    review_draft_updated_at: index === 0 ? new Date('2026-04-05T17:00:00+08:00').toISOString() : null,
    error_message: null,
    reviewed_at: index >= 3 ? new Date('2026-04-05T17:30:00+08:00').toISOString() : null,
    reviewer: index >= 3 ? 'preview' : null,
    created_at: new Date('2026-04-05T16:30:00+08:00').toISOString(),
    updated_at: new Date('2026-04-05T17:30:00+08:00').toISOString(),
  }));
}

export function buildJobsPreviewPage(opts: {
  page: number;
  pageSize: number;
  jobType?: JobTypeApi;
}): { jobs: JobSummary[]; total: number; page: number; page_size: number } {
  const jobs = buildPreviewJobs().filter((job) => (opts.jobType ? job.job_type === opts.jobType : true));
  const start = Math.max(0, (opts.page - 1) * opts.pageSize);
  return {
    jobs: jobs.slice(start, start + opts.pageSize),
    total: jobs.length,
    page: opts.page,
    page_size: opts.pageSize,
  };
}

export function buildJobsPreviewDetail(jobId: string): JobDetail {
  const allJobs = buildPreviewJobs();
  const job = allJobs.find((item) => item.id === jobId) ?? allJobs[0];
  return {
    ...job,
    id: jobId,
    items: buildPreviewItems(jobId),
  };
}

export function isJobsPreviewJob(jobId: string): boolean {
  return jobId.startsWith('preview-job-');
}
