/**
 * 识别配置预设 API（与后端 /api/v1/presets 对齐）
 */
const BASE = '/api/v1';

export type ReplacementMode = 'structured' | 'smart' | 'mask';

/** text=仅文本；vision=仅图像视觉链；full=组合（旧数据默认） */
export type PresetKind = 'text' | 'vision' | 'full';

export interface RecognitionPreset {
  id: string;
  name: string;
  /** 缺省视为 full（旧数据） */
  kind?: PresetKind;
  selectedEntityTypeIds: string[];
  ocrHasTypes: string[];
  hasImageTypes: string[];
  replacementMode: ReplacementMode;
  created_at: string;
  updated_at: string;
}

export interface PresetPayload {
  name: string;
  kind: PresetKind;
  selectedEntityTypeIds: string[];
  ocrHasTypes: string[];
  hasImageTypes: string[];
  replacementMode: ReplacementMode;
}

/** 该预设是否包含可应用的文本链配置 */
export function presetAppliesText(p: RecognitionPreset): boolean {
  const k = p.kind ?? 'full';
  return k === 'text' || k === 'full';
}

/** 该预设是否包含可应用的视觉链配置 */
export function presetAppliesVision(p: RecognitionPreset): boolean {
  const k = p.kind ?? 'full';
  return k === 'vision' || k === 'full';
}

const PRESETS_404_HINT =
  '预设接口返回 404：当前连接的后端未提供 /api/v1/presets。请在 backend 目录重启服务（例如：python -m uvicorn app.main:app --host 0.0.0.0 --port 8000），并确认已更新到包含 app/api/presets.py 的版本。';

async function parseJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const err = await res.json();
      msg = typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail ?? err);
    } catch {
      /* ignore */
    }
    if (res.status === 404 && msg === 'Not Found') {
      msg = PRESETS_404_HINT;
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export async function fetchPresets(): Promise<RecognitionPreset[]> {
  const res = await fetch(`${BASE}/presets`);
  const data = await parseJson<any>(res);
  // 兼容分页响应 { presets: [...] } 和旧的直接数组格式
  return Array.isArray(data) ? data : Array.isArray(data?.presets) ? data.presets : [];
}

export async function createPreset(body: PresetPayload): Promise<RecognitionPreset> {
  const res = await fetch(`${BASE}/presets`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return parseJson<RecognitionPreset>(res);
}

export async function updatePreset(id: string, patch: Partial<PresetPayload>): Promise<RecognitionPreset> {
  const res = await fetch(`${BASE}/presets/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  return parseJson<RecognitionPreset>(res);
}

export async function deletePreset(id: string): Promise<void> {
  const res = await fetch(`${BASE}/presets/${id}`, { method: 'DELETE' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const detail = typeof err.detail === 'string' ? err.detail : '';
    if (res.status === 404 && detail === 'Not Found') {
      throw new Error(PRESETS_404_HINT);
    }
    throw new Error(detail || `HTTP ${res.status}`);
  }
}
