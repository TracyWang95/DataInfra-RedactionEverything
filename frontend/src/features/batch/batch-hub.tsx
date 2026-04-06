
import { Link } from 'react-router-dom';
import { useT } from '@/i18n';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { BatchHubJobList } from './components/batch-hub-job-list';
import { useBatchHub } from './hooks/use-batch-hub';

export function BatchHub() {
  const t = useT();
  const {
    loading,
    jobsUnavailable,
    activeJobs,
    openBatch,
    continueJob,
    openPreview,
  } = useBatchHub();

  return (
    <div className="saas-page flex h-full min-h-0 overflow-y-auto bg-background">
      <div className="page-shell-narrow !max-w-[104rem] 2xl:!max-w-[114rem]">
        <div className="page-stack gap-3.5 sm:gap-4">
          <section className="saas-hero relative overflow-hidden px-5 py-5 sm:px-6 sm:py-5.5">
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

          <section>
            <Card className="overflow-hidden border-border/70 shadow-[var(--shadow-md)]">
              <CardHeader className="gap-3 border-b border-border/70 bg-muted/20 px-6 py-4.5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="space-y-1.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <CardTitle className="text-xl font-semibold tracking-[-0.03em]">
                        {t('batchHub.mode.smart.title')}
                      </CardTitle>
                      <Badge variant="secondary" className="rounded-full px-2.5 py-0.5 text-[10px] font-medium">
                        {jobsUnavailable ? t('batchHub.previewBadge') : t('batchHub.liveBadge')}
                      </Badge>
                    </div>
                    <CardDescription className="max-w-3xl text-sm leading-7">
                      {t('batchHub.mode.smart.desc')}
                    </CardDescription>
                  </div>

                  <Button
                    size="sm"
                    className="h-10 rounded-xl px-4"
                    onClick={() => (jobsUnavailable ? openPreview() : openBatch())}
                    data-testid="batch-launch-smart"
                  >
                    {jobsUnavailable ? t('batchHub.previewCta') : t('batchHub.enterConfig')}
                  </Button>
                </div>
              </CardHeader>

              <CardContent className="grid gap-3.5 p-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(17rem,0.95fr)]">
                <div className="flex flex-col gap-4">
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="outline" className="rounded-full px-3 py-1 text-xs">
                      {t('batchHub.mode.text.title')}
                    </Badge>
                    <Badge variant="outline" className="rounded-full px-3 py-1 text-xs">
                      {t('batchHub.mode.image.title')}
                    </Badge>
                    <Badge variant="outline" className="rounded-full px-3 py-1 text-xs">
                      {t('batchHub.mode.smart.tag1')}
                    </Badge>
                  </div>

                  <div className="grid gap-3 md:grid-cols-2">
                    <div className="surface-muted flex flex-col gap-2 px-4 py-4">
                      <div className="flex items-center gap-2">
                        <span className="size-2 rounded-full bg-[var(--selection-regex-accent)]" />
                        <span className="text-sm font-semibold text-foreground">{t('batchHub.mode.text.title')}</span>
                      </div>
                      <p className="text-sm leading-6 text-muted-foreground">
                        {t('batchHub.mode.text.summaryValue')}
                      </p>
                    </div>

                    <div className="surface-muted flex flex-col gap-2 px-4 py-4">
                      <div className="flex items-center gap-2">
                        <span className="size-2 rounded-full bg-[var(--selection-visual-accent)]" />
                        <span className="text-sm font-semibold text-foreground">{t('batchHub.mode.image.title')}</span>
                      </div>
                      <p className="text-sm leading-6 text-muted-foreground">
                        {t('batchHub.mode.image.summaryValue')}
                      </p>
                    </div>
                  </div>
                </div>

                <div className="surface-muted flex flex-col gap-3 px-5 py-4">
                  <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                    {t('batchHub.mode.smart.summaryLabel')}
                  </span>
                  <p className="text-sm leading-7 text-foreground">
                    {t('batchHub.mode.smart.summaryValue')}
                  </p>
                  <p className="text-sm leading-6 text-muted-foreground">
                    {t('batchHub.modeSectionDesc')}
                  </p>
                </div>
              </CardContent>
            </Card>
          </section>

          <div className="page-fill">
            <BatchHubJobList
              jobs={activeJobs}
              loading={loading}
              onContinue={continueJob}
              footer={(
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  <Button variant="link" size="sm" className="h-auto px-0 text-xs" asChild>
                    <Link to="/jobs">{t('batchHub.jobCenter')}</Link>
                  </Button>
                  <span className="text-border">&middot;</span>
                  <Button variant="link" size="sm" className="h-auto px-0 text-xs" asChild>
                    <Link to="/history">{t('batchHub.history')}</Link>
                  </Button>
                </div>
              )}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
