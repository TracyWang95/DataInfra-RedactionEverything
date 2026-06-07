// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { Link } from 'react-router-dom';
import {
  ArrowRight,
  CheckCircle2,
  Files,
  History,
  ListChecks,
  PlayCircle,
} from 'lucide-react';
import { useI18n, useT } from '@/i18n';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardTitle } from '@/components/ui/card';
import { useServiceHealth } from '@/hooks/use-service-health';
import { BatchHubJobList } from './components/batch-hub-job-list';
import { useBatchHub } from './hooks/use-batch-hub';
import type { BatchWizardMode } from '@/services/batchPipeline';
import type { Locale } from '@/i18n';

type ModeCard = {
  mode: BatchWizardMode;
  icon: typeof Files;
  titleKey: string;
  descKey: string;
  titleHint?: string;
  descHint?: string;
  tagKeys: string[];
  summaryKey: string;
  testId: string;
};

type LocalCopy = Record<Locale, string>;

const PRIMARY_MODE: ModeCard = {
  mode: 'smart',
  icon: Files,
  titleKey: 'batchHub.mode.smart.title',
  descKey: 'batchHub.mode.smart.desc',
  tagKeys: ['batchHub.mode.smart.tag1', 'batchHub.mode.text.tag1', 'batchHub.mode.image.tag1'],
  summaryKey: 'batchHub.mode.smart.summaryValue',
  testId: 'batch-launch-smart',
};

function getLocalCopy(
  t: (key: string) => string,
  locale: Locale,
  key: string,
  fallback: LocalCopy,
) {
  const translated = t(key);
  return translated === key ? fallback[locale] : translated;
}

export function BatchHub() {
  const t = useT();
  const locale = useI18n((state) => state.locale);
  const {
    loading,
    tableLoading,
    jobsUnavailable,
    activeJobs,
    openBatch,
    continueJob,
    openPreview,
  } = useBatchHub();
  const { health, checking: healthChecking } = useServiceHealth();
  const modelServicesLimited = Boolean(health && !health.all_online && !healthChecking);
  const batchEntryBlocked = jobsUnavailable;
  const getBlockedReason = (_mode: BatchWizardMode) => {
    if (jobsUnavailable) return t('batchHub.liveDisabledBackend');
    return undefined;
  };
  const primaryTitle = getLocalCopy(t, locale, 'batchHub.primary.title', {
    en: 'Process multiple files',
    zh: '\u5904\u7406\u591a\u4e2a\u6587\u4ef6',
  });
  const primaryDesc = getLocalCopy(t, locale, 'batchHub.primary.desc', {
    en: 'Upload Word, PDF, scan, and image files together. The default mixed workflow keeps recognition, review, and export in one queue.',
    zh: '\u4e0a\u4f20 Word\u3001PDF\u3001\u626b\u63cf\u4ef6\u548c\u56fe\u7247\u6df7\u5408\u6279\u6b21\uff0c\u9ed8\u8ba4\u7528\u540c\u4e00\u961f\u5217\u5b8c\u6210\u8bc6\u522b\u3001\u590d\u6838\u548c\u5bfc\u51fa\u3002',
  });
  const mixedModeNote =
    locale === 'zh'
      ? '\u5927\u591a\u6570\u7528\u6237\u5e94\u5148\u4ece\u878d\u5408\u6587\u4ef6\u5f00\u59cb\u3002'
      : 'Most users should start with mixed-file batches.';

  return (
    <div className="saas-page flex h-full min-h-0 overflow-hidden bg-background">
      <div className="page-shell-narrow !max-w-[min(100%,2048px)] !px-3 !py-3 sm:!px-4 2xl:!px-5">
        <div className="page-stack gap-3 overflow-hidden">
          <section className="saas-panel flex shrink-0 flex-nowrap items-start justify-between gap-3 rounded-[20px] border-border/70 bg-card/95 p-3 shadow-[var(--shadow-control)]">
            <div className="flex min-w-0 flex-col items-start gap-1.5">
              <span className="saas-kicker">{t('batchHub.kicker')}</span>
              <h1
                className="truncate text-2xl font-semibold tracking-tight text-foreground"
                data-testid="batch-hub-title"
              >
                {t('batchHub.title')}
              </h1>
              <p className="max-w-4xl text-sm leading-6 text-muted-foreground">
                {t('batchHub.desc')}
              </p>
            </div>
            <div className="flex shrink-0 flex-nowrap items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                className="h-9 rounded-xl whitespace-nowrap"
                asChild
              >
                <Link to="/jobs">
                  <ListChecks className="mr-2 size-4" />
                  {t('batchHub.jobCenter')}
                </Link>
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-9 rounded-xl whitespace-nowrap"
                asChild
              >
                <Link to="/history">
                  <History className="mr-2 size-4" />
                  {t('batchHub.history')}
                </Link>
              </Button>
            </div>
          </section>

          {jobsUnavailable && (
            <Alert data-testid="batch-hub-preview-alert">
              <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
                <span>{t('batchHub.previewDesc')}</span>
                <Button variant="outline" size="sm" onClick={() => openPreview('smart')}>
                  {t('batchHub.previewCta')}
                </Button>
              </AlertDescription>
            </Alert>
          )}

          {!jobsUnavailable && modelServicesLimited && (
            <Alert data-testid="batch-hub-model-preview-alert">
              <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
                <span>{t('batchHub.modelPreviewDesc')}</span>
                <Button variant="outline" size="sm" onClick={() => openPreview('smart')}>
                  {t('batchHub.previewCta')}
                </Button>
              </AlertDescription>
            </Alert>
          )}

          <JourneyRail locale={locale} />

          <section className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden">
            <PrimaryBatchEntry
              item={PRIMARY_MODE}
              title={primaryTitle}
              desc={primaryDesc}
              journeyNote={mixedModeNote}
              liveBlocked={batchEntryBlocked}
              liveBlockedReason={getBlockedReason('smart')}
              onOpenLive={() => openBatch('smart')}
              onOpenPreview={() => openPreview('smart')}
            />
            <BatchHubJobList
              jobs={activeJobs}
              loading={loading}
              tableLoading={tableLoading}
              onContinue={continueJob}
            />
          </section>
        </div>
      </div>
    </div>
  );
}

function JourneyRail({ locale }: { locale: Locale }) {
  const copy =
    locale === 'zh'
      ? [
          {
            title: '\u5f15\u5bfc',
            desc: '\u786e\u8ba4\u670d\u52a1\u4e0e\u5904\u7406\u8def\u5f84',
            cta: '\u67e5\u770b\u5f15\u5bfc',
            href: '/',
            Icon: CheckCircle2,
          },
          {
            title: '\u5355\u6b21',
            desc: '\u5148\u7528\u4e00\u4e2a\u6587\u4ef6\u9a8c\u8bc1\u89c4\u5219',
            cta: '\u5355\u6b21\u9a8c\u8bc1',
            href: '/playground',
            Icon: PlayCircle,
          },
          {
            title: '\u6279\u91cf',
            desc: '\u786e\u8ba4\u540e\u542f\u52a8\u6df7\u5408\u6279\u6b21',
            cta: '\u5f53\u524d\u9875\u9762',
            Icon: Files,
          },
        ]
      : [
          {
            title: 'Guide',
            desc: 'Confirm service readiness and the right path.',
            cta: 'Open guide',
            href: '/',
            Icon: CheckCircle2,
          },
          {
            title: 'Single',
            desc: 'Validate rules with one file first.',
            cta: 'Run single file',
            href: '/playground',
            Icon: PlayCircle,
          },
          {
            title: 'Batch',
            desc: 'Start mixed batches after validation.',
            cta: 'Current page',
            Icon: Files,
          },
        ];

  return (
    <Card
      className="page-surface !flex-none border-border/70 shadow-[var(--shadow-control)]"
      data-testid="batch-journey-rail"
    >
      <CardContent className="grid gap-2 p-3 sm:grid-cols-3">
        {copy.map(({ title, desc, cta, href, Icon }, index) => {
          const active = index === copy.length - 1;

          return (
            <div
              key={title}
              className={`grid min-h-[4.25rem] grid-cols-[2.25rem_minmax(0,1fr)_auto] items-center gap-3 rounded-xl border px-3 py-2 ${
                active ? 'border-foreground bg-muted/50' : 'border-border/70 bg-background/70'
              }`}
            >
              <span
                className={`flex size-9 items-center justify-center rounded-xl ${
                  active ? 'bg-foreground text-background' : 'bg-muted text-foreground'
                }`}
              >
                <Icon className="size-4" />
              </span>
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-muted-foreground">
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  <span className="truncate text-sm font-semibold">{title}</span>
                </div>
                <p className="mt-0.5 truncate text-xs leading-5 text-muted-foreground" title={desc}>
                  {desc}
                </p>
              </div>
              {href ? (
                <Button variant="ghost" size="sm" className="h-8 rounded-lg px-2 text-xs" asChild>
                  <Link to={href}>
                    {cta}
                    <ArrowRight className="ml-1 size-3.5" />
                  </Link>
                </Button>
              ) : (
                <Badge variant="secondary" className="rounded-full px-2.5 py-0.5">
                  {cta}
                </Badge>
              )}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

function PrimaryBatchEntry({
  item,
  title,
  desc,
  journeyNote,
  liveBlocked,
  liveBlockedReason,
  onOpenLive,
  onOpenPreview,
}: {
  item: ModeCard;
  title: string;
  desc: string;
  journeyNote: string;
  liveBlocked: boolean;
  liveBlockedReason?: string;
  onOpenLive: () => void;
  onOpenPreview: () => void;
}) {
  const t = useT();
  const Icon = item.icon;
  const blockedReasonId = `${item.testId}-blocked-reason`;

  return (
    <Card className="page-surface !flex-none overflow-hidden border-border/70 shadow-[var(--shadow-md)]">
      <CardContent className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_17rem] lg:items-end">
        <div className="min-w-0 space-y-3">
          <div className="flex min-w-0 items-start gap-3">
            <span className="flex size-12 shrink-0 items-center justify-center rounded-2xl border border-foreground bg-foreground text-background">
              <Icon className="size-6" />
            </span>
            <div className="min-w-0 space-y-1.5">
              <div className="flex flex-wrap items-center gap-2">
                <CardTitle className="truncate text-lg font-semibold leading-6" title={title}>
                  {title}
                </CardTitle>
                <Badge
                  variant="secondary"
                  className="shrink-0 rounded-full px-2.5 py-0.5"
                >
                  {t('batchHub.liveBadge')}
                </Badge>
                {liveBlocked ? (
                  <Badge
                    variant="outline"
                    className="shrink-0 rounded-full px-2.5 py-0.5"
                  >
                    {t('batchHub.demoBadge')}
                  </Badge>
                ) : null}
              </div>
              <CardDescription className="text-xs leading-5" title={t(item.summaryKey)}>
                {t(item.summaryKey)}
              </CardDescription>
            </div>
          </div>

          <p className="max-w-3xl text-sm leading-6 text-muted-foreground" title={desc}>
            {desc}
          </p>

          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary" className="rounded-full px-2.5 py-0.5">
              {journeyNote}
            </Badge>
            {item.tagKeys.map((tagKey) => (
              <Badge
                key={tagKey}
                variant="outline"
                className="rounded-full px-2.5 py-0.5 whitespace-nowrap"
              >
                {t(tagKey)}
              </Badge>
            ))}
          </div>
        </div>

        <div className="min-w-0 space-y-2">
          {liveBlockedReason ? (
            <p
              id={blockedReasonId}
              className="text-xs leading-5 text-muted-foreground"
              data-testid={blockedReasonId}
            >
              {liveBlockedReason}
            </p>
          ) : null}
          <Button
            variant="default"
            className="w-full justify-between rounded-xl whitespace-nowrap"
            onClick={onOpenLive}
            disabled={liveBlocked}
            aria-describedby={liveBlockedReason ? blockedReasonId : undefined}
            title={liveBlocked ? liveBlockedReason : undefined}
            data-testid={item.testId}
          >
            <span className="truncate">{title}</span>
            <ArrowRight className="size-4" />
          </Button>
          {liveBlocked ? (
            <Button
              size="sm"
              variant="ghost"
              className="h-9 w-full justify-between rounded-xl whitespace-nowrap"
              onClick={onOpenPreview}
              data-testid={`${item.testId}-preview`}
            >
              {t('batchHub.demoCta')}
              <ArrowRight className="size-4" />
            </Button>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

