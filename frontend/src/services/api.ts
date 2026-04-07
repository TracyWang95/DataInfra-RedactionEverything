// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import {
  apiClient as api,
  authFetch,
  clearAuthToken,
  downloadFile,
  authenticatedBlobUrl,
  getAuthToken,
  setAuthToken,
  VISION_TIMEOUT,
} from './api-client';
import type {
  CompareData,
  EntityTypeConfig,
  EntityTypeConfigSimple,
  FileInfo,
  FileListResponse,
  NERResult,
  ParseResult,
  RedactionRequest,
  RedactionResult,
  ReplacementModeConfig,
  VisionResult,
} from '../types';

export { clearAuthToken, downloadFile, authenticatedBlobUrl, getAuthToken, setAuthToken };

export const fileApi = {
  upload: async (
    file: File,
    batchGroupId?: string | null,
    jobId?: string | null,
    uploadSource?: 'playground' | 'batch' | null,
  ): Promise<FileInfo> => {
    const formData = new FormData();
    formData.append('file', file);
    if (batchGroupId) formData.append('batch_group_id', batchGroupId);
    if (jobId) formData.append('job_id', jobId);
    if (uploadSource) formData.append('upload_source', uploadSource);
    return api.post('/files/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  parse: async (fileId: string): Promise<ParseResult> => api.get(`/files/${fileId}/parse`),

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

  batchDownloadZip: async (fileIds: string[], redacted: boolean): Promise<Blob> => {
    const res = await authFetch('/api/v1/files/batch/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ file_ids: fileIds, redacted }),
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
    return res.blob();
  },

  getDownloadUrl: (fileId: string, redacted = false): string =>
    `/api/v1/files/${fileId}/download?redacted=${redacted}`,

  delete: async (fileId: string): Promise<void> => api.delete(`/files/${fileId}`),
};

export const nerApi = {
  extractEntities: async (fileId: string): Promise<NERResult> => api.get(`/files/${fileId}/ner`),
};

export const redactionApi = {
  execute: async (request: RedactionRequest): Promise<RedactionResult> =>
    api.post('/redaction/execute', request),

  getComparison: async (fileId: string): Promise<CompareData> =>
    api.get(`/redaction/${fileId}/compare`),

  detectSensitiveRegions: async (fileId: string, page = 1): Promise<VisionResult> =>
    api.post(`/redaction/${fileId}/vision?page=${page}`, undefined, { timeout: VISION_TIMEOUT }),

  getEntityTypes: async (): Promise<{ entity_types: EntityTypeConfigSimple[] }> =>
    api.get('/redaction/entity-types'),

  getReport: async (fileId: string): Promise<unknown> =>
    api.get(`/redaction/${fileId}/report`),

  getReplacementModes: async (): Promise<{ replacement_modes: ReplacementModeConfig[] }> =>
    api.get('/redaction/replacement-modes'),
};

export const entityTypesApi = {
  getAll: async (enabledOnly = false): Promise<{ custom_types: EntityTypeConfig[]; total: number }> =>
    api.get(`/custom-types?enabled_only=${enabledOnly}`),

  getById: async (typeId: string): Promise<EntityTypeConfig> =>
    api.get(`/custom-types/${typeId}`),

  create: async (data: Partial<EntityTypeConfig>): Promise<EntityTypeConfig> =>
    api.post('/custom-types', data),

  update: async (typeId: string, data: Partial<EntityTypeConfig>): Promise<EntityTypeConfig> =>
    api.put(`/custom-types/${typeId}`, data),

  delete: async (typeId: string): Promise<void> =>
    api.delete(`/custom-types/${typeId}`),

  toggle: async (typeId: string): Promise<{ enabled: boolean }> =>
    api.post(`/custom-types/${typeId}/toggle`),

  reset: async (): Promise<{ message: string }> =>
    api.post('/custom-types/reset'),
};

export default api;
