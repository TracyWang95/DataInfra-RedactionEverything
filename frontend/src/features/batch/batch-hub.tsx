/**
 * BatchHub — entry page for batch processing.
 * Allows creating new batch jobs and resuming active ones.
 */
import { Link } from 'react-router-dom';
import { Plus, ArrowRight } from 'lucide-react';
import { t } from '@/i18n';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { useBatchHub } from './hooks/use-batch-hub';
import { BatchHubJobList } from './components/batch-hub-job-list';

export function BatchHub() {
  const { busy, error, loading, recentByType, startNewJob, continueJob } = useBatchHub();

  return (
    <div className="saas-page h-full min-h-0 overflow-y-auto bg-background px-4 py-6 sm:px-8">
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
        <section className="saas-hero relative overflow-hidden px-6 py-7 sm:px-8">
          <div className="space-y-4">
            <span className="saas-kicker">Batch Workspace</span>
            <div className="space-y-2">
              <h2 className="text-2xl font-semibold tracking-[-0.04em]" data-testid="batch-hub-title">
                {t('batchHub.title')}
              </h2>
              <p className="max-w-2xl text-sm leading-7 text-muted-foreground">
                {t('batchHub.desc')}
              </p>
            </div>
          </div>
        </section>

        {/* Error alert */}
        {error && (
          <Alert variant="destructive" data-testid="batch-hub-error">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {/* New task card — premium interactive surface */}
        <button
          type="button"
          className="saas-panel group relative w-full p-6 text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-foreground/15"
          onClick={() => void startNewJob('smart_batch')}
          data-testid="new-batch-btn"
          disabled={busy}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[18px] bg-foreground text-background">
                <Plus className="w-5 h-5" />
              </div>
              <div>
                <div className="text-sm font-semibold tracking-[-0.01em]">
                  {t('batchHub.newTask')}
                </div>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {t('batchHub.newTaskDesc')}
                </p>
              </div>
            </div>
            <ArrowRight className="w-4 h-4 text-muted-foreground opacity-0 -translate-x-2 transition-all group-hover:translate-x-0 group-hover:opacity-100" />
          </div>
        </button>

        {/* Recent active jobs */}
        <BatchHubJobList
          jobs={recentByType}
          loading={loading}
          onContinue={continueJob}
        />

        {/* Footer links */}
        <div className="flex items-center gap-3 text-xs text-muted-foreground pt-2">
          {busy && <span>{t('batchHub.creating')}</span>}
          <Button variant="link" size="sm" className="text-xs px-0 h-auto" asChild>
            <Link to="/jobs">{t('batchHub.jobCenter')}</Link>
          </Button>
          <span className="text-border">&middot;</span>
          <Button variant="link" size="sm" className="text-xs px-0 h-auto" asChild>
            <Link to="/history">{t('batchHub.history')}</Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
