
import { Link } from 'react-router-dom';
import { useT } from '@/i18n';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { BatchHubJobList } from './components/batch-hub-job-list';
import { BatchLaunchGrid, batchLaunchIcons } from './components/batch-launch-grid';
import { useBatchHub } from './hooks/use-batch-hub';

export function BatchHub() {
  const t = useT();
  const {
    loading,
    jobsUnavailable,
    activeJobs,
    openMode,
    continueJob,
    openPreview,
  } = useBatchHub();

  const launchCards = [
    {
      mode: 'text' as const,
      icon: batchLaunchIcons.text,
      dotClassName: 'bg-[var(--selection-regex-accent)]',
      title: t('batchHub.mode.text.title'),
      description: t('batchHub.mode.text.desc'),
      tags: [t('batchHub.mode.text.tag1'), t('batchHub.mode.text.tag2')] as [string, string],
      summaryLabel: t('batchHub.mode.text.summaryLabel'),
      summaryValue: t('batchHub.mode.text.summaryValue'),
    },
    {
      mode: 'image' as const,
      icon: batchLaunchIcons.image,
      dotClassName: 'bg-[var(--selection-visual-accent)]',
      title: t('batchHub.mode.image.title'),
      description: t('batchHub.mode.image.desc'),
      tags: [t('batchHub.mode.image.tag1'), t('batchHub.mode.image.tag2')] as [string, string],
      summaryLabel: t('batchHub.mode.image.summaryLabel'),
      summaryValue: t('batchHub.mode.image.summaryValue'),
    },
    {
      mode: 'smart' as const,
      icon: batchLaunchIcons.smart,
      dotClassName: 'bg-[var(--selection-semantic-accent)]',
      title: t('batchHub.mode.smart.title'),
      description: t('batchHub.mode.smart.desc'),
      tags: [t('batchHub.mode.smart.tag1'), t('batchHub.mode.smart.tag2')] as [string, string],
      summaryLabel: t('batchHub.mode.smart.summaryLabel'),
      summaryValue: t('batchHub.mode.smart.summaryValue'),
    },
  ];

  return (
    <div className="saas-page flex h-full min-h-0 overflow-y-auto bg-background">
      <div className="page-shell-narrow !max-w-[72rem]">
        <div className="page-stack gap-5 sm:gap-6">
          <section className="saas-hero relative overflow-hidden px-6 py-7 sm:px-8">
            <div className="flex flex-col gap-4">
              <span className="saas-kicker">{t('batchHub.kicker')}</span>
              <div className="page-section-heading gap-2">
                <h2 className="text-2xl font-semibold tracking-[-0.04em]" data-testid="batch-hub-title">
                  {t('batchHub.title')}
                </h2>
                <p className="max-w-2xl text-sm leading-7 text-muted-foreground">
                  {t('batchHub.desc')}
                </p>
              </div>
            </div>
          </section>

          {jobsUnavailable && (
            <Alert data-testid="batch-hub-preview-alert">
              <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
                <span>{t('batchHub.previewDesc')}</span>
                <Button variant="outline" size="sm" onClick={() => openPreview()}>
                  {t('batchHub.previewCta')}
                </Button>
              </AlertDescription>
            </Alert>
          )}

          <section className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
              <h3 className="text-sm font-semibold tracking-[-0.02em] text-foreground">
                {t('batchHub.modeSectionTitle')}
              </h3>
              <p className="text-sm text-muted-foreground">
                {t('batchHub.modeSectionDesc')}
              </p>
            </div>
            <BatchLaunchGrid
              jobsUnavailable={jobsUnavailable}
              liveLabel={t('batchHub.liveBadge')}
              previewLabel={t('batchHub.previewBadge')}
              actionLabel={jobsUnavailable ? t('batchHub.previewCta') : t('batchHub.enterConfig')}
              onOpenMode={openMode}
              cards={launchCards}
            />
          </section>

          <BatchHubJobList
            jobs={activeJobs}
            loading={loading}
            onContinue={continueJob}
          />

          <div className="flex items-center gap-3 pt-2 text-xs text-muted-foreground">
            <Button variant="link" size="sm" className="h-auto px-0 text-xs" asChild>
              <Link to="/jobs">{t('batchHub.jobCenter')}</Link>
            </Button>
            <span className="text-border">&middot;</span>
            <Button variant="link" size="sm" className="h-auto px-0 text-xs" asChild>
              <Link to="/history">{t('batchHub.history')}</Link>
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
