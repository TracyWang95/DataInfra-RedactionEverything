// Copyright 2026 DataInfra-RedactionEverything Contributors

/** Centralized localStorage / sessionStorage key constants */
export const STORAGE_KEYS = {
  AUTH_TOKEN: 'auth_token',
  CURRENT_USER: 'datainfraRedaction:currentUser',
  LOCALE: 'locale',
  ONBOARDING_COMPLETED: 'onboarding_completed',
  OCR_HAS_TYPES: 'ocrHasTypes',
  VISUAL_FEATURE_TYPES: 'visualFeatureTypes',
  VISION_SELECTION_SIGNATURE: 'datainfraRedaction:visionSelectionSignature',
  ACTIVE_PRESET_TEXT_ID: 'datainfraRedaction:activePresetTextId',
  ACTIVE_PRESET_TEXT_ID_LEGACY: 'legalRedaction:activePresetTextId',
  ACTIVE_PRESET_VISION_ID: 'datainfraRedaction:activePresetVisionId',
  ACTIVE_PRESET_VISION_ID_LEGACY: 'legalRedaction:activePresetVisionId',
  BATCH_WIZ_FURTHEST_PREFIX: 'lr_batch_wiz_furthest_',
} as const;
