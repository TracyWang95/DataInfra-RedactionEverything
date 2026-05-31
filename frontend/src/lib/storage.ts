// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { STORAGE_KEYS } from '@/constants/storage-keys';

function currentOwnerId(): string | null {
  try {
    const value = localStorage.getItem(STORAGE_KEYS.CURRENT_USER);
    return value && value.trim().length > 0 ? value.trim().toLowerCase() : null;
  } catch {
    return null;
  }
}

export function scopedStorageKey(key: string, ownerId?: string | null): string {
  const owner = (ownerId ?? currentOwnerId())?.trim().toLowerCase();
  return owner ? `${key}:${owner}` : key;
}

export function getStorageItem<T>(key: string, defaultValue: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw !== null ? (JSON.parse(raw) as T) : defaultValue;
  } catch {
    return defaultValue;
  }
}

export function getScopedStorageItem<T>(key: string, defaultValue: T, ownerId?: string | null): T {
  return getStorageItem(scopedStorageKey(key, ownerId), defaultValue);
}

export function setStorageItem<T>(key: string, value: T): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage full or unavailable — silently fail
  }
}

export function setScopedStorageItem<T>(key: string, value: T, ownerId?: string | null): void {
  setStorageItem(scopedStorageKey(key, ownerId), value);
}

export function removeStorageItem(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // Silently fail
  }
}

export function removeScopedStorageItem(key: string, ownerId?: string | null): void {
  removeStorageItem(scopedStorageKey(key, ownerId));
}
