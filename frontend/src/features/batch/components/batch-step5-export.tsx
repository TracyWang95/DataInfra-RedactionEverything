// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { memo, useEffect, useMemo, useState } from 'react';
import { CheckCircle2, Download, FileJson, RefreshCw, ShieldCheck } from 'lucide-react';

import { useT } from '@/i18n';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Badge } from '@/components/ui/badge';
import { getRedactionStateLabel, resolveRedactionState } from '@/utils/redactionState';
import { getJobExportReport } from '@/services/jobsApi';

import {
  BATCH_EXPORT_BLOCKING_REASONS,
  BATCH_EXPORT_DELIVERY_STATUS,
  type BatchExportReport,
  type BatchExportReportFile,
  buildBatchExportReport,
  buildBatchExportReportBlob,
  isBatchRowReadyForDelivery,
} from '../lib/batch-export-report';
import type { BatchRow, Step } from '../types';
import { triggerDownload } from '../hooks/use-batch-wizard-utils';

type DeliveryGroup = 'ready' | 'review' | 'redact' | 'retry';

const DELIVERY_GROUP_ORDER: DeliveryGroup[] = ['ready', 'review', 'redact', 'retry'];

function getDeliveryGroup(row: BatchRow, reportFile?: BatchExportReportFile): DeliveryGroup {
  if (reportFile?.delivery_status === BATCH_EXPORT_DELIVERY_STATUS.readyForDelivery) return 'ready';
  if (reportFile?.delivery_status === BATCH_EXPORT_DELIVERY_STATUS.actionRequired) {
    const blockingReasons = reportFile.blocking_reasons ?? [];
    if (
      reportFile.status === 'failed' ||
      blockingReasons.includes(BATCH_EXPORT_BLOCKING_REASONS.failed)
    ) {
      return 'retry';
    }
    if (
      reportFile.review_confirmed !== true ||
      blockingReasons.includes(BATCH_EXPORT_BLOCKING_REASONS.reviewNotConfirmed)
    ) {
      return 'review';
    }
    return 'redact';
  }
  if (isBatchRowReadyForDelivery(row)) return 'ready';
  if (row.analyzeStatus === 'failed') return 'retry';
  if (row.reviewConfirmed !== true) return 'review';
  return 'redact';
}

function deliveryGroupLabelKey(group: DeliveryGroup): string {
  if (group === 'ready') return 'batchWizard.step5.group.ready';
  if (group === 'review') return 'batchWizard.step5.group.review';
  if (group === 'redact') return 'batchWizard.step5.group.redact';
  return 'batchWizard.step5.group.retry';
}

interface BatchStep5ExportProps {
  activeJobId?: string | null;
  rows: BatchRow[];
  selected: Set<string>;
  selectedIds: string[];
  zipLoading: boolean;
  toggle: (id: string) => void;
  selectReadyForDelivery: () => void;
  resolveExportIssue?: (fileId?: string) => void;
  goStep: (s: Step) => void;
  downloadZip: (redacted: boolean) => Promise<void>;
}

function BatchStep5ExportInner({
  activeJobId,
  rows,
  selected,
  selectedIds,
  zipLoading,
  toggle,
  selectReadyForDelivery,
  resolveExportIssue,
  goStep,
  downloadZip,
}: BatchStep5ExportProps) {
  const t = useT();
  const [reportLoading, setReportLoading] = useState(false);
  const [serverReport, setServerReport] = useState<BatchExportReport | null>(null);
  const [serverReportLoading, setServerReportLoading] = useState(false);
  const [serverReportFailed, setServerReportFailed] = useState(false);
  const [reportReloadNonce, setReportReloadNonce] = useState(0);
  const localReport = useMemo(() => buildBatchExportReport(rows, selectedIds), [rows, selectedIds]);
  const report = serverReport ?? localReport;
  const deliveryStatus =
    report.summary.delivery_status ??
    (report.summary.ready_for_delivery
      ? BATCH_EXPORT_DELIVERY_STATUS.readyForDelivery
      : report.summary.selected_files === 0
        ? BATCH_EXPORT_DELIVERY_STATUS.noSelection
        : BATCH_EXPORT_DELIVERY_STATUS.actionRequired);
  const hasIncompleteSelected = deliveryStatus === BATCH_EXPORT_DELIVERY_STATUS.actionRequired;
  const readyForDeliveryCount = useMemo(
    () => rows.filter(isBatchRowReadyForDelivery).length,
    [rows],
  );
  const selectedRows = useMemo(
    () => rows.filter((row) => selected.has(row.file_id)),
    [rows, selected],
  );
  const reportFilesById = useMemo(
    () => new Map(report.files.map((file) => [file.file_id, file])),
    [report.files],
  );
  const deliveryGroups = useMemo(() => {
    const groups: Record<DeliveryGroup, BatchRow[]> = {
      ready: [],
      review: [],
      redact: [],
      retry: [],
    };
    selectedRows.forEach((row) => {
      groups[getDeliveryGroup(row, reportFilesById.get(row.file_id))].push(row);
    });
    return groups;
  }, [reportFilesById, selectedRows]);
  const selectedKey = selectedIds.join('\u0000');
  const requiresServerReport = Boolean(activeJobId && selectedIds.length > 0);
  const authoritativeReportReady = !requiresServerReport || Boolean(serverReport);
  const authoritativeReportUnavailable = requiresServerReport && serverReportFailed;
  const redactedZipDisabled =
    zipLoading || !selectedIds.length || hasIncompleteSelected || !authoritativeReportReady;
  const qualityReportDisabled =
    !selectedIds.length || reportLoading || serverReportLoading || authoritativeReportUnavailable;
  const firstIssueFileId = useMemo(() => {
    for (const group of DELIVERY_GROUP_ORDER) {
      if (group === 'ready') continue;
      const row = deliveryGroups[group][0];
      if (row) return row.file_id;
    }
    return undefined;
  }, [deliveryGroups]);
  const handleResolveIssue = (fileId?: string) => {
    if (resolveExportIssue) {
      resolveExportIssue(fileId);
      return;
    }
    goStep(4);
  };

  useEffect(() => {
    if (!activeJobId || selectedIds.length === 0) {
      setServerReport(null);
      setServerReportLoading(false);
      setServerReportFailed(false);
      return;
    }

    let cancelled = false;
    setServerReportLoading(true);
    setServerReportFailed(false);
    void getJobExportReport(activeJobId, selectedIds)
      .then((backendReport) => {
        if (cancelled) return;
        if (isExportReportLike(backendReport)) {
          setServerReport(backendReport);
        } else {
          setServerReport(null);
          setServerReportFailed(true);
        }
      })
      .catch(() => {
        if (cancelled) return;
        setServerReport(null);
        setServerReportFailed(true);
      })
      .finally(() => {
        if (!cancelled) setServerReportLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [activeJobId, reportReloadNonce, selectedKey, selectedIds]);

  const downloadReport = async () => {
    let reportToDownload: BatchExportReport = report;
    if (activeJobId) {
      setReportLoading(true);
      try {
        const backendReport = await getJobExportReport(activeJobId, selectedIds);
        if (isExportReportLike(backendReport)) {
          reportToDownload = backendReport;
          setServerReport(backendReport);
          setServerReportFailed(false);
        } else {
          setServerReport(null);
          setServerReportFailed(true);
          return;
        }
      } catch {
        setServerReport(null);
        setServerReportFailed(true);
        return;
      } finally {
        setReportLoading(false);
      }
    }
    const blob = buildBatchExportReportBlob(reportToDownload);
    triggerDownload(blob, 'batch_quality_report.json');
  };

  return (
    <Card
      className="page-surface border-border/70 shadow-[var(--shadow-control)]"
      data-testid="batch-step5-export"
    >
      <CardHeader className="shrink-0 border-b border-border/70 px-3 py-2">
        <CardTitle className="text-sm">{t('batchWizard.step5.title')}</CardTitle>
        <p className="truncate text-xs text-muted-foreground">{t('batchWizard.step5.desc')}</p>
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto p-3 xl:overflow-hidden">
        {authoritativeReportUnavailable && (
          <div
            className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-900"
            role="alert"
            aria-live="polite"
            data-testid="export-authoritative-report-unavailable"
          >
            <span>{t('batchWizard.step5.reportUnavailable')}</span>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-8 shrink-0 whitespace-nowrap bg-white/70 text-xs"
              disabled={serverReportLoading}
              onClick={() => setReportReloadNonce((value) => value + 1)}
              data-testid="retry-quality-report"
            >
              <RefreshCw data-icon="inline-start" />
              {t('batchWizard.step5.retryReport')}
            </Button>
          </div>
        )}

        <div className="flex shrink-0 flex-nowrap gap-2 overflow-x-auto pb-1">
          <Button
            variant="outline"
            className="h-9 shrink-0 whitespace-nowrap"
            onClick={() => handleResolveIssue(firstIssueFileId)}
            data-testid="step5-back-review"
          >
            {t('batchWizard.step5.backReview')}
          </Button>
          <Button
            variant={hasIncompleteSelected ? 'secondary' : 'outline'}
            className="h-9 shrink-0 whitespace-nowrap"
            onClick={selectReadyForDelivery}
            disabled={readyForDeliveryCount === 0}
            data-testid="select-ready-for-delivery"
          >
            <CheckCircle2 data-icon="inline-start" />
            {t('batchWizard.step5.selectReady')}
          </Button>
          {hasIncompleteSelected && (
            <Button
              variant="outline"
              className="h-9 shrink-0 whitespace-nowrap"
              onClick={() => handleResolveIssue(firstIssueFileId)}
              data-testid="fix-selected-issues"
            >
              {t('batchWizard.step5.fixSelectedIssues')}
            </Button>
          )}
          <Button
            className="h-9 shrink-0 whitespace-nowrap"
            onClick={() => void downloadZip(true)}
            disabled={redactedZipDisabled}
            data-testid="download-redacted"
          >
            <ShieldCheck data-icon="inline-start" />
            {zipLoading
              ? t('batchWizard.step5.downloading')
              : t('batchWizard.step5.downloadRedacted')}
          </Button>
          <Button
            variant="outline"
            className="h-9 shrink-0 whitespace-nowrap"
            onClick={() => void downloadReport()}
            disabled={qualityReportDisabled}
            data-testid="download-quality-report"
          >
            <FileJson data-icon="inline-start" />
            {reportLoading
              ? t('batchWizard.step5.preparingReport')
              : t('batchWizard.step5.downloadReport')}
          </Button>
          <Button
            variant="outline"
            className="h-9 shrink-0 whitespace-nowrap"
            onClick={() => void downloadZip(false)}
            disabled={zipLoading || !selectedIds.length}
            data-testid="download-original"
          >
            <Download data-icon="inline-start" />
            {zipLoading
              ? t('batchWizard.step5.downloading')
              : t('batchWizard.step5.downloadOriginal')}
          </Button>
        </div>

        {hasIncompleteSelected && (
          <div
            className="max-h-28 overflow-y-auto rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900"
            data-testid="export-delivery-breakdown"
          >
            <div className="font-medium">{t('batchWizard.step5.issueFilesTitle')}</div>
            <div className="mt-1.5 grid gap-1.5 sm:grid-cols-3">
              {DELIVERY_GROUP_ORDER.filter((group) => group !== 'ready').map((group) => {
                const groupRows = deliveryGroups[group];
                return (
                  <div
                    key={group}
                    className="rounded-md border border-amber-200/80 bg-white/55 px-2 py-1"
                    data-testid={`export-delivery-group-${group}`}
                  >
                    <div className="flex items-center justify-between gap-2 font-medium">
                      <span className="truncate">{t(deliveryGroupLabelKey(group))}</span>
                      <span className="tabular-nums">{groupRows.length}</span>
                    </div>
                    {groupRows.length > 0 && (
                      <ul className="mt-1 flex flex-col gap-0.5 text-[11px] text-amber-950/80">
                        {groupRows.slice(0, 3).map((row) => (
                          <li key={row.file_id}>
                            <button
                              type="button"
                              className="block w-full truncate rounded px-1 py-0.5 text-left hover:bg-amber-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
                              title={row.original_filename}
                              aria-label={t('batchWizard.step5.resolveIssueFile').replace(
                                '{name}',
                                row.original_filename,
                              )}
                              onClick={() => handleResolveIssue(row.file_id)}
                              data-testid={`resolve-export-issue-${row.file_id}`}
                            >
                              {row.original_filename}
                            </button>
                          </li>
                        ))}
                        {groupRows.length > 3 && (
                          <li>
                            {t('batchWizard.step5.moreIssueFiles').replace(
                              '{count}',
                              String(groupRows.length - 3),
                            )}
                          </li>
                        )}
                      </ul>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        <div
          className="min-h-0 flex-1 divide-y overflow-y-auto rounded-lg border"
          role="list"
          aria-label={t('batchWizard.step5.exportFileSelection')}
        >
          {rows.map((r) => {
            const rs = resolveRedactionState(r.has_output, r.analyzeStatus);
            return (
              <div
                key={r.file_id}
                className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 px-3 py-1.5 text-sm"
                role="listitem"
              >
                <Checkbox
                  checked={selected.has(r.file_id)}
                  aria-label={t('batchWizard.step5.selectFile').replace(
                    '{name}',
                    r.original_filename,
                  )}
                  onCheckedChange={() => toggle(r.file_id)}
                  data-testid={`export-check-${r.file_id}`}
                />
                <span className="min-w-0 truncate" title={r.original_filename}>
                  {r.original_filename}
                </span>
                <Badge
                  variant={
                    rs === 'redacted' ? 'default' : rs === 'unredacted' ? 'outline' : 'secondary'
                  }
                  className="shrink-0 whitespace-nowrap text-xs"
                >
                  {getRedactionStateLabel(rs)}
                </Badge>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

function isExportReportLike(value: unknown): value is BatchExportReport {
  if (!value || typeof value !== 'object') return false;
  const raw = value as Partial<BatchExportReport>;
  return typeof raw.generated_at === 'string' && Boolean(raw.summary) && Array.isArray(raw.files);
}

export const BatchStep5Export = memo(BatchStep5ExportInner);
