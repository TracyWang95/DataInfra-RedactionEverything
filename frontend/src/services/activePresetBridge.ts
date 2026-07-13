// Copyright 2026 DataInfra-RedactionEverything Contributors

import { scopedStorageKey } from '@/lib/storage';

const K_TEXT = 'datainfraRedaction:activePresetTextId';
const K_TEXT_LEGACY = 'legalRedaction:activePresetTextId';
const K_VISION = 'datainfraRedaction:activePresetVisionId';
const K_VISION_LEGACY = 'legalRedaction:activePresetVisionId';

const ACTIVE_PRESET_EVENT = 'datainfra-redaction-active-preset';

export function getActivePresetTextId(): string | null {
  try {
    const scoped = scopedStorageKey(K_TEXT);
    const a = localStorage.getItem(scoped);
    if (a && a.length > 0) return a;
    if (scoped !== K_TEXT) return null;
    const b = localStorage.getItem(K_TEXT_LEGACY);
    return b && b.length > 0 ? b : null;
  } catch {
    return null;
  }
}

export function setActivePresetTextId(id: string | null): void {
  try {
    const scoped = scopedStorageKey(K_TEXT);
    if (id) {
      localStorage.setItem(scoped, id);
    } else {
      localStorage.removeItem(scoped);
      if (scoped === K_TEXT) localStorage.removeItem(K_TEXT_LEGACY);
    }
    window.dispatchEvent(new CustomEvent(ACTIVE_PRESET_EVENT));
  } catch {
    return;
  }
}

export function getActivePresetVisionId(): string | null {
  try {
    const scoped = scopedStorageKey(K_VISION);
    const a = localStorage.getItem(scoped);
    if (a && a.length > 0) return a;
    if (scoped !== K_VISION) return null;
    const b = localStorage.getItem(K_VISION_LEGACY);
    return b && b.length > 0 ? b : null;
  } catch {
    return null;
  }
}

export function setActivePresetVisionId(id: string | null): void {
  try {
    const scoped = scopedStorageKey(K_VISION);
    if (id) {
      localStorage.setItem(scoped, id);
    } else {
      localStorage.removeItem(scoped);
      if (scoped === K_VISION) localStorage.removeItem(K_VISION_LEGACY);
    }
    window.dispatchEvent(new CustomEvent(ACTIVE_PRESET_EVENT));
  } catch {
    return;
  }
}
