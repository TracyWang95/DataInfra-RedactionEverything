// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

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
//  - EntityTypeConfig: lighter shape without `category`, `examples`,
//    `tag_template`, or `risk_level` used only in settings/admin views.
// ---------------------------------------------------------------------------

export interface FileInfo {
  file_id: string;
  filename: string;
  file_size: number;
  file_type?: string;
  is_scanned?: boolean;
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
  source?: 'ocr_has' | 'has_image' | 'manual';
}

export interface EntityTypeConfig {
  id: string;
  name: string;
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
}

export interface PipelineConfig {
  mode: 'ocr_has' | 'has_image';
  name: string;
  description: string;
  enabled: boolean;
  types: VisionTypeConfig[];
}

export type Stage = 'upload' | 'preview' | 'result';
