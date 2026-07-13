// Copyright 2026 DataInfra-RedactionEverything Contributors

import {
  apiClient as api,
  authFetch,
  authenticatedBlobUrl,
  BATCH_TIMEOUT,
} from './api-client';
import type { CompareData, FileInfo, FileListResponse } from '../types';

export { authenticatedBlobUrl };

export interface BatchZipSkippedItem {
  file_id: string;
  reason: string;
}

export interface BatchZipManifestSummary {
  requested_count: number;
  included_count: number;
  skipped_count: number;
  redacted: boolean;
  skipped: BatchZipSkippedItem[];
}

export type BatchZipBlob = Blob & {
  batchManifest?: BatchZipManifestSummary;
};

function parseCountHeader(headers: Headers, name: string): number {
  const raw = headers.get(name);
  const parsed = raw ? Number.parseInt(raw, 10) : 0;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function parseSkippedHeader(headers: Headers): BatchZipSkippedItem[] {
  const raw = headers.get('X-Batch-Zip-Skipped');
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map((item): BatchZipSkippedItem | null => {
        if (!item || typeof item !== 'object') return null;
        const fileId = typeof item.file_id === 'string' ? item.file_id : '';
        const reason = typeof item.reason === 'string' ? item.reason : '';
        return fileId && reason ? { file_id: fileId, reason } : null;
      })
      .filter((item): item is BatchZipSkippedItem => Boolean(item));
  } catch {
    return [];
  }
}

export function getBatchZipManifest(blob: Blob): BatchZipManifestSummary | null {
  return (blob as BatchZipBlob).batchManifest ?? null;
}

// ─── 异步分卷导出（万级文件） ─────────────────────────────────

export interface BatchExportEstimate {
  total_bytes: number;
  file_count: number;
  estimated_volume_count: number;
  skipped: BatchZipSkippedItem[];
  skipped_count: number;
}

export interface BatchExportVolume {
  name: string;
  size_bytes: number;
  file_count: number;
}

export interface BatchExportTask {
  export_id: string;
  kind: string;
  title: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  error: string | null;
  progress: { stage: string; current: number; total: number };
  volumes: BatchExportVolume[];
  total_bytes: number;
  file_count: number;
  estimated_volume_count?: number;
}

export const batchExportApi = {
  estimate: async (fileIds: string[], redacted: boolean, jobId?: string | null): Promise<BatchExportEstimate> =>
    api.post('/files/batch/export/estimate', { file_ids: fileIds, redacted, job_id: jobId ?? undefined }),

  create: async (fileIds: string[], redacted: boolean, jobId?: string | null): Promise<BatchExportTask> =>
    api.post('/files/batch/export', { file_ids: fileIds, redacted, job_id: jobId ?? undefined }),

  get: async (exportId: string): Promise<BatchExportTask> =>
    api.get(`/files/batch/export/${encodeURIComponent(exportId)}`),

  createJobData: async (jobId: string, fileIds?: string[] | null): Promise<BatchExportTask> =>
    api.post(`/jobs/${encodeURIComponent(jobId)}/export-data`, {
      file_ids: fileIds ?? undefined,
      include_entities: true,
    }),

  volumeUrl: (exportId: string, name: string): string =>
    `${api.defaults.baseURL}/files/batch/export/${encodeURIComponent(exportId)}/volumes/${encodeURIComponent(name)}`,
};

// ─── 断点续传 ───────────────────────────────────────────────
// 大文件走分块上传：断线后查询服务端已收字节，从断点续传，不整包重来。
const RESUMABLE_THRESHOLD_BYTES = 6 * 1024 * 1024;
const UPLOAD_CHUNK_BYTES = 5 * 1024 * 1024;
const UPLOAD_CHUNK_RETRIES = 3;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function uploadResumable(
  file: File,
  batchGroupId: string | null | undefined,
  jobId: string | null | undefined,
  uploadSource: 'playground' | 'batch' | null | undefined,
  idempotencyKey: string,
): Promise<FileInfo> {
  const init: { upload_id: string; received_bytes: number } = await api.post(
    '/files/upload/resumable/init',
    {
      filename: file.name,
      file_size: file.size,
      batch_group_id: batchGroupId ?? undefined,
      job_id: jobId ?? undefined,
      upload_source: uploadSource ?? undefined,
    },
  );
  const uploadId = init.upload_id;
  let offset = init.received_bytes ?? 0;

  while (offset < file.size) {
    const chunk = file.slice(offset, offset + UPLOAD_CHUNK_BYTES);
    for (let attempt = 1; ; attempt++) {
      try {
        const r: { received_bytes: number } = await api.put(
          `/files/upload/resumable/${encodeURIComponent(uploadId)}/chunk`,
          chunk,
          {
            params: { offset },
            headers: { 'Content-Type': 'application/octet-stream' },
            timeout: BATCH_TIMEOUT,
          },
        );
        offset = r.received_bytes;
        break;
      } catch (err) {
        if (attempt >= UPLOAD_CHUNK_RETRIES) throw err;
        await sleep(1500 * attempt);
        // 断点：向服务端要已收字节（超时的块可能其实已落盘），从那里继续
        try {
          const s: { received_bytes: number } = await api.get(
            `/files/upload/resumable/${encodeURIComponent(uploadId)}`,
          );
          offset = s.received_bytes;
          if (offset >= file.size) break;
        } catch {
          /* 状态查询也失败就按原 offset 重试 */
        }
      }
    }
  }

  for (let attempt = 1; ; attempt++) {
    try {
      return await api.post(
        `/files/upload/resumable/${encodeURIComponent(uploadId)}/complete`,
        {},
        { headers: { 'X-Idempotency-Key': idempotencyKey }, timeout: BATCH_TIMEOUT },
      );
    } catch (err) {
      if (attempt >= UPLOAD_CHUNK_RETRIES) throw err;
      await sleep(1500 * attempt);
    }
  }
}

export const fileApi = {
  upload: async (
    file: File,
    batchGroupId?: string | null,
    jobId?: string | null,
    uploadSource?: 'playground' | 'batch' | null,
  ): Promise<FileInfo> => {
    // 幂等键：并发上传下重试/重复请求不会在 job 里重复注册同一文件
    const idempotencyKey = `${jobId ?? 'nojob'}:${file.name}:${file.size}:${file.lastModified}`;
    if (file.size > RESUMABLE_THRESHOLD_BYTES) {
      return uploadResumable(file, batchGroupId, jobId, uploadSource, idempotencyKey);
    }
    const formData = new FormData();
    formData.append('file', file);
    if (batchGroupId) formData.append('batch_group_id', batchGroupId);
    if (jobId) formData.append('job_id', jobId);
    if (uploadSource) formData.append('upload_source', uploadSource);
    return api.post('/files/upload', formData, {
      timeout: BATCH_TIMEOUT,
      headers: {
        'Content-Type': 'multipart/form-data',
        'X-Idempotency-Key': idempotencyKey,
      },
    });
  },

  getInfo: async (fileId: string): Promise<FileInfo> => api.get(`/files/${fileId}`),

  list: async (
    page = 1,
    pageSize = 10,
    opts?: { source?: 'playground' | 'batch'; embed_job?: boolean; job_id?: string },
  ): Promise<FileListResponse> =>
    api.get('/files', {
      params: {
        page,
        page_size: pageSize,
        ...(opts?.source ? { source: opts.source } : {}),
        ...(opts?.embed_job ? { embed_job: true } : {}),
        ...(opts?.job_id ? { job_id: opts.job_id } : {}),
      },
    }),

  batchDownloadZip: async (
    fileIds: string[],
    redacted: boolean,
    jobId?: string | null,
  ): Promise<BatchZipBlob> => {
    const res = await authFetch('/api/v1/files/batch/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ file_ids: fileIds, redacted, ...(jobId ? { job_id: jobId } : {}) }),
    });
    if (!res.ok) {
      let message = 'Failed to download archive';
      try {
        const err = await res.json();
        message = typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail ?? err);
      } catch {
        // ignore json parse failures
      }
      throw new Error(message);
    }
    const blob = (await res.blob()) as BatchZipBlob;
    blob.batchManifest = {
      requested_count: parseCountHeader(res.headers, 'X-Batch-Zip-Requested-Count'),
      included_count: parseCountHeader(res.headers, 'X-Batch-Zip-Included-Count'),
      skipped_count: parseCountHeader(res.headers, 'X-Batch-Zip-Skipped-Count'),
      redacted: res.headers.get('X-Batch-Zip-Redacted') === 'true',
      skipped: parseSkippedHeader(res.headers),
    };
    return blob;
  },

  getDownloadUrl: (fileId: string, redacted = false): string =>
    `/api/v1/files/${fileId}/download?redacted=${redacted}`,

  delete: async (fileId: string): Promise<void> => api.delete(`/files/${fileId}`),
};

export const redactionApi = {
  getComparison: async (fileId: string): Promise<CompareData> =>
    api.get(`/redaction/${fileId}/compare`),
};

