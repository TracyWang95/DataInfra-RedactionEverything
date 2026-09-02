// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { API_PREFIX, BATCH_TIMEOUT, authFetch, downloadFile, get, post } from './api-client';

export type DicomProfile =
  | 'basic'
  | 'research_strict'
  | 'longitudinal'
  | 'longitudinal_research'
  | 'internal_pseudonymized'
  | 'ai_training';

export type DicomCapabilities = {
  ingest: string[];
  profiles: DicomProfile[];
  hierarchy: string[];
  preview: { format: string; multi_frame: boolean; windowing: boolean };
  pixel_redaction: {
    enabled: boolean;
    automatic: boolean;
    detector: string;
    fail_closed: boolean;
    clean_pixel_data_code: string;
  };
  batch_anonymize: boolean;
  dicomweb: { qido_rs: boolean; wado_rs: boolean; stow_rs: boolean };
  limits: {
    upload_bytes: number;
    archive_expanded_bytes: number;
    archive_entries: number;
  };
};

export type DicomRiskSeverity = 'critical' | 'high' | 'medium' | 'low' | 'info';
export type DicomRiskStatus = 'open' | 'confirmed' | 'resolved' | 'accepted';

export type DicomRiskSummary = {
  critical: number;
  high: number;
  medium: number;
  low: number;
  unresolved: number;
  blocking: number;
};

export type DicomInstance = {
  instance_id: string;
  sop_instance_uid?: string;
  sop_class_uid?: string;
  instance_number?: number | null;
  frame_count?: number;
  transfer_syntax_uid?: string;
  rows?: number | null;
  columns?: number | null;
  preview_available?: boolean;
};

export type DicomSeries = {
  series_id: string;
  series_instance_uid?: string;
  series_number?: number | null;
  description?: string | null;
  modality?: string | null;
  instance_count: number;
  instances?: DicomInstance[];
};

export type DicomStudy = {
  study_id: string;
  study_instance_uid?: string;
  patient_pseudonym?: string | null;
  study_date?: string | null;
  description?: string | null;
  modalities: string[];
  series_count: number;
  instance_count: number;
  status: string;
  profile?: DicomProfile;
  risk_summary: DicomRiskSummary;
  preflight_version?: number | null;
  latest_job?: DicomJob;
  series?: DicomSeries[];
};

export type DicomRisk = {
  risk_id: string;
  category: string;
  severity: DicomRiskSeverity;
  status: DicomRiskStatus;
  message: string;
  location?: string | null;
  tag?: string | null;
  keyword?: string | null;
  value_preview?: string | null;
  instance_id?: string | null;
  frame?: number | null;
  resolution?: string | null;
  note?: string | null;
};

export type DicomMetadataEntry = {
  tag: string;
  keyword?: string | null;
  vr?: string | null;
  original_value?: string | null;
  output_value?: string | null;
  action: string;
  risk_level?: DicomRiskSeverity | null;
  source?: 'dataset' | 'file_meta' | 'preamble' | 'private' | string;
};

export type DicomIngestResponse = {
  ingest_id: string;
  profile: DicomProfile;
  study_count: number;
  series_count: number;
  instance_count: number;
  studies: DicomStudy[];
  risks_summary: DicomRiskSummary;
};

export type DicomPreflightResponse = {
  study_id: string;
  profile: DicomProfile;
  preflight_version: number;
  export_allowed: boolean;
  risk_summary: DicomRiskSummary;
  risks?: DicomRisk[];
  planned_actions?: Record<string, number>;
};

export type DicomJob = {
  job_id: string;
  batch_id?: string | null;
  study_id: string;
  status: 'queued' | 'running' | 'review_required' | 'completed' | 'failed' | string;
  progress?: number;
  message?: string | null;
  export_allowed?: boolean;
  error?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type DicomBatch = {
  batch_id: string;
  status: string;
  progress?: number;
  jobs: DicomJob[];
};

export type DicomReport = {
  job_id: string;
  study_id: string;
  profile: DicomProfile;
  patient_identity_removed?: boolean;
  deidentification_method?: string;
  source_instance_count: number;
  output_instance_count: number;
  validation_status: string;
  risk_summary: DicomRiskSummary;
  actions?: Record<string, number>;
  warnings?: string[];
};

export function getDicomCapabilities(): Promise<DicomCapabilities> {
  return get<Record<string, unknown>>('/dicom/capabilities').then((response) => {
    const dicomweb = asRecord(response.dicomweb);
    const limits = asRecord(response.limits);
    const preview = asRecord(response.preview);
    const pixelRedaction = asRecord(response.pixel_redaction);
    return {
      ingest: asArray(response.ingest).map(String),
      profiles: asArray(response.profiles).map(normalizeProfile),
      hierarchy: asArray(response.hierarchy).map(String),
      preview: {
        format: String(preview.format ?? 'image/png'),
        multi_frame: Boolean(preview.multi_frame),
        windowing: Boolean(preview.windowing),
      },
      pixel_redaction: {
        enabled: Boolean(pixelRedaction.enabled),
        automatic: Boolean(pixelRedaction.automatic),
        detector: String(pixelRedaction.detector ?? ''),
        fail_closed: Boolean(pixelRedaction.fail_closed),
        clean_pixel_data_code: String(pixelRedaction.clean_pixel_data_code ?? ''),
      },
      batch_anonymize: Boolean(response.batch_anonymize),
      dicomweb: {
        qido_rs: Boolean(dicomweb.qido_rs),
        wado_rs: Boolean(dicomweb.wado_rs),
        stow_rs: Boolean(dicomweb.stow_rs),
      },
      limits: {
        upload_bytes: numeric(limits.upload_bytes),
        archive_expanded_bytes: numeric(limits.archive_expanded_bytes),
        archive_entries: numeric(limits.archive_entries),
      },
    };
  });
}

function dicomUploadName(file: File): string {
  return file.webkitRelativePath || file.name;
}

export async function ingestDicom(input: {
  files?: File[];
  archive?: File;
  profile: DicomProfile;
  idempotencyKey?: string;
}): Promise<DicomIngestResponse> {
  const form = new FormData();
  form.append('profile', input.profile);
  // Preserve browser folder-upload paths so a DICOMDIR can still resolve its
  // referenced instances after multipart ingestion.
  input.files?.forEach((file) => form.append('files', file, dicomUploadName(file)));
  if (input.archive) form.append('archive', input.archive);
  const response = await post<Record<string, unknown>>('/dicom/ingest', form, {
    timeout: BATCH_TIMEOUT,
    headers: input.idempotencyKey ? { 'X-Idempotency-Key': input.idempotencyKey } : undefined,
  });
  return normalizeIngest(response);
}

export function listDicomStudies(params?: {
  status?: string;
  modality?: string;
  cursor?: string;
  limit?: number;
}): Promise<{ studies: DicomStudy[]; next_cursor?: string | null }> {
  return get<Record<string, unknown>>('/dicom/studies', { params }).then((response) => ({
    studies: asArray(response.studies ?? response.items).map(normalizeStudy),
    next_cursor: optionalString(response.next_cursor ?? response.next_offset),
  }));
}

export function getDicomStudy(studyId: string): Promise<DicomStudy> {
  return get<Record<string, unknown>>(`/dicom/studies/${encodeURIComponent(studyId)}`).then(
    normalizeStudy,
  );
}

export async function getDicomMetadata(
  studyId: string,
): Promise<{ study_id: string; entries: DicomMetadataEntry[] }> {
  const entries: DicomMetadataEntry[] = [];
  const limit = 1000;
  let offset = 0;
  let resolvedStudyId = studyId;

  while (true) {
    const response = await get<Record<string, unknown>>(
      `/dicom/studies/${encodeURIComponent(studyId)}/metadata`,
      { params: { offset, limit } },
    );
    resolvedStudyId = String(response.study_id ?? resolvedStudyId);
    const page = normalizeMetadata(response);
    entries.push(...page);

    const total = optionalNumber(response.total);
    const hasPagedEntries = Array.isArray(response.entries);
    if (!hasPagedEntries || total == null || entries.length >= total || page.length === 0) break;
    offset += page.length;
  }

  return { study_id: resolvedStudyId, entries };
}

export function getDicomRisks(
  studyId: string,
): Promise<{ study_id: string; summary: DicomRiskSummary; risks: DicomRisk[] }> {
  return get<Record<string, unknown>>(`/dicom/studies/${encodeURIComponent(studyId)}/risks`).then(
    (response) => ({
      study_id: String(response.study_id ?? studyId),
      summary: normalizeRiskSummary(response.summary),
      risks: asArray(response.risks ?? response.items).map(normalizeRisk),
    }),
  );
}

export async function getDicomPreviewUrl(input: {
  studyId: string;
  instanceId: string;
  frame?: number;
  windowCenter?: number;
  windowWidth?: number;
}): Promise<string> {
  const query = new URLSearchParams({ frame: String(input.frame ?? 0) });
  if (input.windowCenter != null) query.set('window_center', String(input.windowCenter));
  if (input.windowWidth != null) query.set('window_width', String(input.windowWidth));
  const response = await authFetch(
    `${API_PREFIX}/dicom/studies/${encodeURIComponent(input.studyId)}/instances/${encodeURIComponent(input.instanceId)}/preview?${query}`,
  );
  if (!response.ok) {
    let message = `DICOM preview failed: HTTP ${response.status}`;
    try {
      const error = (await response.json()) as { message?: string; detail?: string };
      message = error.message ?? error.detail ?? message;
    } catch {
      // The endpoint can return a plain-text decoder error.
    }
    throw new Error(message);
  }
  return URL.createObjectURL(await response.blob());
}

export function preflightDicomStudy(
  studyId: string,
  payload: { profile: DicomProfile; options?: Record<string, unknown> },
): Promise<DicomPreflightResponse> {
  return post<Record<string, unknown>>(
    `/dicom/studies/${encodeURIComponent(studyId)}/preflight`,
    payload,
  ).then((response) => normalizePreflight(response, studyId, payload.profile));
}

export function reviewDicomStudy(
  studyId: string,
  decisions: Array<{ risk_id: string; resolution: 'resolved' | 'accepted'; note?: string }>,
): Promise<{ study_id: string; risk_summary: DicomRiskSummary; export_allowed: boolean }> {
  return post<Record<string, unknown>>(`/dicom/studies/${encodeURIComponent(studyId)}/review`, {
    decisions,
  }).then((response) => {
    const summary = normalizeRiskSummary(response.risk_summary ?? response.summary);
    return {
      study_id: String(response.study_id ?? studyId),
      risk_summary: summary,
      export_allowed:
        response.export_allowed == null ? summary.blocking === 0 : Boolean(response.export_allowed),
    };
  });
}

export function anonymizeDicomStudy(
  studyId: string,
  payload: {
    profile: DicomProfile;
    options?: Record<string, unknown>;
    expected_preflight_version: number;
  },
  idempotencyKey: string,
): Promise<DicomJob> {
  return post<Record<string, unknown>>(
    `/dicom/studies/${encodeURIComponent(studyId)}/anonymize`,
    payload,
    { headers: { 'X-Idempotency-Key': idempotencyKey } },
  ).then((response) => normalizeJob(response, studyId));
}

export function getDicomJob(jobId: string): Promise<DicomJob> {
  return get<Record<string, unknown>>(`/dicom/jobs/${encodeURIComponent(jobId)}`).then((response) =>
    normalizeJob(response),
  );
}

export function anonymizeDicomBatch(
  payload: {
    study_ids: string[];
    profile: DicomProfile;
    expected_preflight_versions: Record<string, number>;
    options?: Record<string, unknown>;
  },
  idempotencyKey: string,
): Promise<DicomBatch> {
  return post<Record<string, unknown>>('/dicom/anonymize', payload, {
    headers: { 'X-Idempotency-Key': idempotencyKey },
  }).then(normalizeBatch);
}

export function getDicomBatch(batchId: string): Promise<DicomBatch> {
  return get<Record<string, unknown>>(`/dicom/batches/${encodeURIComponent(batchId)}`).then(
    normalizeBatch,
  );
}

export function getDicomReport(jobId: string): Promise<DicomReport> {
  return get<Record<string, unknown>>(`/dicom/jobs/${encodeURIComponent(jobId)}/report`).then(
    (response) => normalizeReport(response, jobId),
  );
}

export function downloadDicomExport(jobId: string): Promise<void> {
  return downloadFile(
    `/api/v1/dicom/jobs/${encodeURIComponent(jobId)}/export`,
    `dicom-anonymized-${jobId}.zip`,
  );
}

export function downloadDicomBatchExport(batchId: string): Promise<void> {
  return downloadFile(
    `/api/v1/dicom/batches/${encodeURIComponent(batchId)}/export`,
    `dicom-anonymized-batch-${batchId}.zip`,
  );
}

export function releaseDicomPreviewUrl(url: string | null | undefined): void {
  if (url?.startsWith('blob:')) URL.revokeObjectURL(url);
}

function normalizeIngest(response: Record<string, unknown>): DicomIngestResponse {
  return {
    ingest_id: String(response.ingest_id ?? ''),
    profile: normalizeProfile(response.profile),
    study_count: numeric(response.study_count),
    series_count: numeric(response.series_count),
    instance_count: numeric(response.instance_count),
    studies: asArray(response.studies).map(normalizeStudy),
    risks_summary: normalizeRiskSummary(response.risks_summary),
  };
}

function normalizeStudy(raw: unknown): DicomStudy {
  const value = asRecord(raw);
  const studyId = String(value.study_id ?? value.id ?? '');
  const series = asArray(value.series).map(normalizeSeries);
  const riskCount = numeric(value.risk_count);
  const suppliedSummary = value.risk_summary ?? value.risks_summary;
  const riskSummary = suppliedSummary
    ? normalizeRiskSummary(suppliedSummary)
    : {
        critical: 0,
        high: riskCount,
        medium: 0,
        low: 0,
        unresolved: riskCount,
        blocking: riskCount,
      };
  return {
    study_id: studyId,
    study_instance_uid: optionalString(value.study_instance_uid),
    patient_pseudonym: optionalString(value.patient_pseudonym ?? value.subject_key),
    study_date: optionalString(value.study_date),
    description: optionalString(value.description ?? value.study_description),
    modalities: asArray(value.modalities).map(String),
    series_count: numeric(value.series_count, series.length),
    instance_count: numeric(
      value.instance_count,
      series.reduce((sum, item) => sum + item.instance_count, 0),
    ),
    status: String(value.status ?? 'unknown'),
    profile: value.profile ? normalizeProfile(value.profile) : undefined,
    risk_summary: riskSummary,
    preflight_version: optionalNumber(value.preflight_version),
    latest_job: value.latest_job
      ? normalizeJob(asRecord(value.latest_job), studyId)
      : undefined,
    series,
  };
}

function normalizeSeries(raw: unknown): DicomSeries {
  const value = asRecord(raw);
  const instances = asArray(value.instances).map(normalizeInstance);
  return {
    series_id: String(value.series_id ?? value.id ?? ''),
    series_instance_uid: optionalString(value.series_instance_uid),
    series_number: optionalNumber(value.series_number),
    description: optionalString(value.description ?? value.series_description),
    modality: optionalString(value.modality),
    instance_count: numeric(value.instance_count, instances.length),
    instances,
  };
}

function normalizeInstance(raw: unknown): DicomInstance {
  const value = asRecord(raw);
  return {
    instance_id: String(value.instance_id ?? value.id ?? ''),
    sop_instance_uid: optionalString(value.sop_instance_uid),
    sop_class_uid: optionalString(value.sop_class_uid),
    instance_number: optionalNumber(value.instance_number),
    frame_count: numeric(value.frame_count ?? value.number_of_frames, 1),
    transfer_syntax_uid: optionalString(value.transfer_syntax_uid),
    rows: optionalNumber(value.rows),
    columns: optionalNumber(value.columns),
    preview_available: Boolean(value.preview_available ?? value.previewable ?? true),
  };
}

function normalizeRisk(raw: unknown): DicomRisk {
  const value = asRecord(raw);
  const details = asRecord(value.details);
  return {
    risk_id: String(value.risk_id ?? value.id ?? ''),
    category: String(value.category ?? value.code ?? 'dicom'),
    severity: normalizeSeverity(value.severity),
    status: normalizeRiskStatus(value.status),
    message: String(value.message ?? value.code ?? 'DICOM risk'),
    location: optionalString(value.location ?? details.location ?? details.path),
    tag: optionalString(value.tag ?? details.tag),
    keyword: optionalString(value.keyword ?? details.keyword),
    value_preview: optionalString(value.value_preview ?? details.value_preview ?? details.value),
    instance_id: optionalString(value.instance_id ?? details.instance_id),
    frame: optionalNumber(value.frame ?? details.frame),
    resolution: optionalString(value.resolution),
    note: optionalString(value.note ?? value.review_note),
  };
}

function normalizePreflight(
  response: Record<string, unknown>,
  studyId: string,
  profile: DicomProfile,
): DicomPreflightResponse {
  const summary = normalizeRiskSummary(response.risks_summary ?? response.summary);
  return {
    study_id: String(response.study_id ?? studyId),
    profile: normalizeProfile(response.profile ?? profile),
    preflight_version: numeric(response.preflight_version, 1),
    export_allowed:
      response.export_allowed == null ? summary.blocking === 0 : Boolean(response.export_allowed),
    risk_summary: summary,
    risks: asArray(response.risks).map(normalizeRisk),
    planned_actions: asNumberRecord(asRecord(response.result).planned_actions),
  };
}

function normalizeJob(response: Record<string, unknown>, studyId = ''): DicomJob {
  const error = response.error;
  const errorRecord = asRecord(error);
  return {
    job_id: String(response.job_id ?? response.id ?? ''),
    batch_id: optionalString(response.batch_id),
    study_id: String(response.study_id ?? studyId),
    status: String(response.status ?? 'unknown'),
    progress: numeric(response.progress),
    message: optionalString(response.message),
    export_allowed: response.export_allowed == null ? undefined : Boolean(response.export_allowed),
    error:
      typeof error === 'string'
        ? error
        : optionalString(errorRecord.message ?? errorRecord.error_code),
    created_at: optionalString(response.created_at),
    updated_at: optionalString(response.updated_at),
  };
}

function normalizeBatch(response: Record<string, unknown>): DicomBatch {
  return {
    batch_id: String(response.batch_id ?? ''),
    status: String(response.status ?? 'unknown'),
    progress: numeric(response.progress),
    jobs: asArray(response.jobs).map((item) => normalizeJob(asRecord(item))),
  };
}

function normalizeReport(response: Record<string, unknown>, jobId: string): DicomReport {
  const validation = asRecord(response.validation);
  const deidentification = asRecord(response.deidentification);
  const outputCount = numeric(response.output_instance_count ?? validation.instance_count);
  return {
    job_id: String(response.job_id ?? jobId),
    study_id: String(response.study_id ?? ''),
    profile: normalizeProfile(response.profile),
    patient_identity_removed:
      String(
        response.patient_identity_removed ?? deidentification.patient_identity_removed ?? '',
      ).toUpperCase() === 'YES',
    deidentification_method: optionalString(
      response.deidentification_method ?? deidentification.deidentification_method,
    ),
    source_instance_count: numeric(response.source_instance_count, outputCount),
    output_instance_count: outputCount,
    validation_status: String(
      response.validation_status ??
        (validation.passed === true
          ? 'passed'
          : validation.passed === false
            ? 'failed'
            : 'unknown'),
    ),
    risk_summary: normalizeRiskSummary(response.risks_summary),
    actions: asNumberRecord(response.actions ?? deidentification.actions),
    warnings: asArray(response.warnings ?? validation.warnings).map(String),
  };
}

function normalizeMetadata(response: Record<string, unknown>): DicomMetadataEntry[] {
  if (Array.isArray(response.entries)) {
    return response.entries.map((item) => normalizeMetadataEntry(item, 'dataset'));
  }

  const entries: DicomMetadataEntry[] = [];
  appendMetadataEntries(entries, response.study_metadata, 'dataset');
  asArray(response.instances).forEach((item) => {
    const instance = asRecord(item);
    appendMetadataEntries(entries, instance.metadata, `instance:${String(instance.id ?? '')}`);
  });
  return entries;
}

function appendMetadataEntries(
  target: DicomMetadataEntry[],
  raw: unknown,
  fallbackSource: string,
): void {
  const values = asRecord(raw);
  Object.entries(values).forEach(([tag, item]) => {
    target.push(normalizeMetadataEntry({ ...asRecord(item), tag }, fallbackSource, item));
  });
}

function normalizeMetadataEntry(
  raw: unknown,
  fallbackSource: string,
  fallbackValue?: unknown,
): DicomMetadataEntry {
  const value = asRecord(raw);
  const original = value.original_value ?? value.value ?? fallbackValue;
  return {
    tag: String(value.tag ?? ''),
    keyword: optionalString(value.keyword ?? value.name),
    vr: optionalString(value.vr),
    original_value: displayValue(original),
    output_value: optionalString(value.output_value ?? value.replacement),
    action: String(value.action ?? 'inspect'),
    risk_level: value.risk_level ? normalizeSeverity(value.risk_level) : null,
    source: String(value.source ?? fallbackSource),
  };
}

function normalizeRiskSummary(raw: unknown): DicomRiskSummary {
  const value = asRecord(raw);
  const bySeverity = asRecord(value.by_severity);
  const critical = numeric(value.critical ?? bySeverity.critical);
  const high = numeric(value.high ?? bySeverity.high);
  return {
    critical,
    high,
    medium: numeric(value.medium ?? bySeverity.medium),
    low: numeric(value.low ?? bySeverity.low),
    unresolved: numeric(value.unresolved ?? value.open ?? value.blocking),
    blocking: value.blocking == null ? critical + high : numeric(value.blocking),
  };
}

function normalizeProfile(raw: unknown): DicomProfile {
  const value = String(raw ?? 'research_strict');
  if (value === 'basic') return 'basic';
  if (value === 'longitudinal') return 'longitudinal';
  if (value === 'longitudinal_research') return 'longitudinal_research';
  if (value === 'internal_pseudonymized') return 'internal_pseudonymized';
  if (value === 'ai_training') return 'ai_training';
  return 'research_strict';
}

function normalizeSeverity(raw: unknown): DicomRiskSeverity {
  const value = String(raw ?? 'medium').toLowerCase();
  return ['critical', 'high', 'medium', 'low', 'info'].includes(value)
    ? (value as DicomRiskSeverity)
    : 'medium';
}

function normalizeRiskStatus(raw: unknown): DicomRiskStatus {
  const value = String(raw ?? 'open').toLowerCase();
  if (value === 'resolved' || value === 'accepted' || value === 'confirmed') return value;
  return 'open';
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function numeric(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function optionalNumber(value: unknown): number | null {
  if (value == null || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function optionalString(value: unknown): string | undefined {
  if (value == null || value === '') return undefined;
  return String(value);
}

function displayValue(value: unknown): string | null {
  if (value == null || value === '') return null;
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function asNumberRecord(value: unknown): Record<string, number> | undefined {
  const record = asRecord(value);
  if (Object.keys(record).length === 0) return undefined;
  return Object.fromEntries(Object.entries(record).map(([key, item]) => [key, numeric(item)]));
}

export const __dicomContractAdapters = {
  dicomUploadName,
  normalizeStudy,
  normalizeRiskSummary,
  normalizeMetadata,
  normalizeJob,
};
