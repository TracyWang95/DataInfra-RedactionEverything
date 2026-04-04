/**
 * Playground shared utility functions
 */
import type { Entity, BoundingBox } from './types';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function safeJson<T = any>(res: Response): Promise<T> {
  try {
    return await res.json();
  } catch {
    throw new Error('服务端返回了非 JSON 响应');
  }
}

/** Clamp popover anchor within the content canvas visible area */
export function clampPopoverInCanvas(
  anchorRect: DOMRect,
  canvasRect: DOMRect,
  popoverWidth: number,
  popoverHeight: number
): { left: number; top: number } {
  const margin = 8;
  const maxW = Math.max(120, Math.min(popoverWidth, canvasRect.width - 2 * margin));
  const maxH = Math.max(80, Math.min(popoverHeight, canvasRect.height - 2 * margin));
  const cx = anchorRect.left + anchorRect.width / 2;
  let left = cx - maxW / 2;
  left = Math.max(canvasRect.left + margin, Math.min(left, canvasRect.right - margin - maxW));

  let top = anchorRect.top - margin - maxH;
  if (top < canvasRect.top + margin) {
    top = anchorRect.bottom + margin;
  }
  if (top + maxH > canvasRect.bottom - margin) {
    top = Math.max(canvasRect.top + margin, canvasRect.bottom - margin - maxH);
  }

  return { left, top };
}

/** Preview entity mark style by source */
export function previewEntityMarkStyle(entity: Entity): React.CSSProperties {
  const base: React.CSSProperties = (() => {
    switch (entity.source) {
      case 'regex':
        return { backgroundColor: 'rgba(0, 122, 255, 0.09)', color: '#0a4a8c' };
      case 'llm':
        return { backgroundColor: 'rgba(52, 199, 89, 0.09)', color: '#0d5c2f' };
      case 'manual':
        return { backgroundColor: 'rgba(175, 82, 222, 0.11)', color: '#5c2d7a' };
      case 'has':
      default:
        return { backgroundColor: 'rgba(175, 82, 222, 0.11)', color: '#5c2d7a' };
    }
  })();
  if (!entity.selected) {
    return { ...base, opacity: 0.5, filter: 'saturate(0.55)' };
  }
  return base;
}

/** Hover ring class consistent with sidebar selection semantics */
export function previewEntityHoverRingClass(source: Entity['source']): string {
  switch (source) {
    case 'regex':
      return 'hover:ring-[#007AFF]/25';
    case 'llm':
      return 'hover:ring-[#34C759]/25';
    case 'manual':
      return 'hover:ring-[#AF52DE]/25';
    case 'has':
    default:
      return 'hover:ring-[#AF52DE]/25';
  }
}

export function getModePreview(mode: string, sampleEntity?: Entity) {
  const name = sampleEntity?.text || '张三';
  switch (mode) {
    case 'smart':
      return `${name} → [当事人一]`;
    case 'mask':
      return `${name} → ${name[0]}${'*'.repeat(Math.max(name.length - 1, 1))}`;
    case 'structured':
      return `${name} → <人物[001].个人.姓名>`;
    default:
      return '';
  }
}

export async function authBlobUrl(url: string, mime?: string): Promise<string> {
  const token = localStorage.getItem('auth_token');
  if (!token) return url;
  const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) {
    throw new Error(`加载文件失败: ${res.status}`);
  }
  const buf = await res.arrayBuffer();
  const blob = mime ? new Blob([buf], { type: mime }) : new Blob([buf]);
  return URL.createObjectURL(blob);
}

/** Vision detection timeout */
export const VISION_FETCH_TIMEOUT_MS = 400_000;

export async function runVisionDetection(
  fileId: string,
  ocrHasTypes: string[],
  hasImageTypes: string[]
): Promise<{ boxes: BoundingBox[]; resultImage?: string }> {
  if (import.meta.env.DEV) {
    console.log('[Vision] 发送识别请求:', { ocrHasTypes, hasImageTypes });
  }

  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), VISION_FETCH_TIMEOUT_MS);

  let res: Response;
  try {
    res = await fetch(`/api/v1/redaction/${fileId}/vision?page=1`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        selected_ocr_has_types: ocrHasTypes,
        selected_has_image_types: hasImageTypes,
      }),
      signal: controller.signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') {
      throw new Error(
        '图像识别超时（超过 3 分钟）。若 Paddle 在 CPU 上跑会很慢，可换更小图片或安装 paddle GPU 版加速。'
      );
    }
    throw e;
  } finally {
    window.clearTimeout(timer);
  }

  if (!res.ok) {
    throw new Error('图像识别失败');
  }

  const data = await safeJson(res);
  const boxes = (data.bounding_boxes || []).map((b: Record<string, unknown>, idx: number) => ({
    ...b,
    id: b.id || `bbox_${idx}`,
    selected: true,
  }));
  return { boxes, resultImage: data.result_image };
}

/** Compute entity type statistics */
export function computeEntityStats(entities: Entity[]): Record<string, { total: number; selected: number }> {
  const stats: Record<string, { total: number; selected: number }> = {};
  entities.forEach(e => {
    if (!stats[e.type]) stats[e.type] = { total: 0, selected: 0 };
    stats[e.type].total++;
    if (e.selected) stats[e.type].selected++;
  });
  return stats;
}
