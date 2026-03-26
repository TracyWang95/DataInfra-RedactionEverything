/**
 * 跨页面同步「当前选用的命名预设」：Playground / 批量向导 / 识别项配置
 * 与 /api/v1/presets 数据配合使用，仅存 ID，不重复存配置体。
 */
const K_TEXT = 'datainfraRedaction:activePresetTextId';
const K_TEXT_LEGACY = 'legalRedaction:activePresetTextId';
const K_VISION = 'datainfraRedaction:activePresetVisionId';
const K_VISION_LEGACY = 'legalRedaction:activePresetVisionId';

const ACTIVE_PRESET_EVENT = 'datainfra-redaction-active-preset';

export function getActivePresetTextId(): string | null {
  try {
    const a = localStorage.getItem(K_TEXT);
    if (a && a.length > 0) return a;
    const b = localStorage.getItem(K_TEXT_LEGACY);
    return b && b.length > 0 ? b : null;
  } catch {
    return null;
  }
}

export function setActivePresetTextId(id: string | null): void {
  try {
    if (id) {
      localStorage.setItem(K_TEXT, id);
      localStorage.setItem(K_TEXT_LEGACY, id);
    } else {
      localStorage.removeItem(K_TEXT);
      localStorage.removeItem(K_TEXT_LEGACY);
    }
    window.dispatchEvent(new CustomEvent(ACTIVE_PRESET_EVENT));
  } catch {
    /* ignore */
  }
}

export function getActivePresetVisionId(): string | null {
  try {
    const a = localStorage.getItem(K_VISION);
    if (a && a.length > 0) return a;
    const b = localStorage.getItem(K_VISION_LEGACY);
    return b && b.length > 0 ? b : null;
  } catch {
    return null;
  }
}

export function setActivePresetVisionId(id: string | null): void {
  try {
    if (id) {
      localStorage.setItem(K_VISION, id);
      localStorage.setItem(K_VISION_LEGACY, id);
    } else {
      localStorage.removeItem(K_VISION);
      localStorage.removeItem(K_VISION_LEGACY);
    }
    window.dispatchEvent(new CustomEvent(ACTIVE_PRESET_EVENT));
  } catch {
    /* ignore */
  }
}
