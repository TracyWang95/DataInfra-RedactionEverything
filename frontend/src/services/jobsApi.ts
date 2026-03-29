/**
 * 任务中心：文本批量 / 图像批量 Job API
 */
const BASE = '/api/v1/jobs';

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
  /** 后端表示是否已有持久化草稿行 */
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
  /** 列表摘要：供导航解析（awaiting_review 时带出首个待审 itemId） */
  nav_hints?: {
    item_count: number;
    first_awaiting_review_item_id?: string | null;
    wizard_furthest_step?: number | null;
    batch_step1_configured?: boolean | null;
  };
};

export type JobDetail = JobSummary & { items: JobItemRow[] };

export type DeleteJobResult = {
  id: string;
  deleted: boolean;
  deleted_item_count: number;
  detached_file_count: number;
};

async function parseJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const err = await res.json();
      msg = typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail ?? err);
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export async function createJob(body: {
  job_type: JobTypeApi;
  title?: string;
  config?: Record<string, unknown>;
  skip_item_review?: boolean;
  priority?: number;
}): Promise<JobSummary> {
  const res = await fetch(BASE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return parseJson<JobSummary>(res);
}

export async function updateJobDraft(
  jobId: string,
  body: { title?: string; config?: Record<string, unknown>; skip_item_review?: boolean }
): Promise<JobSummary> {
  const res = await fetch(`${BASE}/${encodeURIComponent(jobId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return parseJson<JobSummary>(res);
}

export async function listJobs(params: {
  job_type?: JobTypeApi;
  page?: number;
  page_size?: number;
}): Promise<{ jobs: JobSummary[]; total: number; page: number; page_size: number }> {
  const sp = new URLSearchParams();
  if (params.job_type) sp.set('job_type', params.job_type);
  if (params.page) sp.set('page', String(params.page));
  if (params.page_size) sp.set('page_size', String(params.page_size));
  const q = sp.toString();
  const res = await fetch(q ? `${BASE}?${q}` : BASE);
  return parseJson(res);
}

export async function getJob(jobId: string): Promise<JobDetail> {
  const res = await fetch(`${BASE}/${encodeURIComponent(jobId)}`);
  return parseJson<JobDetail>(res);
}

export async function submitJob(jobId: string): Promise<JobSummary> {
  const res = await fetch(`${BASE}/${encodeURIComponent(jobId)}/submit`, { method: 'POST' });
  return parseJson<JobSummary>(res);
}

export async function cancelJob(jobId: string): Promise<JobSummary> {
  const res = await fetch(`${BASE}/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' });
  return parseJson<JobSummary>(res);
}

export async function deleteJob(jobId: string): Promise<DeleteJobResult> {
  const res = await fetch(`${BASE}/${encodeURIComponent(jobId)}`, { method: 'DELETE' });
  return parseJson<DeleteJobResult>(res);
}

export async function approveItemReview(jobId: string, itemId: string): Promise<JobItemRow> {
  const res = await fetch(
    `${BASE}/${encodeURIComponent(jobId)}/items/${encodeURIComponent(itemId)}/review/approve`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }
  );
  return parseJson<JobItemRow>(res);
}

export async function rejectItemReview(jobId: string, itemId: string): Promise<JobItemRow> {
  const res = await fetch(
    `${BASE}/${encodeURIComponent(jobId)}/items/${encodeURIComponent(itemId)}/review/reject`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }
  );
  return parseJson<JobItemRow>(res);
}

export async function getItemReviewDraft(jobId: string, itemId: string): Promise<JobItemReviewDraft> {
  const res = await fetch(
    `${BASE}/${encodeURIComponent(jobId)}/items/${encodeURIComponent(itemId)}/review-draft`
  );
  return parseJson<JobItemReviewDraft>(res);
}

export async function putItemReviewDraft(
  jobId: string,
  itemId: string,
  body: { entities: Array<Record<string, unknown>>; bounding_boxes: Array<Record<string, unknown>> }
): Promise<JobItemReviewDraft> {
  const res = await fetch(
    `${BASE}/${encodeURIComponent(jobId)}/items/${encodeURIComponent(itemId)}/review-draft`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }
  );
  return parseJson(res);
}

export async function commitItemReview(
  jobId: string,
  itemId: string,
  body: { entities: Array<Record<string, unknown>>; bounding_boxes: Array<Record<string, unknown>> }
): Promise<JobItemRow> {
  const res = await fetch(
    `${BASE}/${encodeURIComponent(jobId)}/items/${encodeURIComponent(itemId)}/review/commit`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }
  );
  return parseJson<JobItemRow>(res);
}
