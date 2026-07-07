// Copyright 2026 DataInfra-RedactionEverything Contributors

// ---------------------------------------------------------------------------
// Playground-local type definitions.
//
// These intentionally diverge from the shared types in `@/types/index.ts`.
// The shared types model the full server-side schema (used by history, batch,
// and API layers), while these playground types are slimmer, UI-oriented
// projections that match the playground's runtime needs:
//
//  - FileInfo: no `page_count`, `pages`, `content`, or `created_at` — the
//    playground only cares about the upload metadata.
//  - Entity: adds `source` and `coref_id` for provenance tracking; omits
//    `page`, `confidence`, and `replacement` which are managed elsewhere.
//  - BoundingBox: `page` is optional (single-page playground default);
//    adds `confidence` — differs from the required `page` in the shared type.
//  - EntityTypeConfig: lighter shape without full taxonomy metadata,
//    `examples`, or `tag_template` used only in settings/admin views.
// ---------------------------------------------------------------------------

export interface FileInfo {
  file_id: string;
  filename: string;
  file_size: number;
  file_type?: string;
  is_scanned?: boolean;
  page_count?: number;
  pages?: string[];
}

export interface Entity {
  id: string;
  text: string;
  type: string;
  start: number;
  end: number;
  selected: boolean;
  source: 'regex' | 'llm' | 'manual' | 'has';
  coref_id?: string | null;
  page?: number;
}

export interface BoundingBox {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  page?: number;
  type: string;
  text?: string;
  selected: boolean;
  confidence?: number;
  source?: 'ocr_has' | 'visual_features' | 'manual';
  evidence_source?: 'ocr_has' | 'visual_feature_model' | 'local_fallback' | 'manual';
  source_detail?: string;
  warnings?: string[];
}

export interface EntityTypeConfig {
  id: string;
  name: string;
  data_domain?: string;
  generic_target?: string | null;
  entity_type_ids?: string[];
  linkage_groups?: string[];
  coref_enabled?: boolean;
  default_enabled?: boolean;
  color: string;
  description?: string;
  regex_pattern?: string | null;
  use_llm?: boolean;
  enabled?: boolean;
  order?: number;
}

export interface VisionTypeConfig {
  id: string;
  name: string;
  color: string;
  description?: string;
  enabled?: boolean;
  order?: number;
  rules?: string[];
  negative_prompt_enabled?: boolean;
  negative_prompt?: string | null;
  pipelineMode?: 'ocr_has' | 'visual_features';
}

export interface PipelineConfig {
  mode: 'ocr_has' | 'visual_features';
  name: string;
  description: string;
  enabled: boolean;
  types: VisionTypeConfig[];
}

export type Stage = 'upload' | 'preview' | 'result';

// ---------------------------------------------------------------------------
// API response shapes used by playground hooks / utils
// ---------------------------------------------------------------------------

/** POST /api/v1/files/upload */
export interface UploadResponse {
  file_id: string;
  filename: string;
  file_size: number;
  file_type: string;
}

/** GET /api/v1/files/:id/parse */
export interface ParseResponse {
  is_scanned?: boolean;
  content?: string;
  page_count?: number;
  file_type?: string;
  pages?: string[];
}

/** POST /api/v1/files/:id/ner/hybrid */
export interface NerResponse {
  entities: Array<Record<string, unknown>>;
}

/** POST /api/v1/redaction/execute */
export interface RedactionResult {
  entity_map: Record<string, string>;
  redacted_count: number;
}

/** POST /api/v1/redaction/:id/vision */
export interface VisionDetectionResponse {
  bounding_boxes?: Array<Record<string, unknown>>;
  result_image?: string;
}
