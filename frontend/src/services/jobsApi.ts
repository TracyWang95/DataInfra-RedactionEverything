// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0


import { get, post, put, del } from './api-client';

export type JobTypeApi = 'text_batch' | 'image_batch' | 'smart_batch';

export type JobProgress = {
  total_items: number;
  pending: number;
  queued: number;
  parsing: number;
  ner: number;
  vision: number;
  awaiting_review: number;
  review_approved: number;
  redacting: number;
  completed: number;
  failed: number;
  cancelled?: number;
};

export type JobItemRow = {
  id: string;
  job_id: string;
  file_id: string;
  sort_order: number;
  status: string;
  filename?: string;
  file_type?: string;
  has_output?: boolean;
  entity_count?: number;
  has_review_draft?: boolean;
  review_draft_updated_at?: string | null;
  error_message?: string | null;
  reviewed_at?: string | null;
  reviewer?: string | null;
  created_at: string;
  updated_at: string;
};

export type JobItemReviewDraft = {

  exists?: boolean;
  entities: Array<Record<string, unknown>>;
  bounding_boxes: Array<Record<string, unknown>>;
  updated_at?: string | null;
};

export type JobSummary = {
  id: string;
  job_type: JobTypeApi;
  title: string;
  status: string;
  skip_item_review: boolean;
  config: Record<string, unknown>;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
  progress: JobProgress;

  nav_hints?: {
    item_count: number;
    first_awaiting_review_item_id?: string | null;
    wizard_furthest_step?: number | null;
    batch_step1_configured?: boolean | null;
    redacted_count?: number | null;
    awaiting_review_count?: number | null;
  };
};

export type JobDetail = JobSummary & { items: JobItemRow[] };

export type DeleteJobResult = {
  id: string;
  deleted: boolean;
  deleted_item_count: number;
  detached_file_count: number;
};

export function createJob(body: {
  job_type: JobTypeApi;
  title?: string;
  config?: Record<string, unknown>;
  skip_item_review?: boolean;
  priority?: number;
}): Promise<JobSummary> {
  return post<JobSummary>('/jobs', body);
}

export function updateJobDraft(
  jobId: string,
  body: { title?: string; config?: Record<string, unknown>; skip_item_review?: boolean }
): Promise<JobSummary> {
  return put<JobSummary>(`/jobs/${encodeURIComponent(jobId)}`, body);
}

export function listJobs(params: {
  job_type?: JobTypeApi;
  page?: number;
  page_size?: number;
}): Promise<{ jobs: JobSummary[]; total: number; page: number; page_size: number }> {
  return get('/jobs', { params });
}

export function getJob(jobId: string): Promise<JobDetail> {
  return get<JobDetail>(`/jobs/${encodeURIComponent(jobId)}`);
}

export function submitJob(jobId: string): Promise<JobSummary> {
  return post<JobSummary>(`/jobs/${encodeURIComponent(jobId)}/submit`);
}

export function cancelJob(jobId: string): Promise<JobSummary> {
  return post<JobSummary>(`/jobs/${encodeURIComponent(jobId)}/cancel`);
}

export function requeueFailed(jobId: string): Promise<JobSummary> {
  return post<JobSummary>(`/jobs/${encodeURIComponent(jobId)}/requeue-failed`);
}

export function deleteJob(jobId: string): Promise<DeleteJobResult> {
  return del<DeleteJobResult>(`/jobs/${encodeURIComponent(jobId)}`);
}

export function approveItemReview(jobId: string, itemId: string): Promise<JobItemRow> {
  return post<JobItemRow>(
    `/jobs/${encodeURIComponent(jobId)}/items/${encodeURIComponent(itemId)}/review/approve`,
    {}
  );
}

export function rejectItemReview(jobId: string, itemId: string): Promise<JobItemRow> {
  return post<JobItemRow>(
    `/jobs/${encodeURIComponent(jobId)}/items/${encodeURIComponent(itemId)}/review/reject`,
    {}
  );
}

export function getItemReviewDraft(jobId: string, itemId: string): Promise<JobItemReviewDraft> {
  return get<JobItemReviewDraft>(
    `/jobs/${encodeURIComponent(jobId)}/items/${encodeURIComponent(itemId)}/review-draft`
  );
}

export function putItemReviewDraft(
  jobId: string,
  itemId: string,
  body: { entities: Array<Record<string, unknown>>; bounding_boxes: Array<Record<string, unknown>> }
): Promise<JobItemReviewDraft> {
  return put<JobItemReviewDraft>(
    `/jobs/${encodeURIComponent(jobId)}/items/${encodeURIComponent(itemId)}/review-draft`,
    body
  );
}

export function commitItemReview(
  jobId: string,
  itemId: string,
  body: { entities: Array<Record<string, unknown>>; bounding_boxes: Array<Record<string, unknown>> }
): Promise<JobItemRow> {
  return post<JobItemRow>(
    `/jobs/${encodeURIComponent(jobId)}/items/${encodeURIComponent(itemId)}/review/commit`,
    body
  );
}
