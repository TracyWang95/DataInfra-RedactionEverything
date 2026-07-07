// Copyright 2026 DataInfra-RedactionEverything Contributors

import { del, downloadFile, get, post, put } from './api-client';

export type StructuredSourceKind = 'csv' | 'xlsx' | 'jsonl' | 'sqlite' | 'mysql' | 'postgres';
export type StructuredPolicyAction =
  | 'keep'
  | 'mask'
  | 'hash'
  | 'tokenize'
  | 'generalize'
  | 'bucket'
  | 'suppress'
  | 'custom';
export type StructuredExportFormat = 'csv' | 'xlsx' | 'sqlite' | 'sql' | 'zip';

export type StructuredDataset = {
  id: string;
  source_id?: string | null;
  connection_id?: string | null;
  name: string;
  dataset_type: 'file_table' | 'db_table' | 'db_view' | 'sheet';
  source_kind: StructuredSourceKind;
  shape_kind:
    | 'flat_table'
    | 'relational_multi_table'
    | 'event_log'
    | 'wide_feature_table'
    | 'json_kv_table';
  schema_name?: string | null;
  table_name?: string | null;
  row_count_estimate?: number | null;
  column_count: number;
  schema: Array<Record<string, unknown>>;
  metadata: Record<string, unknown>;
  created_at: string;
  profile_updated_at?: string | null;
  policy_updated_at?: string | null;
  policy_reviewed_at?: string | null;
};

export type StructuredSource = {
  id: string;
  source_type: 'file' | 'db';
  kind: StructuredSourceKind;
  name: string;
  status: string;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type StructuredConnection = {
  id: string;
  engine: 'sqlite' | 'mysql' | 'postgres';
  display_name: string;
  last_test_status?: string | null;
  last_tested_at?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type StructuredColumnProfile = {
  name: string;
  data_type: string;
  null_rate: number;
  unique_rate: number;
  sample_values: unknown[];
  entity_type: string;
  risk_level: 'low' | 'medium' | 'high' | 'critical';
  confidence: number;
  reasons: string[];
  recommended_policy: StructuredPolicyAction;
};

export type StructuredProfile = {
  dataset_id: string;
  shape_kind: StructuredDataset['shape_kind'];
  row_count_estimate?: number | null;
  sampled_rows: number;
  columns: StructuredColumnProfile[];
  semantic_inference?: {
    engine?: string;
    status?: string;
    duration_ms?: number;
    matched_columns?: number;
  };
};

export type StructuredColumnPolicy = {
  column: string;
  action: StructuredPolicyAction;
  entity_type: string;
  enabled: boolean;
  params: Record<string, unknown>;
};

export type StructuredPreview = {
  dataset_id: string;
  columns: string[];
  original_rows: Array<Record<string, unknown>>;
  redacted_rows: Array<Record<string, unknown>>;
  policy: StructuredColumnPolicy[];
};

export type StructuredJobResponse = {
  job: {
    id: string;
    status: string;
    title: string;
    nav_hints?: Record<string, unknown>;
  };
  datasets: StructuredDataset[];
};

export type StructuredConnectionPayload = {
  engine: 'sqlite' | 'mysql' | 'postgres';
  display_name?: string;
  host?: string;
  port?: number;
  database?: string;
  username?: string;
  password?: string;
  sqlite_path?: string;
};

export async function uploadStructuredFile(file: File): Promise<{
  source: StructuredSource;
  datasets: StructuredDataset[];
}> {
  const form = new FormData();
  form.append('file', file);
  return post('/structured/files', form);
}

export function listStructuredDatasets(): Promise<{ datasets: StructuredDataset[] }> {
  return get('/structured/datasets');
}

export function profileStructuredDataset(datasetId: string): Promise<StructuredProfile> {
  return post(`/structured/datasets/${datasetId}/profile`);
}

export function getStructuredProfile(datasetId: string): Promise<StructuredProfile> {
  return get(`/structured/datasets/${datasetId}/profile`);
}

export function previewStructuredDataset(datasetId: string): Promise<StructuredPreview> {
  return get(`/structured/datasets/${datasetId}/preview`);
}

export function getStructuredPolicy(
  datasetId: string,
): Promise<{ dataset_id: string; columns: StructuredColumnPolicy[]; updated_at?: string | null }> {
  return get(`/structured/datasets/${datasetId}/policy`);
}

export function saveStructuredPolicy(
  datasetId: string,
  columns: StructuredColumnPolicy[],
): Promise<{ dataset_id: string; columns: StructuredColumnPolicy[]; updated_at?: string | null }> {
  return put(`/structured/datasets/${datasetId}/policy`, { columns });
}

export function createStructuredJob(payload: {
  title: string;
  dataset_ids: string[];
  export_format: StructuredExportFormat;
  skip_review?: boolean;
  auto_submit?: boolean;
}): Promise<StructuredJobResponse> {
  return post('/structured/jobs', payload);
}

export function downloadStructuredJob(jobId: string): Promise<void> {
  return downloadFile(`/api/v1/structured/jobs/${jobId}/export`, `structured-${jobId}.zip`);
}

export function testStructuredConnection(payload: StructuredConnectionPayload): Promise<{
  ok: boolean;
  message: string;
  engine: string;
  dataset_count: number;
}> {
  return post('/structured/connections/test', payload);
}

export function createStructuredConnection(
  payload: StructuredConnectionPayload,
): Promise<StructuredConnection> {
  return post('/structured/connections', payload);
}

export function listStructuredConnections(): Promise<StructuredConnection[]> {
  return get('/structured/connections');
}

export function deleteStructuredConnection(
  connectionId: string,
): Promise<{ id: string; deleted: boolean }> {
  return del(`/structured/connections/${connectionId}`);
}

export function deleteStructuredDataset(
  datasetId: string,
): Promise<{ id: string; deleted: boolean }> {
  return del(`/structured/datasets/${encodeURIComponent(datasetId)}`);
}

export function discoverStructuredConnectionDatasets(
  connectionId: string,
): Promise<{ datasets: StructuredDataset[] }> {
  return get(`/structured/connections/${connectionId}/datasets`);
}

export function registerStructuredConnectionDatasets(
  connectionId: string,
  datasets: Array<{ schema_name?: string | null; table_name?: string | null; name?: string | null }>,
): Promise<{ datasets: StructuredDataset[] }> {
  return post(`/structured/connections/${connectionId}/datasets`, { datasets });
}
