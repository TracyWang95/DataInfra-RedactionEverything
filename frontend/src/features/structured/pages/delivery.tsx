// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowRight, Download, Play } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { getJob } from '@/services/jobsApi';
import { useT } from '@/i18n';
import {
  createStructuredJob,
  downloadStructuredJob,
  type StructuredExportFormat,
} from '@/services/structuredApi';
import { DeliveryChecklist, DeliveryDatasetCard } from '../components/delivery-cards';
import { Field } from '../components/shared';
import { StructuredFrame } from '../components/structured-frame';
import { useNotice } from '../hooks/use-notice';
import { useConnections, useDatasets } from '../hooks/use-structured-data';
import { exportOptions } from '../lib/constants';
import {
  compareStructuredDatasetsForReview,
  isDatasetDeliveryReady,
  isFileDataset,
  policyReviewUrlForDataset,
  sameSetValues,
  structuredJobStatusLabel,
  toggleSet,
} from '../lib/dataset-utils';

export function StructuredDelivery() {
  const t = useT();
  const [searchParams, setSearchParams] = useSearchParams();
  const datasetsState = useDatasets();
  const connectionsState = useConnections();
  const notice = useNotice();
  const requestedDatasetId = searchParams.get('datasetId') ?? '';
  const requestedScope = searchParams.get('scope') ?? '';
  const requestedConnectionId = searchParams.get('connectionId') ?? '';
  const requestedSourceId = searchParams.get('sourceId') ?? '';
  const requestedJobId = searchParams.get('jobId') ?? '';
  const requestedSelectionSignature = searchParams.get('selected') ?? '';
  const requestedSelectionIds = React.useMemo(
    () => Array.from(new Set(requestedSelectionSignature.split(',').map((item) => item.trim()).filter(Boolean))),
    [requestedSelectionSignature],
  );
  const appliedDatasetParamRef = React.useRef('');
  const appliedDefaultSelectionRef = React.useRef('');
  const [selectedIds, setSelectedIds] = React.useState<Set<string>>(new Set());
  const [exportFormat, setExportFormat] = React.useState<StructuredExportFormat>('csv');
  const [latestJobId, setLatestJobId] = React.useState(requestedJobId);
  const [latestJobStatus, setLatestJobStatus] = React.useState('');
  const handoffDataset = datasetsState.datasets.find((dataset) => dataset.id === requestedDatasetId) ?? null;
  const handoffScopeDatasets = React.useMemo(() => {
    if (requestedScope === 'file') {
      return datasetsState.datasets.filter(isFileDataset).sort(compareStructuredDatasetsForReview);
    }
    if (requestedScope === 'connection' && requestedConnectionId) {
      return datasetsState.datasets
        .filter((dataset) => dataset.connection_id === requestedConnectionId)
        .sort(compareStructuredDatasetsForReview);
    }
    if (requestedScope === 'source' && requestedSourceId) {
      return datasetsState.datasets
        .filter((dataset) => dataset.source_id === requestedSourceId)
        .sort(compareStructuredDatasetsForReview);
    }
    return handoffDataset ? [handoffDataset] : [];
  }, [datasetsState.datasets, handoffDataset, requestedConnectionId, requestedScope, requestedSourceId]);
  const handoffSelectionIds = handoffScopeDatasets.map((dataset) => dataset.id);
  const handoffSelectionSignature = handoffSelectionIds.join('|');
  const hasExplicitHandoffScope =
    handoffScopeDatasets.length > 0 &&
    (requestedScope === 'file' ||
      (requestedScope === 'connection' && Boolean(requestedConnectionId)) ||
      (requestedScope === 'source' && Boolean(requestedSourceId)));
  const deliveryDatasetOptions = React.useMemo(
    () => (hasExplicitHandoffScope ? handoffScopeDatasets : datasetsState.datasets),
    [datasetsState.datasets, handoffScopeDatasets, hasExplicitHandoffScope],
  );
  const deliverableDatasetOptions = React.useMemo(
    () => deliveryDatasetOptions.filter(isDatasetDeliveryReady),
    [deliveryDatasetOptions],
  );
  const deliverableDatasetIds = React.useMemo(
    () => deliverableDatasetOptions.map((dataset) => dataset.id),
    [deliverableDatasetOptions],
  );
  const deliverableDatasetIdSet = React.useMemo(() => new Set(deliverableDatasetIds), [deliverableDatasetIds]);
  const defaultSelectionSignature = deliverableDatasetIds.join('|');
  const unreviewedDeliveryDatasets = deliveryDatasetOptions.filter((dataset) => !isDatasetDeliveryReady(dataset));
  const selectedDatasets = React.useMemo(
    () => deliverableDatasetOptions.filter((dataset) => selectedIds.has(dataset.id)),
    [deliverableDatasetOptions, selectedIds],
  );
  const firstUnreviewedDataset = unreviewedDeliveryDatasets[0] ?? null;
  const firstUnreviewedLabel = firstUnreviewedDataset
    ? firstUnreviewedDataset.table_name || firstUnreviewedDataset.name
    : '';
  const handoffConnection =
    requestedScope === 'connection'
      ? connectionsState.connections.find((connection) => connection.id === requestedConnectionId) ?? null
      : null;
  const handoffLabel =
    requestedScope === 'file' && handoffScopeDatasets.length > 1
      ? t('structured.delivery.handoff.files').replace('{count}', String(handoffScopeDatasets.length))
    : requestedScope === 'connection' && handoffScopeDatasets.length > 1
      ? t('structured.delivery.handoff.connection')
          .replace('{name}', handoffConnection?.display_name || t('structured.delivery.handoff.connectionFallback'))
          .replace('{count}', String(handoffScopeDatasets.length))
      : requestedScope === 'source' && handoffScopeDatasets.length > 1
        ? t('structured.delivery.handoff.source').replace('{count}', String(handoffScopeDatasets.length))
        : handoffDataset?.name;
  const handoffVisible = handoffSelectionIds.some((datasetId) => selectedIds.has(datasetId));
  const jobCompleted = latestJobStatus === 'completed';
  const deliveryMode = selectedDatasets.length === 0 ? 'none' : selectedDatasets.length > 1 ? 'batch' : 'single';
  const deliveryModeLabel =
    selectedDatasets.length === 0
      ? t('structured.delivery.modePending')
      : selectedDatasets.length > 1
        ? t('structured.delivery.modeBatch').replace('{count}', String(selectedDatasets.length))
        : t('structured.delivery.modeSingle');
  const canCreateJob = selectedDatasets.length > 0 && !notice.busy;
  const createButtonLabel = jobCompleted
    ? t('structured.delivery.createRerun')
    : selectedDatasets.length === 0
      ? t('structured.delivery.createSelectFirst')
      : selectedDatasets.length > 1
        ? t('structured.delivery.createBatch').replace('{count}', String(selectedDatasets.length))
        : t('structured.delivery.createSingle');
  const downloadButtonLabel = jobCompleted ? t('structured.delivery.downloadZip') : t('structured.delivery.downloadResult');

  React.useEffect(() => {
    if (requestedSelectionIds.length === 0) return;
    const validSelectionIds = requestedSelectionIds.filter((datasetId) => deliverableDatasetIdSet.has(datasetId));
    setSelectedIds((current) => (sameSetValues(current, validSelectionIds) ? current : new Set(validSelectionIds)));
  }, [deliverableDatasetIdSet, requestedSelectionIds]);

  React.useEffect(() => {
    if (requestedSelectionIds.length > 0) return;
    const handoffKey = `${requestedDatasetId}:${requestedScope}:${requestedConnectionId}:${requestedSourceId}:${handoffSelectionSignature}`;
    if ((!requestedDatasetId && !hasExplicitHandoffScope) || appliedDatasetParamRef.current === handoffKey) return;
    if (handoffSelectionIds.length === 0) return;
    const reviewedHandoffIds = handoffScopeDatasets.filter(isDatasetDeliveryReady).map((dataset) => dataset.id);
    setSelectedIds(new Set(reviewedHandoffIds));
    appliedDatasetParamRef.current = handoffKey;
  }, [
    handoffSelectionIds,
    handoffSelectionSignature,
    handoffScopeDatasets,
    requestedSelectionIds.length,
    requestedConnectionId,
    requestedDatasetId,
    requestedScope,
    requestedSourceId,
    hasExplicitHandoffScope,
  ]);

  React.useEffect(() => {
    if (requestedSelectionIds.length > 0) return;
    if (requestedDatasetId || hasExplicitHandoffScope) return;
    if (!defaultSelectionSignature || appliedDefaultSelectionRef.current === defaultSelectionSignature) return;
    if (selectedIds.size > 0) {
      appliedDefaultSelectionRef.current = defaultSelectionSignature;
      return;
    }
    setSelectedIds(new Set(deliverableDatasetIds));
    appliedDefaultSelectionRef.current = defaultSelectionSignature;
  }, [
    defaultSelectionSignature,
    deliverableDatasetIds,
    hasExplicitHandoffScope,
    requestedDatasetId,
    requestedSelectionIds.length,
    selectedIds.size,
  ]);

  React.useEffect(() => {
    setLatestJobId(requestedJobId);
    if (!requestedJobId) {
      setLatestJobStatus('');
      return undefined;
    }
    let cancelled = false;
    void getJob(requestedJobId)
      .then((detail) => {
        if (!cancelled) setLatestJobStatus(detail.status);
      })
      .catch(() => {
        if (!cancelled) setLatestJobStatus('');
      });
    return () => {
      cancelled = true;
    };
  }, [requestedJobId]);

  async function waitForStructuredJob(jobId: string): Promise<string> {
    for (let attempt = 0; attempt < 45; attempt += 1) {
      const detail = await getJob(jobId);
      setLatestJobStatus(detail.status);
      if (['completed', 'failed', 'cancelled'].includes(detail.status)) return detail.status;
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    return 'processing';
  }

  async function handleCreateJob() {
    const ids = selectedDatasets.map((dataset) => dataset.id);
    if (!ids.length) {
      notice.setError(t('structured.delivery.error.selectOne'));
      return;
    }
    await notice.run('job', async () => {
      const response = await createStructuredJob({
        title:
          ids.length === 1
            ? t('structured.delivery.jobTitleSingle')
            : t('structured.delivery.jobTitleBatch').replace('{count}', String(ids.length)),
        dataset_ids: ids,
        export_format: exportFormat,
        skip_review: true,
        auto_submit: true,
      });
      setLatestJobId(response.job.id);
      setLatestJobStatus(response.job.status || 'queued');
      setSearchParams({ ...handoffSearchParams(new Set(ids)), jobId: response.job.id });
      const finalStatus = await waitForStructuredJob(response.job.id);
      if (finalStatus === 'completed') {
        notice.setMessage(t('structured.delivery.notice.packageReady').replace('{jobId}', response.job.id));
      } else if (finalStatus === 'failed' || finalStatus === 'cancelled') {
        throw new Error(t('structured.delivery.error.jobIncomplete').replace('{status}', finalStatus));
      } else {
        notice.setMessage(t('structured.delivery.notice.stillProcessing').replace('{jobId}', response.job.id));
      }
    });
  }

  function clearStaleJob(nextSelectedIds = selectedIds, reason = t('structured.delivery.notice.selectionChanged')) {
    const hadJob = Boolean(latestJobId || latestJobStatus);
    setLatestJobId('');
    setLatestJobStatus('');
    notice.setMessage(hadJob ? reason : '');
    setSearchParams(handoffSearchParams(nextSelectedIds));
  }

  function handoffSearchParams(nextSelectedIds: Set<string>): Record<string, string> {
    const params: Record<string, string> = {};
    if (requestedDatasetId && nextSelectedIds.has(requestedDatasetId)) params.datasetId = requestedDatasetId;
    if (requestedScope === 'file') {
      params.scope = 'file';
    }
    if (requestedScope === 'connection' && requestedConnectionId) {
      params.scope = 'connection';
      params.connectionId = requestedConnectionId;
    }
    if (requestedScope === 'source' && requestedSourceId) {
      params.scope = 'source';
      params.sourceId = requestedSourceId;
    }
    const selectedInScope = Array.from(nextSelectedIds).filter((datasetId) => deliverableDatasetIds.includes(datasetId));
    const defaultIdSet = new Set(deliverableDatasetIds);
    const differsFromDefault =
      selectedInScope.length > 0 &&
      (selectedInScope.length !== defaultIdSet.size || selectedInScope.some((datasetId) => !defaultIdSet.has(datasetId)));
    if (differsFromDefault) params.selected = selectedInScope.join(',');
    return params;
  }

  function handleToggleDataset(datasetId: string) {
    const dataset = deliveryDatasetOptions.find((item) => item.id === datasetId);
    if (dataset && !isDatasetDeliveryReady(dataset)) {
      notice.setError(t('structured.delivery.error.notReviewed'));
      return;
    }
    const next = toggleSet(selectedIds, datasetId);
    setSelectedIds(next);
    clearStaleJob(next);
  }

  function handleSelectAll(datasetIds?: string[]) {
    const next = new Set(datasetIds ?? deliverableDatasetOptions.map((dataset) => dataset.id));
    if (next.size === 0 && deliveryDatasetOptions.length > 0) {
      notice.setError(t('structured.delivery.error.noneReviewed'));
      return;
    }
    setSelectedIds(next);
    clearStaleJob(next);
  }

  function handleClearSelection() {
    const next = new Set<string>();
    setSelectedIds(next);
    clearStaleJob(next);
  }

  function handleExportFormatChange(value: StructuredExportFormat) {
    setExportFormat(value);
    clearStaleJob(selectedIds, t('structured.delivery.notice.formatChanged'));
  }

  async function handleDownload() {
    if (!latestJobId) return;
    if (latestJobStatus !== 'completed') {
      notice.setError(t('structured.delivery.error.waitComplete'));
      return;
    }
    await notice.run('download', async () => {
      await downloadStructuredJob(latestJobId);
      notice.setMessage(t('structured.delivery.notice.downloadStarted').replace('{jobId}', latestJobId));
    });
  }

  return (
    <StructuredFrame
      eyebrow={t('structured.delivery.eyebrow')}
      title={t('structured.delivery.title')}
      description={t('structured.delivery.description')}
      notices={notice}
      actions={
        <Button variant="outline" size="sm" asChild>
          <Link to="/jobs">{t('structured.delivery.jobsCenter')}</Link>
        </Button>
      }
    >
      <section className="grid items-start gap-3 xl:grid-cols-[minmax(0,1.2fr)_minmax(22rem,0.8fr)]">
        <DeliveryDatasetCard
          datasets={deliveryDatasetOptions}
          connections={connectionsState.connections}
          selectedIds={selectedIds}
          onToggle={handleToggleDataset}
          onSelectAll={handleSelectAll}
          onClear={handleClearSelection}
        />
        <Card className="page-surface border-border/70 shadow-[var(--shadow-control)]">
          <CardHeader className="px-4 py-3">
            <CardTitle className="text-sm">{t('structured.delivery.settings.title')}</CardTitle>
            <CardDescription>{t('structured.delivery.settings.description')}</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-2 px-4 pb-4 pt-0">
            <Field label={t('structured.delivery.settings.format')}>
              <Select
                value={exportFormat}
                onValueChange={(value) => handleExportFormatChange(value as StructuredExportFormat)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {exportOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs leading-4 text-muted-foreground">
                {t('structured.delivery.settings.formatHint')}
              </p>
            </Field>
            <div className="rounded-xl border border-border bg-muted/25 p-3 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">{t('structured.delivery.summary.selected')}</span>
                <span className="font-semibold">
                  {t('structured.common.datasetCount').replace('{count}', String(selectedDatasets.length))}
                </span>
              </div>
              <div className="mt-1.5 flex items-center justify-between gap-3">
                <span className="text-muted-foreground">{t('structured.delivery.summary.mode')}</span>
                <Badge variant={deliveryMode === 'single' ? 'secondary' : 'outline'}>{deliveryModeLabel}</Badge>
              </div>
              {handoffVisible && handoffLabel ? (
                <div className="mt-1.5 flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">{t('structured.delivery.summary.handoff')}</span>
                  <span className="truncate font-medium" title={handoffLabel}>
                    {handoffLabel}
                  </span>
                </div>
              ) : null}
              <div className="mt-1.5 flex items-center justify-between gap-3">
                <span className="text-muted-foreground">{t('structured.delivery.summary.downloadForm')}</span>
                <span className="font-medium">{t('structured.delivery.summary.zipPackage')}</span>
              </div>
              {latestJobId ? (
                <div className="mt-1.5 flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">{t('structured.delivery.summary.latestJob')}</span>
                  <Badge variant={jobCompleted ? 'default' : 'outline'}>
                    {structuredJobStatusLabel(latestJobStatus || 'queued')}
                  </Badge>
                </div>
              ) : null}
              {jobCompleted ? (
                <div className="mt-1.5 rounded-lg border border-[var(--success-border)] bg-[var(--success-surface)] px-2.5 py-1.5 text-xs text-[var(--success-foreground)]">
                  {t('structured.delivery.zipReady')}
                </div>
              ) : null}
            </div>
            {unreviewedDeliveryDatasets.length > 0 ? (
              <div className="grid gap-2 rounded-xl border border-[var(--warning-border)] bg-[var(--warning-surface)] px-3 py-2 text-sm">
                <div className="flex items-start justify-between gap-3">
                  <span className="min-w-0">
                    <span className="block font-semibold text-[var(--warning-foreground)]">
                      {t('structured.delivery.unreviewedTitle')}
                    </span>
                    <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                      {firstUnreviewedLabel
                        ? t('structured.delivery.unreviewedNext').replace('{name}', firstUnreviewedLabel)
                        : ''}
                      {t('structured.delivery.unreviewedHint').replace(
                        '{count}',
                        String(unreviewedDeliveryDatasets.length),
                      )}
                    </span>
                  </span>
                  {firstUnreviewedDataset ? (
                    <Button asChild variant="outline" size="sm" className="h-8 shrink-0 bg-background">
                      <Link to={policyReviewUrlForDataset(firstUnreviewedDataset, { returnToDelivery: true })}>
                        {t('structured.common.goReview')}
                        <ArrowRight className="size-4" />
                      </Link>
                    </Button>
                  ) : null}
                </div>
              </div>
            ) : null}
            <DeliveryChecklist
              selectedCount={selectedDatasets.length}
              unreviewedCount={unreviewedDeliveryDatasets.length}
              exportFormat={exportFormat}
              deliveryModeLabel={selectedDatasets.length ? deliveryModeLabel : t('structured.delivery.modePending')}
              latestJobStatus={latestJobStatus}
            />
            <div className="grid gap-2 sm:grid-cols-2">
              <Button
                variant={jobCompleted ? 'outline' : 'default'}
                onClick={() => void handleCreateJob()}
                disabled={!canCreateJob}
                data-testid="delivery-create-job"
              >
                <Play className="size-4" />
                {createButtonLabel}
              </Button>
              <Button
                variant={jobCompleted ? 'default' : 'outline'}
                onClick={() => void handleDownload()}
                disabled={!latestJobId || !jobCompleted || Boolean(notice.busy)}
                data-testid="delivery-download-job"
              >
                <Download className="size-4" />
                {downloadButtonLabel}
              </Button>
            </div>
          </CardContent>
        </Card>
      </section>
    </StructuredFrame>
  );
}
