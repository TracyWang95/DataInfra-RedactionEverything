// Copyright 2026 DataInfra-RedactionEverything Contributors

import { memo, useCallback, useId, useMemo, useState } from 'react';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { PaginationRail } from '@/components/PaginationRail';
import ImageBBoxEditor from '@/components/ImageBBoxEditor';
import type { BoundingBox as EditorBox } from '@/components/ImageBBoxEditor';
import {
  formatSourceDetail,
  getReviewBoxSourceKind,
  getReviewBoxQualityIssueKeys,
  type ReviewBoxQualityIssue,
  type ReviewBoxSourceKind,
} from '../lib/review-box-quality';
import type { PipelineCfg, ReviewVisionPageQuality, ReviewVisionPipelineStatus } from '../types';

const DEFAULT_VISION_TYPE_COLOR = '#6366F1';

export interface ReviewImageContentProps {
  reviewBoxes: EditorBox[];
  visibleReviewBoxes: EditorBox[];
  reviewOrigImageBlobUrl: string;
  reviewImagePreviewSrc: string;
  reviewImagePreviewLoading: boolean;
  reviewCurrentPage: number;
  reviewTotalPages: number;
  selectedReviewBoxCount: number;
  totalReviewBoxCount: number;
  currentReviewVisionQuality: ReviewVisionPageQuality | null;
  pipelines: PipelineCfg[];
  onReviewPageChange: (page: number) => void;
  setVisibleReviewBoxes: React.Dispatch<React.SetStateAction<EditorBox[]>>;
  handleReviewBoxesCommit: (prev: EditorBox[], next: EditorBox[]) => void;
  toggleReviewBoxSelected: (id: string) => void;
}

function pipelineLabel(t: ReturnType<typeof useT>, key: string): string {
  if (key === 'ocr_has') return t('batchWizard.step4.pipelineOcrHas');
  if (key === 'visual_features') return t('batchWizard.step4.pipelineVisualFeature');
  return formatSourceDetail(key) || key;
}

function pipelineStateLabel(
  t: ReturnType<typeof useT>,
  status: ReviewVisionPipelineStatus,
): string {
  if (status.failed) return t('batchWizard.step4.pipelineFailed');
  if (status.skipped) return t('batchWizard.step4.pipelineSkipped');
  if (status.ran) return t('batchWizard.step4.pipelineRan');
  return t('batchWizard.step4.pipelineUnknown');
}

interface QualityIssueChip {
  key: ReviewBoxQualityIssue;
  label: string;
  title: string;
}

interface SourceBadge {
  label: string;
  title: string;
  tone: 'model' | 'ocr' | 'fallback' | 'neutral';
}

interface SourceSummaryChip {
  key: ReviewBoxSourceKind;
  label: string;
  title: string;
  tone: SourceBadge['tone'];
  count: number;
}

const SOURCE_SUMMARY_ORDER: readonly ReviewBoxSourceKind[] = [
  'visualFeature',
  'fallback',
  'ocrHas',
  'table',
];

function compactSourceDetail(
  value: string | undefined,
  omittedWords: readonly string[] = [],
): string {
  const omitted = new Set(omittedWords.map((word) => word.toLowerCase()));
  return formatSourceDetail(value)
    .split(/\s+/)
    .filter((word) => word && !omitted.has(word.toLowerCase()))
    .join(' ')
    .trim();
}

function sourceLabel(t: ReturnType<typeof useT>, key: ReviewBoxSourceKind): string {
  if (key === 'visualFeature') return t('batchWizard.step4.sourceVisualFeatureModel');
  if (key === 'fallback') return t('batchWizard.step4.sourceFallbackDetector');
  if (key === 'ocrHas') return t('batchWizard.step4.sourceOcrHas');
  return t('batchWizard.step4.sourceTable');
}

function sourceTitle(t: ReturnType<typeof useT>, key: ReviewBoxSourceKind): string {
  if (key === 'visualFeature') return t('batchWizard.step4.sourceVisualFeatureModelTitle');
  if (key === 'fallback') return t('batchWizard.step4.sourceFallbackDetectorTitle');
  if (key === 'ocrHas') return t('batchWizard.step4.sourceOcrHasTitle');
  return t('batchWizard.step4.sourceTableTitle');
}

function sourceTone(key: ReviewBoxSourceKind): SourceBadge['tone'] {
  if (key === 'fallback') return 'fallback';
  if (key === 'visualFeature') return 'model';
  return key === 'ocrHas' ? 'ocr' : 'neutral';
}

function sourceBadge(t: ReturnType<typeof useT>, box: EditorBox): SourceBadge | null {
  const source = String(box.source ?? '').toLowerCase();
  const kind = getReviewBoxSourceKind(box);
  const isFallback = kind === 'fallback';
  const detail =
    box.source_detail && box.source_detail.toLowerCase() !== source
      ? compactSourceDetail(box.source_detail, isFallback ? ['fallback', 'detector'] : [])
      : '';

  if (kind) {
    const label = sourceLabel(t, kind);
    return {
      label: detail ? `${label}: ${detail}` : label,
      title: sourceTitle(t, kind),
      tone: sourceTone(kind),
    };
  }

  const label = formatSourceDetail(box.source_detail ?? box.source);
  if (!label) return null;
  return {
    label,
    title: t('batchWizard.step4.sourceGenericTitle'),
    tone: 'neutral',
  };
}

function sourceSummaryChips(
  t: ReturnType<typeof useT>,
  boxes: readonly EditorBox[],
): SourceSummaryChip[] {
  const counts = new Map<ReviewBoxSourceKind, number>();
  boxes.forEach((box) => {
    const kind = getReviewBoxSourceKind(box);
    if (!kind) return;
    counts.set(kind, (counts.get(kind) ?? 0) + 1);
  });

  return SOURCE_SUMMARY_ORDER.flatMap((key) => {
    const count = counts.get(key);
    if (!count) return [];
    const label = sourceLabel(t, key);
    return {
      key,
      label,
      title: t('batchWizard.step4.sourceSummaryChipTitle')
        .replace('{source}', label)
        .replace('{count}', String(count)),
      tone: sourceTone(key),
      count,
    };
  });
}

function qualityIssues(t: ReturnType<typeof useT>, box: EditorBox): QualityIssueChip[] {
  const labelByIssue: Record<ReviewBoxQualityIssue, string> = {
    lowConfidence: t('batchWizard.step4.qualityIssueLowConfidence'),
    fallback: t('batchWizard.step4.qualityIssueFallback'),
    tableStructure: t('batchWizard.step4.qualityIssueTableStructure'),
    coarseMarkup: t('batchWizard.step4.qualityIssueCoarseMarkup'),
    largeRegion: t('batchWizard.step4.qualityIssueLargeRegion'),
    edgeSeal: t('batchWizard.step4.qualityIssueEdgeSeal'),
    seamSeal: t('batchWizard.step4.qualityIssueSeamSeal'),
    warning: t('batchWizard.step4.qualityIssueWarning'),
  };
  const titleByIssue: Record<ReviewBoxQualityIssue, string> = {
    lowConfidence: t('batchWizard.step4.qualityIssueLowConfidenceTitle'),
    fallback: t('batchWizard.step4.qualityIssueFallbackTitle'),
    tableStructure: t('batchWizard.step4.qualityIssueTableStructureTitle'),
    coarseMarkup: t('batchWizard.step4.qualityIssueCoarseMarkupTitle'),
    largeRegion: t('batchWizard.step4.qualityIssueLargeRegionTitle'),
    edgeSeal: t('batchWizard.step4.qualityIssueEdgeSealTitle'),
    seamSeal: t('batchWizard.step4.qualityIssueSeamSealTitle'),
    warning: t('batchWizard.step4.qualityIssueWarningTitle'),
  };
  return getReviewBoxQualityIssueKeys(box).map((issue) => ({
    key: issue,
    label: labelByIssue[issue],
    title: titleByIssue[issue],
  }));
}

interface VisibleReviewRegion {
  box: EditorBox;
  meta: { name: string; color: string };
  issues: QualityIssueChip[];
  source: SourceBadge | null;
  selected: boolean;
  dimensionLabel: string;
  ariaLabel: string;
  checkboxLabel: string;
}

interface ReviewRegionItemProps {
  region: VisibleReviewRegion;
  t: ReturnType<typeof useT>;
  toggleReviewBoxSelected: (id: string) => void;
}

function ReviewRegionItemInner({ region, t, toggleReviewBoxSelected }: ReviewRegionItemProps) {
  const { box, meta, issues, source, selected, dimensionLabel, ariaLabel, checkboxLabel } = region;
  const cardStyle = useMemo(
    () => ({
      borderColor: box.selected !== false ? meta.color : undefined,
      backgroundColor: box.selected === false ? undefined : `${meta.color}0d`,
    }),
    [box.selected, meta.color],
  );
  const typeStyle = useMemo(() => ({ color: meta.color }), [meta.color]);
  const handleToggle = useCallback(() => {
    toggleReviewBoxSelected(box.id);
  }, [box.id, toggleReviewBoxSelected]);
  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      toggleReviewBoxSelected(box.id);
    },
    [box.id, toggleReviewBoxSelected],
  );
  const stopCheckboxClick = useCallback((event: React.MouseEvent) => {
    event.stopPropagation();
  }, []);

  return (
    <div role="listitem">
      <div
        role="button"
        tabIndex={0}
        aria-label={ariaLabel}
        aria-pressed={selected}
        onClick={handleToggle}
        onKeyDown={handleKeyDown}
        className="w-full rounded-lg border px-2.5 py-1.5 text-left transition hover:border-muted-foreground/40"
        style={cardStyle}
        data-testid={`bbox-toggle-${box.id}`}
      >
        <div className="flex min-w-0 items-center gap-2">
          <Checkbox
            checked={box.selected !== false}
            aria-label={checkboxLabel}
            onClick={stopCheckboxClick}
            onCheckedChange={handleToggle}
          />
          <span className="min-w-0 truncate text-xs font-medium" style={typeStyle}>
            {meta.name}
          </span>
          <span className="ml-auto shrink-0 text-xs text-muted-foreground">{dimensionLabel}</span>
        </div>
        {box.text && (
          <p className="mt-0.5 truncate pl-6 text-xs text-muted-foreground">{box.text}</p>
        )}
        <div className="mt-1 flex min-w-0 flex-nowrap gap-1 overflow-hidden pl-6 text-[11px] text-muted-foreground">
          {box.confidence !== undefined && (
            <span className="shrink-0 whitespace-nowrap">
              {t('batchWizard.step4.confidence')} {Math.round(box.confidence * 100)}%
            </span>
          )}
          {source && (
            <span
              className={cn(
                'max-w-[11rem] truncate rounded-full border px-1.5 py-0.5 font-medium',
                source.tone === 'fallback'
                  ? 'border-[var(--warning-border)] bg-[var(--warning-surface)] text-[var(--warning-foreground)]'
                  : source.tone === 'model'
                    ? 'border-[var(--success-border)] bg-[var(--success-surface)] text-[var(--success-foreground)]'
                    : 'border-border bg-muted/40 text-muted-foreground',
              )}
              title={source.title}
              aria-label={`${t('batchWizard.step4.source')} ${source.label}. ${source.title}`}
              data-testid={`bbox-source-${box.id}`}
            >
              {t('batchWizard.step4.source')} {source.label}
            </span>
          )}
        </div>
        {issues.length > 0 && (
          <div
            className="mt-1 flex flex-nowrap gap-1 overflow-hidden pl-6"
            data-testid={`bbox-quality-${box.id}`}
            aria-label={`${t('batchWizard.step4.qualityIssues')} ${issues
              .map((issue) => issue.label)
              .join(', ')}`}
          >
            {issues.map((issue) => (
              <span
                key={issue.key}
                className="max-w-[8rem] truncate rounded-full border border-[var(--warning-border)] bg-[var(--warning-surface)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--warning-foreground)]"
                title={issue.title}
                aria-label={`${issue.label}. ${issue.title}`}
                data-testid={`bbox-quality-${box.id}-${issue.key}`}
              >
                {issue.label}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

const ReviewRegionItem = memo(ReviewRegionItemInner, (prev, next) => {
  const prevRegion = prev.region;
  const nextRegion = next.region;
  const prevBox = prevRegion.box;
  const nextBox = nextRegion.box;
  return (
    prev.t === next.t &&
    prev.toggleReviewBoxSelected === next.toggleReviewBoxSelected &&
    prevRegion.meta.name === nextRegion.meta.name &&
    prevRegion.meta.color === nextRegion.meta.color &&
    prevRegion.source?.label === nextRegion.source?.label &&
    prevRegion.source?.title === nextRegion.source?.title &&
    prevRegion.source?.tone === nextRegion.source?.tone &&
    prevRegion.selected === nextRegion.selected &&
    prevRegion.dimensionLabel === nextRegion.dimensionLabel &&
    prevRegion.ariaLabel === nextRegion.ariaLabel &&
    prevRegion.checkboxLabel === nextRegion.checkboxLabel &&
    prevRegion.issues.length === nextRegion.issues.length &&
    prevRegion.issues.every(
      (issue, index) =>
        issue.key === nextRegion.issues[index]?.key &&
        issue.label === nextRegion.issues[index]?.label &&
        issue.title === nextRegion.issues[index]?.title,
    ) &&
    prevBox.id === nextBox.id &&
    prevBox.type === nextBox.type &&
    prevBox.text === nextBox.text &&
    prevBox.x === nextBox.x &&
    prevBox.y === nextBox.y &&
    prevBox.width === nextBox.width &&
    prevBox.height === nextBox.height &&
    prevBox.selected === nextBox.selected &&
    prevBox.confidence === nextBox.confidence &&
    prevBox.source === nextBox.source &&
    prevBox.source_detail === nextBox.source_detail
  );
});

function ReviewImageContentInner({
  reviewBoxes,
  visibleReviewBoxes,
  reviewOrigImageBlobUrl,
  reviewImagePreviewSrc,
  reviewImagePreviewLoading,
  reviewCurrentPage,
  reviewTotalPages,
  selectedReviewBoxCount,
  totalReviewBoxCount,
  currentReviewVisionQuality,
  pipelines,
  onReviewPageChange,
  setVisibleReviewBoxes,
  handleReviewBoxesCommit,
  toggleReviewBoxSelected,
}: ReviewImageContentProps) {
  const t = useT();
  const tabsId = useId();
  const originalPanelId = `${tabsId}-original-panel`;
  const previewPanelId = `${tabsId}-preview-panel`;
  const regionsPanelId = `${tabsId}-regions-panel`;
  const originalTabId = `${tabsId}-original-tab`;
  const previewTabId = `${tabsId}-preview-tab`;
  const regionsTabId = `${tabsId}-regions-tab`;
  const [mobilePanel, setMobilePanel] = useState<'original' | 'preview' | 'regions'>('original');

  const visionTypeMetaById = useMemo(() => {
    const metaById = new Map<string, { name: string; color: string }>();
    pipelines.forEach((pipeline) => {
      pipeline.types.forEach((type) => {
        if (!metaById.has(type.id)) {
          metaById.set(type.id, { name: type.name, color: DEFAULT_VISION_TYPE_COLOR });
        }
      });
    });
    return metaById;
  }, [pipelines]);
  const getVisionTypeMeta = useCallback(
    (id: string) => visionTypeMetaById.get(id) ?? { name: id, color: DEFAULT_VISION_TYPE_COLOR },
    [visionTypeMetaById],
  );
  const visibleReviewRegions = useMemo<VisibleReviewRegion[]>(
    () =>
      visibleReviewBoxes.map((box) => {
        const meta = getVisionTypeMeta(box.type);
        const issues = qualityIssues(t, box);
        const source = sourceBadge(t, box);
        const selected = box.selected !== false;
        const dimensionLabel = `${Math.round(box.width * 100)}×${Math.round(box.height * 100)}%`;
        const boxLabelParts = [
          meta.name,
          box.text,
          dimensionLabel,
          box.confidence !== undefined
            ? `${t('batchWizard.step4.confidence')} ${Math.round(box.confidence * 100)}%`
            : '',
          source ? `${t('batchWizard.step4.source')} ${source.label}` : '',
          issues.length > 0
            ? `${t('batchWizard.step4.qualityIssues')} ${issues
                .map((issue) => issue.label)
                .join(', ')}`
            : '',
          selected ? t('batchWizard.step4.selected') : t('editor.deselected'),
        ].filter(Boolean);

        return {
          box,
          meta,
          issues,
          source,
          selected,
          dimensionLabel,
          ariaLabel: boxLabelParts.join(', '),
          checkboxLabel: t('batchWizard.step4.regionToggleLabel')
            .replace('{type}', meta.name)
            .replace('{text}', box.text || box.id),
        };
      }),
    [getVisionTypeMeta, t, visibleReviewBoxes],
  );
  const visibleQualityIssueCount = useMemo(
    () => visibleReviewRegions.reduce((count, region) => count + region.issues.length, 0),
    [visibleReviewRegions],
  );
  const visibleSourceSummary = useMemo(
    () => sourceSummaryChips(t, visibleReviewBoxes),
    [t, visibleReviewBoxes],
  );
  const hasVisibleBoxes = visibleReviewBoxes.length > 0;
  const allVisibleBoxesSelected =
    hasVisibleBoxes && selectedReviewBoxCount === visibleReviewBoxes.length;
  const noVisibleBoxesSelected = hasVisibleBoxes && selectedReviewBoxCount === 0;
  const tabClass = useCallback(
    (panel: typeof mobilePanel) =>
      cn(
        'h-8 flex-1 rounded-full px-3 text-xs',
        mobilePanel === panel ? 'bg-primary text-primary-foreground' : 'bg-transparent',
      ),
    [mobilePanel],
  );
  const showOriginalPanel = useCallback(() => setMobilePanel('original'), []);
  const showPreviewPanel = useCallback(() => setMobilePanel('preview'), []);
  const showRegionsPanel = useCallback(() => setMobilePanel('regions'), []);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      {reviewTotalPages > 1 && (
        <div className="shrink-0 border-b bg-muted/20 px-3 py-1.5">
          <PaginationRail
            page={reviewCurrentPage}
            pageSize={1}
            totalItems={reviewTotalPages}
            totalPages={reviewTotalPages}
            compact
            onPageChange={onReviewPageChange}
            testIdPrefix="review-page"
          />
        </div>
      )}
      {currentReviewVisionQuality &&
        (currentReviewVisionQuality.warnings.length > 0 ||
          Object.keys(currentReviewVisionQuality.pipeline_status).length > 0) && (
          <div
            className="shrink-0 border-b bg-muted/20 px-3 py-2"
            data-testid="review-image-pipeline-quality"
            role="status"
            aria-live="polite"
            aria-atomic="true"
          >
            <div className="flex flex-nowrap items-center gap-1.5 overflow-x-auto pb-0.5">
              {Object.entries(currentReviewVisionQuality.pipeline_status).map(([key, status]) => (
                <span
                  key={key}
                  className={cn(
                    'shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium',
                    status.failed
                      ? 'border-destructive/30 bg-destructive/5 text-destructive'
                      : status.skipped
                        ? 'border-border bg-[var(--surface-control)] text-muted-foreground'
                        : 'border-[var(--success-border)] bg-[var(--success-surface)] text-[var(--success-foreground)]',
                  )}
                  title={typeof status.error === 'string' ? status.error : undefined}
                >
                  {pipelineLabel(t, key)} {pipelineStateLabel(t, status)}
                  {typeof status.region_count === 'number' ? ` ${status.region_count}` : ''}
                </span>
              ))}
              {currentReviewVisionQuality.warnings.map((warning) => (
                <span
                  key={warning}
                  className="shrink-0 rounded-full border border-[var(--warning-border)] bg-[var(--warning-surface)] px-2 py-0.5 text-[11px] font-medium text-[var(--warning-foreground)]"
                >
                  {warning}
                </span>
              ))}
            </div>
          </div>
        )}
      <div
        className="flex shrink-0 gap-1 border-b bg-muted/20 p-1 lg:hidden"
        role="tablist"
        aria-label={t('batchWizard.step4.imageReviewPanels')}
      >
        <Button
          type="button"
          id={originalTabId}
          role="tab"
          aria-selected={mobilePanel === 'original'}
          aria-controls={originalPanelId}
          variant="ghost"
          className={tabClass('original')}
          onClick={showOriginalPanel}
          data-testid="review-image-tab-original"
        >
          {t('batchWizard.step4.originalImage')}
        </Button>
        <Button
          type="button"
          id={previewTabId}
          role="tab"
          aria-selected={mobilePanel === 'preview'}
          aria-controls={previewPanelId}
          variant="ghost"
          className={tabClass('preview')}
          onClick={showPreviewPanel}
          data-testid="review-image-tab-preview"
        >
          {t('batchWizard.step4.previewImage')}
        </Button>
        <Button
          type="button"
          id={regionsTabId}
          role="tab"
          aria-selected={mobilePanel === 'regions'}
          aria-controls={regionsPanelId}
          variant="ghost"
          className={tabClass('regions')}
          onClick={showRegionsPanel}
          data-testid="review-image-tab-regions"
        >
          {t('batchWizard.step4.detectionRegions')}
        </Button>
      </div>
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <div
          id={originalPanelId}
          role="tabpanel"
          aria-labelledby={originalTabId}
          className={cn(
            'min-h-0 min-w-0 flex-[2] flex-col border-r',
            mobilePanel === 'original' ? 'flex' : 'hidden',
            'lg:flex',
          )}
        >
          <div className="flex h-8 shrink-0 items-center gap-1.5 border-b !bg-white px-2">
            <span className="text-xs font-medium">{t('batchWizard.step4.originalImage')}</span>
          </div>
          <div className="relative min-h-0 flex-1">
            {reviewOrigImageBlobUrl ? (
            <div className="absolute inset-0 !bg-white">
                <ImageBBoxEditor
                  imageSrc={reviewOrigImageBlobUrl}
                  boxes={visibleReviewBoxes}
                  onBoxesChange={setVisibleReviewBoxes}
                  onBoxesCommit={handleReviewBoxesCommit}
                  getTypeConfig={getVisionTypeMeta}
                />
              </div>
            ) : (
              <div className="flex h-full items-center justify-center !bg-white">
                <p className="text-sm text-muted-foreground">
                  {reviewImagePreviewLoading
                    ? t('batchWizard.step4.generating')
                    : t('batchWizard.step4.noBoxes')}
                </p>
              </div>
            )}
          </div>
        </div>

        <div
          id={previewPanelId}
          role="tabpanel"
          aria-labelledby={previewTabId}
          className={cn(
            'min-w-0 flex-[2] flex-col overflow-hidden border-r',
            mobilePanel === 'preview' ? 'flex' : 'hidden',
            'lg:flex',
          )}
        >
          <div className="flex h-8 shrink-0 items-center gap-1.5 border-b !bg-white px-2">
            <span className="text-xs font-medium">{t('batchWizard.step4.previewImage')}</span>
            <span className="ml-auto text-xs text-muted-foreground">
              {reviewImagePreviewLoading
                ? t('batchWizard.step4.generating')
                : `${selectedReviewBoxCount}/${visibleReviewBoxes.length} ${t('batchWizard.step4.selected')}`}
            </span>
          </div>
          {/* Spacer matches the internal toolbar of ImageBBoxEditor so both
            image panes have identical top offsets and the two renders align
            pixel-for-pixel along the top and bottom edges. */}
          <div
            className="h-[42px] shrink-0 border-b border-border/70 !bg-white"
            aria-hidden="true"
          />
          <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto !bg-white">
            {reviewImagePreviewSrc ? (
              <img
                src={reviewImagePreviewSrc}
                alt={t('batchWizard.step4.previewImage')}
                className="max-h-full max-w-full object-contain"
              />
            ) : (
              <p className="text-sm text-muted-foreground">
                {reviewImagePreviewLoading
                  ? t('batchWizard.step4.generating')
                  : t('batchWizard.step4.previewNotReady')}
              </p>
            )}
          </div>
        </div>

        <div
          id={regionsPanelId}
          role="tabpanel"
          aria-labelledby={regionsTabId}
          className={cn(
            'min-h-0 min-w-0 flex-[1] flex-col bg-background lg:min-w-[220px] lg:max-w-[300px] 2xl:max-w-[320px]',
            mobilePanel === 'regions' ? 'flex' : 'hidden',
            'lg:flex',
          )}
        >
          <div className="flex shrink-0 items-center border-b px-2 py-1.5">
            <span className="text-xs font-medium">{t('batchWizard.step4.detectionRegions')}</span>
            <span className="ml-auto text-xs tabular-nums text-muted-foreground">
              {selectedReviewBoxCount}/{visibleReviewBoxes.length}
            </span>
          </div>
          <div className="truncate px-2 pb-1 pt-1 text-[11px] text-muted-foreground">
            {reviewTotalPages > 1
              ? `${t('jobs.showRange')
                  .replace('{start}', String(reviewCurrentPage))
                  .replace('{end}', String(reviewCurrentPage))
                  .replace('{total}', String(reviewTotalPages))} | ${totalReviewBoxCount}`
              : `${totalReviewBoxCount}`}
          </div>
          {hasVisibleBoxes && visibleSourceSummary.length > 0 && (
            <div
              className="mx-2 mb-1 flex flex-nowrap gap-1 overflow-hidden"
              data-testid="review-image-source-summary"
              role="status"
              aria-live="polite"
              aria-label={t('batchWizard.step4.sourceSummary')}
            >
              {visibleSourceSummary.map((source) => (
                <span
                  key={source.key}
                  className={cn(
                    'max-w-[8.5rem] truncate rounded-full border px-1.5 py-0.5 text-[10px] font-medium leading-4',
                    source.tone === 'fallback'
                      ? 'border-[var(--warning-border)] bg-[var(--warning-surface)] text-[var(--warning-foreground)]'
                      : source.tone === 'model'
                        ? 'border-[var(--success-border)] bg-[var(--success-surface)] text-[var(--success-foreground)]'
                        : 'border-border bg-muted/40 text-muted-foreground',
                  )}
                  title={source.title}
                  aria-label={source.title}
                  data-testid={`review-image-source-summary-${source.key}`}
                >
                  {source.label} {source.count}
                </span>
              ))}
            </div>
          )}
          {visibleQualityIssueCount > 0 && (
            <div
              className="mx-2 mb-1 rounded-md border border-[var(--warning-border)] bg-white px-2 py-1 text-[11px] text-[var(--warning-foreground)]"
              data-testid="review-image-quality-summary"
              role="status"
              aria-live="polite"
            >
              <p className="font-semibold">
                {t('batchWizard.step4.qualityIssueSummary').replace(
                  '{count}',
                  String(visibleQualityIssueCount),
                )}
              </p>
            </div>
          )}
          {hasVisibleBoxes && (
            <div
              className={cn(
                'mx-2 mb-1 rounded-md border px-2 py-1 text-[11px] leading-4',
                noVisibleBoxesSelected
                  ? 'border-[var(--warning-border)] bg-white text-[var(--warning-foreground)]'
                  : 'border-border bg-white text-muted-foreground',
              )}
              data-testid="review-image-selection-summary"
              role="status"
              aria-live="polite"
              aria-atomic="true"
            >
              {allVisibleBoxesSelected
                ? `${t('batchWizard.step4.selected')} ${selectedReviewBoxCount}/${visibleReviewBoxes.length}`
                : `${selectedReviewBoxCount}/${visibleReviewBoxes.length} ${t('batchWizard.step4.selected')}`}
            </div>
          )}
          <div
            className="flex flex-1 flex-col gap-1.5 overflow-y-auto p-2 pt-1"
            role="list"
            aria-label={t('batchWizard.step4.detectionRegions')}
          >
            {!hasVisibleBoxes && (
              <div
                className="rounded-xl border border-dashed border-border bg-white px-3 py-6 text-center"
                data-testid="review-image-empty-regions"
              >
                <p className="text-sm font-medium text-foreground">
                  {t('batchWizard.step4.noBoxes')}
                </p>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  P{reviewCurrentPage} / {reviewTotalPages}
                </p>
              </div>
            )}
            {visibleReviewRegions.map((region) => (
              <ReviewRegionItem
                key={region.box.id}
                region={region}
                t={t}
                toggleReviewBoxSelected={toggleReviewBoxSelected}
              />
            ))}
          </div>
          <div className="border-t px-2 py-1.5 text-[11px] text-muted-foreground">
            {reviewBoxes.length} {t('batchWizard.step4.detectionRegions')}
          </div>
        </div>
      </div>
    </div>
  );
}

export const ReviewImageContent = memo(ReviewImageContentInner);
