// Copyright 2026 DataInfra-RedactionEverything Contributors

import type { BatchRow } from '../types';
import type {
  BatchExportReport,
  BatchExportReportFileDeliveryStatus,
  BatchExportReportSummaryDeliveryStatus,
  BatchExportReportVisualEvidence,
  BatchExportReportVisualReview,
} from '@/types';

export type {
  BatchExportReport,
  BatchExportReportFile,
  BatchExportReportFileDeliveryStatus,
  BatchExportReportSummary,
  BatchExportReportSummaryDeliveryStatus,
  BatchExportReportVisualEvidence,
  BatchExportReportVisualReview,
  JobExportReportJob,
  JobExportReportRedactedZip,
  JobExportReportZipSkipped,
} from '@/types';

export type BatchExportVisualEvidenceSource = 'visualFeature' | 'fallback' | 'ocrHas' | 'table';

export interface BatchExportVisualEvidenceEntry {
  key: BatchExportVisualEvidenceSource;
  count: number;
}

export const BATCH_EXPORT_BLOCKING_REASONS = {
  failed: 'failed',
  missingRedactedOutput: 'missing_redacted_output',
  reviewNotConfirmed: 'review_not_confirmed',
} as const;

export const BATCH_EXPORT_DELIVERY_STATUS = {
  readyForDelivery: 'ready_for_delivery',
  actionRequired: 'action_required',
  noSelection: 'no_selection',
  notSelected: 'not_selected',
} as const;

export function isBatchRowReadyForDelivery(
  row: Pick<BatchRow, 'analyzeStatus' | 'has_output' | 'reviewConfirmed'>,
): boolean {
  return row.analyzeStatus !== 'failed' && Boolean(row.has_output) && row.reviewConfirmed === true;
}

function countByStatus(rows: readonly BatchRow[]): Record<string, number> {
  return rows.reduce<Record<string, number>>((acc, row) => {
    acc[row.analyzeStatus] = (acc[row.analyzeStatus] ?? 0) + 1;
    return acc;
  }, {});
}

function normalizeCount(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

function recordCount(record: Record<string, number> | undefined, key: string): number {
  return normalizeCount(record?.[key]);
}

function recordCountIncluding(
  record: Record<string, number> | undefined,
  pattern: string,
): number {
  if (!record) return 0;
  return Object.entries(record).reduce(
    (sum, [key, count]) => (key.includes(pattern) ? sum + normalizeCount(count) : sum),
    0,
  );
}

function firstPositiveCount(values: readonly number[]): number {
  return values.find((value) => value > 0) ?? 0;
}

export function buildBatchExportVisualEvidenceEntries(
  evidence?: BatchExportReportVisualEvidence | null,
): BatchExportVisualEvidenceEntry[] {
  if (!evidence) return [];

  const fallbackCount = firstPositiveCount([
    normalizeCount(evidence.local_fallback),
    normalizeCount(evidence.fallback_detector),
    recordCount(evidence.evidence_source_counts, 'local_fallback'),
    recordCountIncluding(evidence.source_detail_counts, 'fallback'),
  ]);
  const visualFeatureCount = firstPositiveCount([
    normalizeCount(evidence.visual_feature_model),
    recordCount(evidence.evidence_source_counts, 'visual_feature_model'),
    Math.max(0, recordCount(evidence.source_counts, 'visual_features') - fallbackCount),
  ]);
  const ocrHasCount = firstPositiveCount([
    normalizeCount(evidence.ocr_has),
    recordCount(evidence.evidence_source_counts, 'ocr_has'),
    recordCount(evidence.source_counts, 'ocr_has'),
  ]);
  const tableCount = firstPositiveCount([
    normalizeCount(evidence.table_structure),
    recordCount(evidence.source_detail_counts, 'table_structure'),
    recordCount(evidence.source_counts, 'table_structure'),
    recordCountIncluding(evidence.warnings_by_key, 'table_structure'),
  ]);

  const entries: BatchExportVisualEvidenceEntry[] = [
    { key: 'visualFeature', count: visualFeatureCount },
    { key: 'fallback', count: fallbackCount },
    { key: 'ocrHas', count: ocrHasCount },
    { key: 'table', count: tableCount },
  ];

  return entries.filter((entry) => entry.count > 0);
}

function redactedExportSkipReason(row: Pick<BatchRow, 'has_output'>): string | null {
  return row.has_output ? null : BATCH_EXPORT_BLOCKING_REASONS.missingRedactedOutput;
}

function buildBlockingReasons(
  row: Pick<BatchRow, 'analyzeStatus' | 'has_output' | 'reviewConfirmed'>,
): string[] {
  return [
    ...(row.analyzeStatus === 'failed' ? [BATCH_EXPORT_BLOCKING_REASONS.failed] : []),
    ...(redactedExportSkipReason(row) ? [BATCH_EXPORT_BLOCKING_REASONS.missingRedactedOutput] : []),
    ...(row.reviewConfirmed !== true ? [BATCH_EXPORT_BLOCKING_REASONS.reviewNotConfirmed] : []),
  ];
}

function emptyVisualReview(): BatchExportReportVisualReview {
  return {
    blocking: false,
    review_hint: false,
    issue_count: 0,
    issue_pages: [],
    issue_pages_count: 0,
    issue_labels: [],
    by_issue: {},
  };
}

function summaryDeliveryStatus(
  selectedCount: number,
  actionRequiredCount: number,
): BatchExportReportSummaryDeliveryStatus {
  if (selectedCount === 0) return BATCH_EXPORT_DELIVERY_STATUS.noSelection;
  return actionRequiredCount === 0
    ? BATCH_EXPORT_DELIVERY_STATUS.readyForDelivery
    : BATCH_EXPORT_DELIVERY_STATUS.actionRequired;
}

function fileDeliveryStatus(
  selectedForExport: boolean,
  readyForDelivery: boolean,
): BatchExportReportFileDeliveryStatus {
  if (!selectedForExport) return BATCH_EXPORT_DELIVERY_STATUS.notSelected;
  return readyForDelivery
    ? BATCH_EXPORT_DELIVERY_STATUS.readyForDelivery
    : BATCH_EXPORT_DELIVERY_STATUS.actionRequired;
}

export function buildBatchExportReport(
  rows: readonly BatchRow[],
  selectedIds: readonly string[],
  generatedAt = new Date().toISOString(),
): BatchExportReport {
  const selected = new Set(selectedIds);
  const selectedRows = rows.filter((row) => selected.has(row.file_id));
  const selectedCount = selectedRows.length;
  const redactedCount = selectedRows.filter((row) => Boolean(row.has_output)).length;
  const actionRequiredCount = selectedRows.filter((row) => !isBatchRowReadyForDelivery(row)).length;
  const deliveryStatus = summaryDeliveryStatus(selectedCount, actionRequiredCount);
  const zipSkipped = selectedRows
    .filter((row) => !row.has_output)
    .map((row) => ({
      file_id: row.file_id,
      reason: BATCH_EXPORT_BLOCKING_REASONS.missingRedactedOutput,
    }));

  return {
    generated_at: generatedAt,
    job: null,
    summary: {
      total_files: rows.length,
      selected_files: selectedCount,
      redacted_selected_files: redactedCount,
      unredacted_selected_files: selectedCount - redactedCount,
      review_confirmed_selected_files: selectedRows.filter((row) => row.reviewConfirmed === true)
        .length,
      failed_selected_files: selectedRows.filter((row) => row.analyzeStatus === 'failed').length,
      detected_entities: selectedRows.reduce(
        (sum, row) => sum + normalizeCount(row.entity_count),
        0,
      ),
      redaction_coverage: selectedCount > 0 ? redactedCount / selectedCount : 0,
      delivery_status: deliveryStatus,
      action_required_files: actionRequiredCount,
      action_required: deliveryStatus === BATCH_EXPORT_DELIVERY_STATUS.actionRequired,
      blocking_files: actionRequiredCount,
      blocking: deliveryStatus === BATCH_EXPORT_DELIVERY_STATUS.actionRequired,
      ready_for_delivery: deliveryStatus === BATCH_EXPORT_DELIVERY_STATUS.readyForDelivery,
      by_status: countByStatus(selectedRows),
      zip_redacted_included_files: redactedCount,
      zip_redacted_skipped_files: zipSkipped.length,
      visual_review_hint: false,
      visual_review_issue_files: 0,
      visual_review_issue_count: 0,
      visual_review_issue_pages_count: 0,
      visual_review_issue_labels: [],
      visual_review_by_issue: {},
    },
    files: rows.map((row) => {
      const selectedForExport = selected.has(row.file_id);
      const readyForDelivery = isBatchRowReadyForDelivery(row);
      const blockingReasons = readyForDelivery ? [] : buildBlockingReasons(row);
      const deliveryStatus = fileDeliveryStatus(selectedForExport, readyForDelivery);
      return {
        item_id: row.item_id ?? '',
        file_id: row.file_id,
        filename: row.original_filename,
        file_type: String(row.file_type ?? ''),
        file_size: normalizeCount(row.file_size),
        status: row.analyzeStatus,
        has_output: Boolean(row.has_output),
        review_confirmed: row.reviewConfirmed === true,
        entity_count: normalizeCount(row.entity_count),
        page_count: typeof row.page_count === 'number' ? row.page_count : null,
        selected_for_export: selectedForExport,
        delivery_status: deliveryStatus,
        error: row.analyzeError ?? null,
        ready_for_delivery: readyForDelivery,
        action_required: !readyForDelivery,
        blocking: !readyForDelivery,
        blocking_reasons: blockingReasons,
        redacted_export_skip_reason: redactedExportSkipReason(row),
        visual_review_hint: false,
        visual_review: emptyVisualReview(),
      };
    }),
    redacted_zip: {
      included_count: redactedCount,
      skipped_count: zipSkipped.length,
      skipped: zipSkipped,
    },
  };
}

export function buildBatchExportReportBlob(report: BatchExportReport): Blob {
  return new Blob([JSON.stringify(report, null, 2)], {
    type: 'application/json;charset=utf-8',
  });
}
