import axios from 'axios';
import type {
  FileInfo,
  FileListResponse,
  ParseResult,
  NERResult,
  VisionResult,
  RedactionRequest,
  RedactionResult,
  CompareData,
  EntityTypeConfig,
  EntityTypeConfigSimple,
  ReplacementModeConfig,
} from '../types';

// Auth token key in localStorage (shared with login flow)
const AUTH_TOKEN_KEY = 'auth_token';

/** Read the current JWT from localStorage (null when AUTH_ENABLED=false). */
export function getAuthToken(): string | null {
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

/** Persist a JWT so all subsequent requests include it. */
export function setAuthToken(token: string): void {
  localStorage.setItem(AUTH_TOKEN_KEY, token);
}

/** Clear the stored JWT (logout). */
export function clearAuthToken(): void {
  localStorage.removeItem(AUTH_TOKEN_KEY);
}

// 创建 axios 实例
const api = axios.create({
  baseURL: '/api/v1',
  timeout: 60000, // 60秒超时（AI处理可能较慢）
});

// 请求拦截器 - automatically attach JWT when available
api.interceptors.request.use(
  (config) => {
    const token = getAuthToken();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// 响应拦截器
api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const message = error.response?.data?.message || error.response?.data?.detail || error.message || '请求失败';
    if (import.meta.env.DEV) {
      console.error('API Error:', message);
    }
    return Promise.reject(new Error(message));
  }
);

// 文件管理 API
export const fileApi = {
  // 上传文件（批量向导可传 batch_group_id，同一会话多文件共享）
  upload: async (
    file: File,
    batchGroupId?: string | null,
    jobId?: string | null,
    uploadSource?: 'playground' | 'batch' | null
  ): Promise<FileInfo> => {
    const formData = new FormData();
    formData.append('file', file);
    if (batchGroupId) {
      formData.append('batch_group_id', batchGroupId);
    }
    if (jobId) {
      formData.append('job_id', jobId);
    }
    if (uploadSource) {
      formData.append('upload_source', uploadSource);
    }
    return api.post('/files/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  // 解析文件
  parse: async (fileId: string): Promise<ParseResult> => {
    return api.get(`/files/${fileId}/parse`);
  },

  // 获取文件信息
  getInfo: async (fileId: string): Promise<FileInfo> => {
    return api.get(`/files/${fileId}`);
  },

  /** 文件列表（处理历史，分页）；source 筛选 Playground / 批量与任务 */
  list: async (
    page: number = 1,
    pageSize: number = 10,
    opts?: { source?: 'playground' | 'batch'; embed_job?: boolean }
  ): Promise<FileListResponse> => {
    return api.get('/files', {
      params: {
        page,
        page_size: pageSize,
        ...(opts?.source ? { source: opts.source } : {}),
        ...(opts?.embed_job ? { embed_job: true } : {}),
      },
    });
  },

  /** 批量打包为 ZIP（返回 Blob） */
  batchDownloadZip: async (fileIds: string[], redacted: boolean): Promise<Blob> => {
    const res = await fetch('/api/v1/files/batch/download', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(getAuthToken() ? { Authorization: `Bearer ${getAuthToken()}` } : {}),
      },
      body: JSON.stringify({ file_ids: fileIds, redacted }),
    });
    if (!res.ok) {
      let msg = '打包下载失败';
      try {
        const err = await res.json();
        msg = typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail ?? err);
      } catch {
        /* ignore */
      }
      throw new Error(msg);
    }
    return res.blob();
  },

  // 下载文件
  getDownloadUrl: (fileId: string, redacted: boolean = false): string => {
    return `/api/v1/files/${fileId}/download?redacted=${redacted}`;
  },

  // 删除文件
  delete: async (fileId: string): Promise<void> => {
    return api.delete(`/files/${fileId}`);
  },
};

// NER识别 API
export const nerApi = {
  // 提取实体
  extractEntities: async (fileId: string): Promise<NERResult> => {
    return api.get(`/files/${fileId}/ner`);
  },
};

// 脱敏处理 API
export const redactionApi = {
  // 执行脱敏
  execute: async (request: RedactionRequest): Promise<RedactionResult> => {
    return api.post('/redaction/execute', request);
  },

  // 获取对比数据
  getComparison: async (fileId: string): Promise<CompareData> => {
    return api.get(`/redaction/${fileId}/compare`);
  },

  // 视觉识别（OCR+NER+YOLO 可能耗时很长，独立超时 > 后端 OCR_TIMEOUT 360s）
  detectSensitiveRegions: async (fileId: string, page: number = 1): Promise<VisionResult> => {
    return api.post(`/redaction/${fileId}/vision?page=${page}`, undefined, { timeout: 400000 });
  },

  // 获取实体类型列表（旧版兼容）
  getEntityTypes: async (): Promise<{ entity_types: EntityTypeConfigSimple[] }> => {
    return api.get('/redaction/entity-types');
  },

  // 获取脱敏质量报告
  getReport: async (fileId: string): Promise<any> => {
    return api.get(`/redaction/${fileId}/report`);
  },

  // 获取替换模式列表
  getReplacementModes: async (): Promise<{ replacement_modes: ReplacementModeConfig[] }> => {
    return api.get('/redaction/replacement-modes');
  },
};

// 实体类型管理 API - 基于 GB/T 37964-2019
export const entityTypesApi = {
  // 获取所有实体类型配置
  getAll: async (enabledOnly: boolean = false): Promise<{ custom_types: EntityTypeConfig[], total: number }> => {
    return api.get(`/custom-types?enabled_only=${enabledOnly}`);
  },

  // 获取单个实体类型
  getById: async (typeId: string): Promise<EntityTypeConfig> => {
    return api.get(`/custom-types/${typeId}`);
  },

  // 创建新的实体类型
  create: async (data: Partial<EntityTypeConfig>): Promise<EntityTypeConfig> => {
    return api.post('/custom-types', data);
  },

  // 更新实体类型
  update: async (typeId: string, data: Partial<EntityTypeConfig>): Promise<EntityTypeConfig> => {
    return api.put(`/custom-types/${typeId}`, data);
  },

  // 删除实体类型
  delete: async (typeId: string): Promise<void> => {
    return api.delete(`/custom-types/${typeId}`);
  },

  // 切换启用状态
  toggle: async (typeId: string): Promise<{ enabled: boolean }> => {
    return api.post(`/custom-types/${typeId}/toggle`);
  },

  // 重置为默认配置
  reset: async (): Promise<{ message: string }> => {
    return api.post('/custom-types/reset');
  },
};

// visionTypesApi 已废弃，图像类型通过 vision-pipelines API 统一管理

/* ─── Authenticated download / fetch helpers ─── */

/** Build a Headers object that includes the JWT Bearer token when available. */
function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = { ...extra };
  const token = getAuthToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

/**
 * Download a file via authenticated fetch (works even with AUTH_ENABLED=true).
 * Falls back to a plain `<a>` link when no auth token is stored.
 */
export async function downloadFile(url: string, filename: string): Promise<void> {
  const token = getAuthToken();
  if (!token) {
    // No auth – direct navigation works when AUTH_ENABLED=false
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    return;
  }

  const res = await fetch(url, { headers: authHeaders() });
  if (!res.ok) {
    throw new Error(`下载失败: ${res.status}`);
  }
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(objectUrl);
}

/**
 * Fetch a file as a Blob URL with authentication.
 * Useful for <img src> / preview scenarios.
 * Returns the original URL directly if no token is stored.
 */
export async function authenticatedBlobUrl(url: string, mime?: string): Promise<string> {
  const token = getAuthToken();
  if (!token) {
    return url;
  }
  const res = await fetch(url, { headers: authHeaders() });
  if (!res.ok) {
    throw new Error(`加载文件失败: ${res.status}`);
  }
  const buf = await res.arrayBuffer();
  const blob = mime ? new Blob([buf], { type: mime }) : new Blob([buf]);
  return URL.createObjectURL(blob);
}

export default api;
