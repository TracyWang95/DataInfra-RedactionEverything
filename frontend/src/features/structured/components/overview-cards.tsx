// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, CheckCircle2, Layers, PackageCheck, ShieldCheck } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { useT } from '@/i18n';
import type { StructuredDataset } from '@/services/structuredApi';
import { deliveryUrlForDataset } from '../lib/dataset-utils';

export function StructuredPathCard({
  datasetCount,
  connectionCount,
  deliverableCount,
  pendingReviewCount,
}: {
  datasetCount: number;
  connectionCount: number;
  deliverableCount: number;
  pendingReviewCount: number;
}) {
  const t = useT();
  const steps = [
    {
      title: t('structured.overview.path.step1.title'),
      desc: datasetCount > 0 ? t('structured.overview.path.step1.descDone') : t('structured.overview.path.step1.descTodo'),
      Icon: Layers,
      done: datasetCount > 0,
      active: datasetCount === 0,
      status:
        datasetCount > 0
          ? t('structured.overview.path.step1.statusCount').replace('{count}', String(datasetCount))
          : t('structured.overview.path.step1.statusTodo'),
    },
    {
      title: t('structured.overview.path.step2.title'),
      desc:
        datasetCount === 0
          ? t('structured.overview.path.step2.descTodo')
          : pendingReviewCount > 0
            ? t('structured.overview.path.step2.descPending').replace('{count}', String(pendingReviewCount))
            : t('structured.overview.path.step2.descDone'),
      Icon: ShieldCheck,
      done: datasetCount > 0 && pendingReviewCount === 0,
      active: datasetCount > 0 && pendingReviewCount > 0,
      status: datasetCount > 0 ? `${deliverableCount}/${datasetCount}` : t('structured.overview.path.step2.statusTodo'),
    },
    {
      title: t('structured.overview.path.step3.title'),
      desc: deliverableCount > 0 ? t('structured.overview.path.step3.descDone') : t('structured.overview.path.step3.descTodo'),
      Icon: PackageCheck,
      done: deliverableCount > 0,
      active: deliverableCount > 0,
      status: deliverableCount > 0 ? t('structured.overview.path.step3.statusReady') : t('structured.common.pendingReview'),
    },
  ];
  return (
    <Card className="page-surface border-border/70 shadow-[var(--shadow-control)]">
      <CardHeader className="px-4 py-3">
        <CardTitle className="text-sm">{t('structured.overview.path.title')}</CardTitle>
        <CardDescription>{t('structured.overview.path.description')}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-2 px-4 pb-4 pt-0">
        {steps.map(({ title, desc, Icon, done, active, status }) => {
          return (
            <div
              key={title}
              data-testid="structured-path-step"
              data-path-title={title}
              className={cn(
                'grid min-h-11 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 rounded-xl border border-border px-3 py-1.5',
                active && 'bg-muted/35',
              )}
            >
              <span
                className={cn(
                  'grid size-9 place-items-center rounded-xl border',
                  done ? 'border-[var(--success-border)] bg-[var(--success-surface)]' : 'border-border bg-muted/25',
                )}
              >
                {done ? <CheckCircle2 className="size-4 text-[var(--success-foreground)]" /> : <Icon className="size-4" />}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-sm font-semibold">{title}</span>
                <span className="block truncate text-xs text-muted-foreground">{desc}</span>
              </span>
              <Badge variant="outline" className="rounded-full">
                {status}
              </Badge>
            </div>
          );
        })}
        <div className="rounded-xl border border-border bg-muted/25 px-3 py-2 text-xs text-muted-foreground">
          {t('structured.overview.path.footer').replace('{count}', String(connectionCount))}
        </div>
      </CardContent>
    </Card>
  );
}

export function StructuredNextActionCard({
  dataset,
  deliveryDataset,
  datasetCount,
  deliverableCount,
  pendingReviewCount,
}: {
  dataset: StructuredDataset | null;
  deliveryDataset: StructuredDataset | null;
  datasetCount: number;
  deliverableCount: number;
  pendingReviewCount: number;
}) {
  const t = useT();
  const hasDataset = Boolean(dataset);
  const hasPendingReview = pendingReviewCount > 0;
  const primaryTarget = dataset
    ? `/structured/datasets?datasetId=${encodeURIComponent(dataset.id)}`
    : '/structured/files';
  const primaryLabel = !hasDataset
    ? t('structured.overview.next.primaryImport')
    : hasPendingReview
      ? t('structured.overview.next.primaryReview')
      : t('structured.overview.next.primaryView');
  const secondaryTarget =
    deliverableCount > 0
      ? '/structured/delivery'
      : deliveryDataset
        ? deliveryUrlForDataset(deliveryDataset)
        : '/structured/database';
  const secondaryLabel =
    deliverableCount > 0
      ? t('structured.overview.next.secondaryDeliver')
      : deliveryDataset
        ? t('structured.overview.next.secondaryPrepare')
        : t('structured.overview.next.secondaryConnect');
  const description =
    datasetCount === 0
      ? t('structured.overview.next.descEmpty')
      : hasPendingReview
        ? t('structured.overview.next.descPending').replace('{count}', String(pendingReviewCount))
        : t('structured.overview.next.descDone');

  return (
    <Card className="page-surface border-border/70 shadow-[var(--shadow-control)]">
      <CardHeader className="px-4 py-3">
        <CardTitle className="text-sm">{t('structured.overview.next.title')}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 px-4 pb-4 pt-0">
        <div className="grid min-h-20 content-center rounded-xl border border-border bg-muted/25 px-3 py-2">
          <span className="text-xs font-semibold text-muted-foreground">
            {hasPendingReview ? t('structured.overview.next.pendingTarget') : t('structured.overview.next.currentTarget')}
          </span>
          <span className="mt-1 truncate text-sm font-semibold" title={dataset?.name}>
            {dataset?.name ?? t('structured.common.noDatasets')}
          </span>
          <span className="mt-1 truncate text-xs text-muted-foreground">
            {dataset
              ? t('structured.common.datasetMeta')
                  .replace('{kind}', dataset.source_kind.toUpperCase())
                  .replace('{columns}', String(dataset.column_count))
                  .replace('{rows}', String(dataset.row_count_estimate ?? 0))
              : t('structured.overview.next.autoHint')}
          </span>
        </div>
        <Button asChild className="h-9 justify-between rounded-xl" size="sm">
          <Link to={primaryTarget}>
            {primaryLabel}
            <ArrowRight className="size-4" />
          </Link>
        </Button>
        <Button asChild variant="outline" className="h-9 justify-between rounded-xl" size="sm">
          <Link to={secondaryTarget}>
            {secondaryLabel}
            <ArrowRight className="size-4" />
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}

export function StructuredSourceMixCard({
  fileCount,
  dbCount,
  connectionCount,
}: {
  fileCount: number;
  dbCount: number;
  connectionCount: number;
}) {
  const t = useT();
  const total = fileCount + dbCount;
  const filePct = total > 0 ? Math.round((fileCount / total) * 100) : 0;
  const dbPct = total > 0 ? 100 - filePct : 0;
  return (
    <Card className="page-surface border-border/70 shadow-[var(--shadow-control)]">
      <CardHeader className="px-4 py-3">
        <CardTitle className="text-sm">{t('structured.overview.mix.title')}</CardTitle>
        <CardDescription>{t('structured.overview.mix.description')}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 px-4 pb-4 pt-0">
        <div className="grid gap-2 rounded-xl border border-border bg-muted/25 p-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">{t('structured.overview.mix.registered')}</span>
            <span className="font-semibold">{total}</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div className="flex h-full">
              <span className="bg-foreground" style={{ width: `${filePct}%` }} />
              <span className="bg-[var(--success-foreground)]" style={{ width: `${dbPct}%` }} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <SourceMixItem label={t('structured.overview.mix.fileLabel')} value={fileCount} percent={filePct} tone="file" />
            <SourceMixItem label={t('structured.overview.mix.dbLabel')} value={dbCount} percent={dbPct} tone="db" />
          </div>
        </div>
        <div className="grid min-h-11 content-center rounded-xl border border-border px-3 py-1.5 text-sm">
          <span className="text-xs text-muted-foreground">{t('structured.overview.mix.readonly')}</span>
          <span className="mt-0.5 font-semibold">
            {t('structured.overview.mix.connectionSummary').replace('{count}', String(connectionCount))}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

function SourceMixItem({
  label,
  value,
  percent,
  tone,
}: {
  label: string;
  value: number;
  percent: number;
  tone: 'file' | 'db';
}) {
  return (
    <span className="grid gap-0.5 rounded-lg bg-background px-2 py-1.5">
      <span className="flex items-center gap-1 text-muted-foreground">
        <span
          className={cn(
            'size-2 rounded-full',
            tone === 'file' ? 'bg-foreground' : 'bg-[var(--success-foreground)]',
          )}
        />
        {label}
      </span>
      <span className="font-semibold">
        {value} · {percent}%
      </span>
    </span>
  );
}

export function MetricCard({
  label,
  value,
  helper,
  icon: Icon,
}: {
  label: string;
  value: string;
  helper?: string;
  icon?: React.FC<{ className?: string }>;
}) {
  return (
    <Card className="page-surface border-border/70 shadow-[var(--shadow-control)]" data-testid="structured-metric-card">
      <CardContent className="flex min-h-20 items-start justify-between gap-3 px-4 py-2.5">
        <span className="min-w-0">
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="mt-1 text-2xl font-semibold tracking-tight">{value}</p>
          {helper ? <p className="mt-1 truncate text-xs text-muted-foreground">{helper}</p> : null}
        </span>
        {Icon ? (
          <span className="grid size-9 shrink-0 place-items-center rounded-xl border border-border bg-muted text-muted-foreground">
            <Icon className="size-4" />
          </span>
        ) : null}
      </CardContent>
    </Card>
  );
}
