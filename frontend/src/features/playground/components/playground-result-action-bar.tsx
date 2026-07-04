// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useState, type FC } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { getEntityTypeName } from '@/config/entityTypes';
import { useI18n, useT } from '@/i18n';
import { cn } from '@/lib/utils';
import type { FileInfo } from '../types';

export interface PlaygroundResultActionBarProps {
  fileInfo: FileInfo | null;
  redactedCount: number;
  resultReady?: boolean;
  canDownload?: boolean;
  onBackToEdit: () => void;
  onReset: () => void;
  onDownload: () => void | Promise<void>;
}

export const PlaygroundResultActionBar: FC<PlaygroundResultActionBarProps> = ({
  fileInfo,
  redactedCount,
  resultReady = true,
  canDownload = true,
  onBackToEdit,
  onReset,
  onDownload,
}) => {
  const t = useT();
  const locale = useI18n((state) => state.locale);
  const flowCopy = resultActionFlowCopy(locale, redactedCount);
  const [downloading, setDownloading] = useState(false);

  const handleDownloadClick = () => {
    if (downloading) return;
    setDownloading(true);
    void Promise.resolve(onDownload()).finally(() => setDownloading(false));
  };

  return (
    <div className="mb-3 flex-shrink-0">
      <Card className="border-0 bg-foreground text-background shadow-[var(--shadow-floating)]">
        <CardContent className="flex items-center justify-between gap-3 px-4 py-3.5 sm:px-5">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-2xl bg-background/10 backdrop-blur-sm">
              <svg className="size-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"
                />
              </svg>
            </div>
            <div className="min-w-0">
              <p className="text-sm font-semibold">
                {resultReady ? t('playground.redactComplete') : t('playground.redactedPreviewPreparing')}
              </p>
              <p className="truncate text-xs text-background/70">{flowCopy.countLabel}</p>
              <div className="mt-1.5 hidden items-center gap-1.5 lg:flex">
                {flowCopy.steps.map((step, index) => (
                  <span
                    key={step}
                    className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full border border-background/35 px-2 py-0.5 text-[11px] font-medium"
                  >
                    <span className="grid size-4 place-items-center rounded-full bg-background/20 text-[10px]">
                      {index + 1}
                    </span>
                    <span>{step}</span>
                  </span>
                ))}
              </div>
              <p className="mt-1 hidden truncate text-[11px] leading-snug text-background/80 xl:block">
                {flowCopy.hint}
              </p>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={onBackToEdit}
              data-testid="playground-back-edit"
              className="h-9 whitespace-nowrap px-3"
            >
              {t('playground.backToEdit')}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={onReset}
              className="h-9 whitespace-nowrap px-3"
            >
              {t('playground.newFile')}
            </Button>
            {fileInfo && canDownload && (
              <Button
                size="sm"
                variant="default"
                onClick={handleDownloadClick}
                disabled={downloading}
                data-testid="playground-download"
                className="h-9 whitespace-nowrap px-3"
              >
                {downloading ? t('common.downloading') : t('playground.downloadFile')}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export const RedactionReportSection: FC<{
  report: Record<string, unknown>;
  open: boolean;
  onToggle: () => void;
}> = ({ report, open, onToggle }) => {
  const t = useT();
  const total = numberFrom(report.total_entities);
  const redacted = numberFrom(report.redacted_entities);
  const unprocessed = Math.max(total - redacted, 0);
  const coverage = Number.isFinite(numberFrom(report.coverage_rate))
    ? numberFrom(report.coverage_rate)
    : total > 0
      ? Math.round((redacted / total) * 1000) / 10
      : 0;
  const typeRows = distributionRows(report.entity_type_distribution, getEntityTypeName);
  const sourceRows = distributionRows(report.source_distribution, (key) => sourceLabel(key, t));
  const confidenceRows = distributionRows(report.confidence_distribution, (key) =>
    confidenceLabel(key, t),
  );
  const redactionMode = String(report.redaction_mode || '');

  return (
    <div className="mb-3 flex-shrink-0">
      <Button
        variant="outline"
        className="h-10 w-full justify-between rounded-[20px] px-4 py-0"
        onClick={onToggle}
      >
        <span className="truncate text-xs font-semibold">{t('playground.qualityReport')}</span>
        <svg
          className={cn('size-4 shrink-0 transition-transform', open && 'rotate-180')}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </Button>
      {open && (
        <Card className="-mt-1 rounded-t-none px-4 pb-3 pt-2.5">
          <CardContent className="space-y-3 p-0 text-xs" data-testid="playground-quality-report">
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
              <ReportMetric label={t('playground.totalEntities')} value={total} />
              <ReportMetric label={t('playground.redactedEntities')} value={redacted} />
              <ReportMetric label={t('playground.unprocessedEntities')} value={unprocessed} />
              <ReportMetric label={t('report.coverage')} value={`${coverage.toFixed(1)}%`} />
            </div>
            <div className="grid gap-2.5 md:grid-cols-3">
              <DistributionBlock title={t('report.typeDistribution')} rows={typeRows} />
              <DistributionBlock title={t('playground.sourceDistribution')} rows={sourceRows} />
              <DistributionBlock title={t('report.confidenceDistribution')} rows={confidenceRows} />
            </div>
            {redactionMode && (
              <div className="rounded-xl border border-border/70 bg-muted/25 px-3 py-2">
                <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {t('playground.reportMode')}
                </span>
                <p className="mt-1 text-sm font-medium text-foreground">{redactionMode}</p>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
};

const ReportMetric: FC<{ label: string; value: string | number }> = ({ label, value }) => (
  <div className="min-w-0 rounded-xl border border-border/70 bg-muted/25 px-3 py-2">
    <span className="block truncate text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</span>
    <span className="mt-1 block text-lg font-bold tabular-nums">{String(value)}</span>
  </div>
);

const DistributionBlock: FC<{ title: string; rows: Array<[string, number]> }> = ({
  title,
  rows,
}) => (
  <div className="min-w-0 rounded-xl border border-border/70 px-3 py-2">
    <span className="block truncate text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</span>
    <div className="mt-2 space-y-1.5">
      {rows.length > 0 ? (
        rows.map(([label, count]) => (
          <div key={label} className="flex items-center justify-between gap-3">
            <span className="truncate text-muted-foreground">{label}</span>
            <span className="font-semibold tabular-nums text-foreground">{count}</span>
          </div>
        ))
      ) : (
        <span className="text-muted-foreground">-</span>
      )}
    </div>
  </div>
);

function numberFrom(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function distributionRows(value: unknown, labelForKey: (key: string) => string) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
  return Object.entries(value as Record<string, unknown>)
    .map(([key, count]) => [labelForKey(key), numberFrom(count)] as [string, number])
    .filter(([, count]) => count > 0)
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]));
}

function sourceLabel(key: string, t: (key: string) => string) {
  if (key === 'regex') return t('playground.sourceRegex');
  if (key === 'manual') return t('playground.sourceManual');
  if (key === 'has') return 'HaS';
  if (key === 'llm') return t('playground.sourceAi');
  return key;
}

function confidenceLabel(key: string, t: (key: string) => string) {
  if (key === 'high') return t('report.high');
  if (key === 'medium') return t('report.medium');
  if (key === 'low') return t('report.low');
  return key;
}

function resultActionFlowCopy(locale: 'en' | 'zh', redactedCount: number) {
  if (locale === 'zh') {
    return {
      countLabel: `\u5df2\u5904\u7406 ${redactedCount} \u4e2a\u654f\u611f\u9879`,
      steps: ['\u8bc6\u522b', '\u590d\u6838', '\u5bfc\u51fa'] as const,
      hint: '\u5148\u590d\u6838\u9ad8\u4eae\u5185\u5bb9\uff0c\u786e\u8ba4\u65e0\u8bef\u540e\u5bfc\u51fa\u3002',
    };
  }

  return {
    countLabel: `${redactedCount} sensitive item${redactedCount === 1 ? '' : 's'} redacted`,
    steps: ['Recognize', 'Review', 'Export'] as const,
    hint: 'Review the result first, then export when it looks correct.',
  };
}
