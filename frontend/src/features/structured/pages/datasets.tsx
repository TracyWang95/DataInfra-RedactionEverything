// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import { useSearchParams } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { useT } from '@/i18n';
import {
  getStructuredPolicy,
  getStructuredProfile,
  previewStructuredDataset,
  profileStructuredDataset,
  saveStructuredPolicy,
  type StructuredColumnPolicy,
  type StructuredPreview,
  type StructuredProfile,
} from '@/services/structuredApi';
import { DatasetPickerCard } from '../components/dataset-picker';
import { PolicyCanvas } from '../components/policy-canvas';
import { PreviewCard } from '../components/preview-card';
import { ProfilePolicyCard } from '../components/profile-policy-card';
import { StructuredFrame } from '../components/structured-frame';
import { useNotice } from '../hooks/use-notice';
import { useConnections, useDatasets } from '../hooks/use-structured-data';
import { FIELD_POLICY_PAGE_SIZE } from '../lib/constants';
import {
  compareStructuredDatasetsForReview,
  deliveryUrlForDataset,
  isSameDatasetReviewScope,
  preservePolicyReturnParams,
} from '../lib/dataset-utils';
import { profileToPolicy, type FieldReviewProgress } from '../lib/policy-utils';

export function StructuredDatasets() {
  const t = useT();
  const [searchParams, setSearchParams] = useSearchParams();
  const datasetsState = useDatasets();
  const connectionsState = useConnections();
  const notice = useNotice();
  const [selectedDatasetId, setSelectedDatasetId] = React.useState('');
  const [profile, setProfile] = React.useState<StructuredProfile | null>(null);
  const [policy, setPolicy] = React.useState<StructuredColumnPolicy[]>([]);
  const [preview, setPreview] = React.useState<StructuredPreview | null>(null);
  const [policyConfirmed, setPolicyConfirmed] = React.useState(false);
  const [policySaved, setPolicySaved] = React.useState(false);
  const [policyDirty, setPolicyDirty] = React.useState(false);
  const [fieldPage, setFieldPage] = React.useState(0);
  const [reviewedFieldPages, setReviewedFieldPages] = React.useState<Set<number>>(new Set());
  const [completedDatasetIds, setCompletedDatasetIds] = React.useState<Set<string>>(new Set());
  const [pendingSwitchDatasetId, setPendingSwitchDatasetId] = React.useState('');
  const handoffNoticeRef = React.useRef('');
  const restoredDatasetIdRef = React.useRef('');
  const autoPreviewKeyRef = React.useRef('');
  const runNotice = notice.run;
  const selectedDataset =
    datasetsState.datasets.find((dataset) => dataset.id === selectedDatasetId) ?? null;
  const returnToDelivery = searchParams.get('returnTo') === 'delivery';
  const returnDeliveryUrl = returnToDelivery && selectedDataset ? deliveryUrlForDataset(selectedDataset) : '';
  const reviewedDatasetIds = React.useMemo(() => {
    const ids = new Set(completedDatasetIds);
    datasetsState.datasets.forEach((dataset) => {
      if (dataset.policy_reviewed_at) ids.add(dataset.id);
    });
    if (policyDirty && selectedDatasetId) ids.delete(selectedDatasetId);
    return ids;
  }, [completedDatasetIds, datasetsState.datasets, policyDirty, selectedDatasetId]);
  const reviewScopeDatasets = React.useMemo(
    () =>
      selectedDataset
        ? datasetsState.datasets.filter((dataset) => isSameDatasetReviewScope(dataset, selectedDataset))
        : datasetsState.datasets,
    [datasetsState.datasets, selectedDataset],
  );
  const remainingDatasetReviewCount = reviewScopeDatasets.filter(
    (dataset) => !reviewedDatasetIds.has(dataset.id),
  ).length;
  const nextDatasetToReview =
    reviewScopeDatasets
      .filter((dataset) => dataset.id !== selectedDatasetId && !reviewedDatasetIds.has(dataset.id))
      .sort(compareStructuredDatasetsForReview)[0] ?? null;
  const fieldCount = profile?.columns.length ?? 0;
  const fieldPageCount = Math.max(1, Math.ceil(fieldCount / FIELD_POLICY_PAGE_SIZE));
  const safeFieldPage = Math.min(fieldPage, fieldPageCount - 1);
  const fieldReviewTotalPages = profile && fieldCount > 0 ? fieldPageCount : 0;
  const fieldReviewReviewedPages = profile
    ? Math.min(
        [...reviewedFieldPages].filter((pageIndex) => pageIndex >= 0 && pageIndex < fieldPageCount).length,
        fieldPageCount,
      )
    : 0;
  const fieldReviewComplete = Boolean(profile) && (fieldReviewTotalPages === 0 || fieldReviewReviewedPages >= fieldReviewTotalPages);
  const currentFieldPageReviewed = Boolean(profile && reviewedFieldPages.has(safeFieldPage));
  const fieldReviewProgress: FieldReviewProgress = {
    reviewedPages: fieldReviewReviewedPages,
    totalPages: fieldReviewTotalPages,
    currentPage: profile ? safeFieldPage + 1 : 0,
    currentPageReviewed: currentFieldPageReviewed,
    allReviewed: fieldReviewComplete,
  };

  React.useEffect(() => {
    const requested = searchParams.get('datasetId');
    if (requested && datasetsState.datasets.some((dataset) => dataset.id === requested)) {
      setSelectedDatasetId(requested);
      return;
    }
    setSelectedDatasetId((current) => current || datasetsState.datasets[0]?.id || '');
  }, [datasetsState.datasets, searchParams]);

  React.useEffect(() => {
    const registered = Number(searchParams.get('registered') ?? 0);
    const source = searchParams.get('source');
    const datasetId = searchParams.get('datasetId') ?? '';
    const key = `${source}:${registered}:${datasetId}`;
    if (!['database', 'file'].includes(source ?? '') || registered <= 0 || handoffNoticeRef.current === key) return;
    handoffNoticeRef.current = key;
    const sourceLabel = source === 'database' ? t('structured.datasets.source.database') : t('structured.datasets.source.file');
    notice.setMessage(
      registered === 1
        ? t('structured.datasets.notice.handoffSingle').replace('{source}', sourceLabel)
        : t('structured.datasets.notice.handoffMulti')
            .replace('{source}', sourceLabel)
            .replace('{count}', String(registered)),
    );
  }, [notice, searchParams, t]);

  function resetDatasetReviewState() {
    setProfile(null);
    setPolicy([]);
    setPreview(null);
    setPolicyConfirmed(false);
    setPolicySaved(false);
    setPolicyDirty(false);
    setFieldPage(0);
    setReviewedFieldPages(new Set());
  }

  React.useEffect(() => {
    if (!selectedDataset) return;
    const restoreKey = [
      selectedDataset.id,
      selectedDataset.profile_updated_at ?? '',
      selectedDataset.policy_updated_at ?? '',
      selectedDataset.policy_reviewed_at ?? '',
    ].join(':');
    if (restoredDatasetIdRef.current === restoreKey && profile?.dataset_id === selectedDataset.id) return;

    const hasLocalReviewState =
      profile?.dataset_id === selectedDataset.id ||
      preview?.dataset_id === selectedDataset.id;
    if (!hasLocalReviewState) {
      resetDatasetReviewState();
    }

    const hasStoredReviewState = Boolean(
      selectedDataset.profile_updated_at || selectedDataset.policy_updated_at || selectedDataset.policy_reviewed_at,
    );
    if (!hasStoredReviewState) {
      restoredDatasetIdRef.current = restoreKey;
      return;
    }

    let cancelled = false;
    void runNotice('restorePolicy', async () => {
      const [storedProfile, storedPolicy] = await Promise.all([
        getStructuredProfile(selectedDataset.id),
        getStructuredPolicy(selectedDataset.id),
      ]);
      if (cancelled) return;
      const restoredPolicy = storedPolicy.columns.length
        ? storedPolicy.columns
        : storedProfile.columns.map(profileToPolicy);
      const restoredPageCount = Math.max(1, Math.ceil(storedProfile.columns.length / FIELD_POLICY_PAGE_SIZE));
      const wasReviewed = Boolean(selectedDataset.policy_reviewed_at);
      const restoredPreview = wasReviewed ? await previewStructuredDataset(selectedDataset.id) : null;
      if (cancelled) return;
      setProfile(storedProfile);
      setPolicy(restoredPreview?.policy ?? restoredPolicy);
      setPreview(restoredPreview);
      setPolicyConfirmed(wasReviewed);
      setPolicySaved(wasReviewed);
      setPolicyDirty(false);
      setFieldPage(0);
      setReviewedFieldPages(
        wasReviewed
          ? new Set(Array.from({ length: restoredPageCount }, (_, index) => index))
          : new Set(),
      );
      restoredDatasetIdRef.current = restoreKey;
    });
    return () => {
      cancelled = true;
    };
  }, [preview?.dataset_id, profile?.dataset_id, runNotice, selectedDataset]);

  React.useEffect(() => {
    if (!selectedDataset || !selectedDatasetId || !policySaved || preview || notice.busy) return;
    const previewKey = `${selectedDataset.id}:${selectedDataset.policy_updated_at ?? selectedDataset.policy_reviewed_at ?? 'saved'}`;
    if (autoPreviewKeyRef.current === previewKey) return;

    let cancelled = false;
    autoPreviewKeyRef.current = previewKey;
    void runNotice('autoPreview', async () => {
      const response = await previewStructuredDataset(selectedDatasetId);
      if (cancelled) return;
      setPreview(response);
      setPolicy(response.policy);
    });
    return () => {
      cancelled = true;
    };
  }, [notice.busy, policySaved, preview, runNotice, selectedDataset, selectedDatasetId]);

  function applyDatasetSelection(datasetId: string) {
    setSelectedDatasetId(datasetId);
    setSearchParams(datasetId ? preservePolicyReturnParams(searchParams, datasetId) : {});
    resetDatasetReviewState();
  }

  function selectDataset(datasetId: string) {
    if (datasetId === selectedDatasetId) {
      setSearchParams(datasetId ? preservePolicyReturnParams(searchParams, datasetId) : {});
      return;
    }
    if (policyDirty) {
      setPendingSwitchDatasetId(datasetId);
      return;
    }
    applyDatasetSelection(datasetId);
  }

  async function handleProfile(datasetId = selectedDatasetId) {
    if (!datasetId) return;
    await notice.run('profile', async () => {
      const nextProfile = await profileStructuredDataset(datasetId);
      setProfile(nextProfile);
      setPolicy(nextProfile.columns.map(profileToPolicy));
      setPolicyConfirmed(false);
      setPolicySaved(false);
      setPolicyDirty(false);
      setPreview(null);
      setFieldPage(0);
      setReviewedFieldPages(new Set());
    });
  }

  async function handleSaveAndPreview() {
    if (!selectedDatasetId) return;
    if (!policyConfirmed) {
      notice.setError(t('structured.datasets.error.confirmFirst'));
      return;
    }
    await notice.run('policyPreview', async () => {
      const saved = await saveStructuredPolicy(selectedDatasetId, policy);
      setPolicy(saved.columns);
      setPolicySaved(true);
      setPolicyDirty(false);
      const response = await previewStructuredDataset(selectedDatasetId);
      setPreview(response);
      setPolicy(response.policy);
      setCompletedDatasetIds((current) => new Set([...current, selectedDatasetId]));
      await datasetsState.refresh();
    });
  }

  async function handlePreview() {
    if (!selectedDatasetId) return;
    if (!policySaved) {
      notice.setError(t('structured.datasets.error.saveFirst'));
      return;
    }
    await notice.run('preview', async () => {
      const response = await previewStructuredDataset(selectedDatasetId);
      setPreview(response);
      setPolicy(response.policy);
    });
  }

  function handlePolicyChange(nextPolicy: StructuredColumnPolicy[]) {
    setPolicy(nextPolicy);
    setPolicyConfirmed(false);
    setPolicySaved(false);
    setPolicyDirty(true);
    setPreview(null);
    setReviewedFieldPages((current) => {
      if (!current.has(safeFieldPage)) return current;
      const next = new Set(current);
      next.delete(safeFieldPage);
      return next;
    });
  }

  function handleConfirmChange(checked: boolean) {
    if (checked && !fieldReviewComplete) {
      notice.setError(
        t('structured.datasets.error.reviewAllPages')
          .replace('{reviewed}', String(fieldReviewReviewedPages))
          .replace('{total}', String(fieldReviewTotalPages)),
      );
      return;
    }
    setPolicyConfirmed(checked);
  }

  function advanceFieldReview() {
    if (!profile) return;
    const nextReviewedPages = new Set(reviewedFieldPages);
    nextReviewedPages.add(safeFieldPage);
    setReviewedFieldPages(nextReviewedPages);
    const nextUnreviewed = Array.from({ length: fieldPageCount }, (_, index) => index).find(
      (pageIndex) => !nextReviewedPages.has(pageIndex),
    );
    if (nextUnreviewed == null) {
      setPolicyConfirmed(true);
    }
    setFieldPage(nextUnreviewed ?? safeFieldPage);
  }

  return (
    <StructuredFrame
      eyebrow={t('structured.datasets.eyebrow')}
      title={t('structured.datasets.title')}
      description={t('structured.datasets.description')}
      notices={notice}
      fit
      actions={
        <Button variant="outline" size="sm" onClick={() => void datasetsState.refresh()}>
          <RefreshCw className="size-4" />
          {t('structured.datasets.refresh')}
        </Button>
      }
    >
      <section className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-2">
        <PolicyCanvas
          dataset={selectedDataset}
          profile={profile}
          fieldReview={fieldReviewProgress}
          policyConfirmed={policyConfirmed}
          policySaved={policySaved}
          preview={preview}
          nextDatasetToReview={nextDatasetToReview}
          remainingDatasetReviewCount={remainingDatasetReviewCount}
          busy={notice.busy}
          onConfirmChange={handleConfirmChange}
          onAdvanceFieldReview={advanceFieldReview}
          onProfile={() => void handleProfile()}
          onSave={() => void handleSaveAndPreview()}
          onPreview={() => void handlePreview()}
          onNextDataset={() => {
            if (nextDatasetToReview) selectDataset(nextDatasetToReview.id);
          }}
          returnDeliveryUrl={returnDeliveryUrl}
        />
        <div className="grid min-h-0 gap-2 xl:grid-cols-[17rem_minmax(0,1fr)_22rem]">
          <DatasetPickerCard
            datasets={datasetsState.datasets}
            connections={connectionsState.connections}
            selectedDatasetId={selectedDatasetId}
            reviewedDatasetIds={reviewedDatasetIds}
            dirtyDatasetId={policyDirty ? selectedDatasetId : ''}
            onSelect={selectDataset}
            compact
          />
          <ProfilePolicyCard
            dataset={selectedDataset}
            profile={profile}
            policy={policy}
            fieldPage={safeFieldPage}
            currentPageReviewed={fieldReviewProgress.currentPageReviewed}
            reviewedPageCount={fieldReviewReviewedPages}
            pageCount={fieldReviewTotalPages || 1}
            onFieldPageChange={setFieldPage}
            onPolicyChange={handlePolicyChange}
          />
          <PreviewCard
            preview={preview}
            profile={profile}
            loading={notice.busy === 'autoPreview' || notice.busy === 'preview' || notice.busy === 'policyPreview'}
          />
        </div>
      </section>
      <ConfirmDialog
        open={Boolean(pendingSwitchDatasetId)}
        title={t('structured.datasets.confirmSwitch.title')}
        message={t('structured.datasets.confirmSwitch.message')}
        onConfirm={() => {
          const nextDatasetId = pendingSwitchDatasetId;
          setPendingSwitchDatasetId('');
          if (nextDatasetId) applyDatasetSelection(nextDatasetId);
        }}
        onCancel={() => setPendingSwitchDatasetId('')}
      />
    </StructuredFrame>
  );
}
