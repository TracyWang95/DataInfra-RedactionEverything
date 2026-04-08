// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

/** Centralized localStorage / sessionStorage key constants */
export const STORAGE_KEYS = {
  AUTH_TOKEN: 'auth_token',
  LOCALE: 'locale',
  ONBOARDING_COMPLETED: 'onboarding_completed',
  OCR_HAS_TYPES: 'ocrHasTypes',
  HAS_IMAGE_TYPES: 'hasImageTypes',
  /** @deprecated legacy key, kept for migration reads only */
  GLM_VISION_TYPES: 'glmVisionTypes',
  ACTIVE_PRESET_TEXT_ID: 'datainfraRedaction:activePresetTextId',
  ACTIVE_PRESET_TEXT_ID_LEGACY: 'legalRedaction:activePresetTextId',
  ACTIVE_PRESET_VISION_ID: 'datainfraRedaction:activePresetVisionId',
  ACTIVE_PRESET_VISION_ID_LEGACY: 'legalRedaction:activePresetVisionId',
  BATCH_WIZ_FURTHEST_PREFIX: 'lr_batch_wiz_furthest_',
} as const;
