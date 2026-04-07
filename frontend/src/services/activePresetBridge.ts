// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0


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
    return;
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
    return;
  }
}
