/**
 * 批量向导专用：仅批量页使用，与 Playground 无代码耦合。
 * 封装 parse / NER / vision / execute / 文件详情 等请求。
 */
import type { ParseResult, NERResult, VisionResult, RedactionResult, RedactionRequest } from '../types';

const BASE = '/api/v1';

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

export async function batchParse(fileId: string): Promise<ParseResult> {
  const res = await fetch(`${BASE}/files/${fileId}/parse`, { method: 'GET' });
  return parseJson<ParseResult>(res);
}

export async function batchHybridNer(
  fileId: string,
  body: { entity_type_ids: string[] }
): Promise<NERResult> {
  const res = await fetch(`${BASE}/files/${fileId}/ner/hybrid`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return parseJson<NERResult>(res);
}

export async function batchVision(
  fileId: string,
  page: number,
  selectedOcrHasTypes: string[],
  selectedHasImageTypes: string[]
): Promise<VisionResult> {
  const res = await fetch(`${BASE}/redaction/${fileId}/vision?page=${page}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      selected_ocr_has_types: selectedOcrHasTypes,
      selected_has_image_types: selectedHasImageTypes,
    }),
  });
  return parseJson<VisionResult>(res);
}

export async function batchGetFileRaw(fileId: string): Promise<Record<string, unknown>> {
  const res = await fetch(`${BASE}/files/${fileId}`);
  return parseJson<Record<string, unknown>>(res);
}

export async function batchExecute(request: RedactionRequest): Promise<RedactionResult> {
  const res = await fetch(`${BASE}/redaction/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  return parseJson<RedactionResult>(res);
}

/** 与后端 execute 一致的 entity_map 预览（不落盘） */
export async function batchPreviewEntityMap(body: {
  entities: unknown[];
  config: Record<string, unknown>;
}): Promise<Record<string, string>> {
  const res = await fetch(`${BASE}/redaction/preview-map`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await parseJson<{ entity_map?: Record<string, string> }>(res);
  return data.entity_map ?? {};
}

export async function batchPreviewImage(body: {
  file_id: string;
  page?: number;
  bounding_boxes: unknown[];
  config: Record<string, unknown>;
}): Promise<string> {
  const page = body.page ?? 1;
  const res = await fetch(`${BASE}/redaction/${encodeURIComponent(body.file_id)}/preview-image?page=${page}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      bounding_boxes: body.bounding_boxes,
      config: body.config,
    }),
  });
  const data = await parseJson<{ image_base64?: string }>(res);
  return data.image_base64 ?? '';
}

/** 将 file_store 中的 bounding_boxes 规范为单层数组（多页合并） */
export function flattenBoundingBoxesFromStore(raw: unknown): Array<Record<string, unknown>> {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw as Array<Record<string, unknown>>;
  if (typeof raw === 'object') {
    const out: Array<Record<string, unknown>> = [];
    for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
      const pageNum = Number(k) || 1;
      const arr = Array.isArray(v) ? v : [];
      for (const b of arr) {
        if (b && typeof b === 'object') {
          out.push({ ...(b as object), page: (b as { page?: number }).page ?? pageNum });
        }
      }
    }
    return out;
  }
  return [];
}

/** 批量向导 session 分「文本类批量」与「图片类文本批量」两套 */
export type BatchWizardMode = 'text' | 'image' | 'smart';

const LEGACY_BATCH_WIZARD_KEY = 'batchWizard:config:v1';

/**
 * 图片类文本批量单独升到 v2：v1 里常存 hasImageTypes=[]（旧默认），会导致 YOLO 始终不选；v2 起无旧 session 时按「默认」全选两条链。
 */
export function batchWizardStorageKey(mode: BatchWizardMode): string {
  if (mode === 'image') return 'batchWizard:config:v2:image';
  if (mode === 'smart') return 'batchWizard:config:v2:smart';
  return `batchWizard:config:v1:${mode}`;
}

/** @deprecated 使用 batchWizardStorageKey(mode) */
export const BATCH_WIZARD_STORAGE_KEY = LEGACY_BATCH_WIZARD_KEY;

export interface BatchWizardPersistedConfig {
  selectedEntityTypeIds: string[];
  ocrHasTypes: string[];
  hasImageTypes: string[];
  replacementMode: 'structured' | 'smart' | 'mask';
  /** 图片类批量：HaS Image 风格块级脱敏（与文本替换模式无关） */
  imageRedactionMethod?: 'mosaic' | 'blur' | 'fill';
  imageRedactionStrength?: number;
  imageFillColor?: string;
  /** 文本脱敏配置清单（HaS NER + 替换模式） */
  presetTextId?: string | null;
  /** 图像脱敏配置清单（图片类文本 + 图像特征） */
  presetVisionId?: string | null;
  /** @deprecated 已拆分为 presetTextId / presetVisionId，仅用于兼容旧 session */
  presetId?: string | null;
  /**
   * 默认处理路径：queue=与后台 Worker 队列协同（推荐）；local=倾向在本页跑完识别与导出
   */
  executionDefault?: 'queue' | 'local';
}

export function loadBatchWizardConfig(mode: BatchWizardMode = 'text'): BatchWizardPersistedConfig | null {
  try {
    const key = batchWizardStorageKey(mode);
    let s = sessionStorage.getItem(key);
    if (!s && mode === 'text') {
      s = sessionStorage.getItem(LEGACY_BATCH_WIZARD_KEY);
      if (s) {
        try {
          sessionStorage.setItem(key, s);
          sessionStorage.removeItem(LEGACY_BATCH_WIZARD_KEY);
        } catch {
          /* ignore */
        }
      }
    }
    if (!s) return null;
    const raw = JSON.parse(s) as Record<string, unknown>;
    const legacy = raw.glmVisionTypes as string[] | undefined;
    const hasImageTypes = (raw.hasImageTypes as string[] | undefined) ?? legacy ?? [];
    const base = raw as unknown as BatchWizardPersistedConfig;
    const legacyPid = (raw.presetId as string | null | undefined) ?? base.presetId ?? null;
    return {
      ...base,
      hasImageTypes,
      presetTextId: (raw.presetTextId as string | null | undefined) ?? (legacyPid ?? base.presetTextId ?? null),
      presetVisionId: (raw.presetVisionId as string | null | undefined) ?? (legacyPid ?? base.presetVisionId ?? null),
      presetId: legacyPid,
    };
  } catch {
    return null;
  }
}

export function saveBatchWizardConfig(c: BatchWizardPersistedConfig, mode: BatchWizardMode = 'text'): void {
  try {
    sessionStorage.setItem(batchWizardStorageKey(mode), JSON.stringify(c));
  } catch {
    /* ignore */
  }
}
