// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useT } from '@/i18n';
import { JOB_DETAIL_POLL_ACTIVE_MS, JOB_DETAIL_POLL_IDLE_MS } from '@/constants/timing';
import {
  cancelJob,
  deleteJob,
  getJob,
  requeueFailed,
  submitJob,
  type JobDetail,
} from '@/services/jobsApi';
import {
  buildJobPrimaryNavigationLabels,
  resolveJobPrimaryNavigation,
} from '@/utils/jobPrimaryNavigation';
import { localizeErrorMessage } from '@/utils/localizeError';
import { resolveRedactionState } from '@/utils/redactionState';
import {
  buildJobRecoveryPlan,
  type JobRecoveryAction,
  type JobRecoveryPlan,
} from './lib/job-recovery';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { InteractionLockOverlay } from '@/components/InteractionLockOverlay';
import { JobStatusBadge, RedactionStateBadge } from './components/jobs-status-badge';

type ActionMessage = {
  text: string;
  tone: 'ok' | 'err';
};

function canDeleteJob(status: string): boolean {
  return ['draft', 'awaiting_review', 'completed', 'failed', 'cancelled'].includes(status);
}

function jobDetailSignature(job: JobDetail): string {
  const progress = job.progress;
  const nav = job.nav_hints;
  const itemSignature = job.items
    .map((item) =>
      [
        item.id,
        item.file_id,
        item.status,
        item.filename ?? '',
        item.file_type ?? '',
        item.has_output === true ? '1' : '0',
        item.entity_count ?? 0,
        item.error_message ?? '',
        item.updated_at,
      ].join('\x1e'),
    )
    .join('\x1f');
  return [
    job.id,
    job.status,
    job.title ?? '',
    job.updated_at,
    progress.total_items,
    progress.pending,
    progress.processing,
    progress.queued,
    progress.parsing,
    progress.ner,
    progress.vision,
    progress.awaiting_review,
    progress.review_approved,
    progress.redacting,
    progress.completed,
    progress.failed,
    progress.cancelled ?? 0,
    nav?.item_count ?? '',
    nav?.first_awaiting_review_item_id ?? '',
    nav?.wizard_furthest_step ?? '',
    nav?.redacted_count ?? '',
    nav?.awaiting_review_count ?? '',
    itemSignature,
  ].join('\x1d');
}

export function JobDetailPage() {
  const t = useT();
  const { jobId = '' } = useParams<{ jobId: string }>();
  const navigate = useNavigate();

  const [data, setData] = useState<JobDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionMsg, setActionMsg] = useState<ActionMessage | null>(null);
  const [submitLoading, setSubmitLoading] = useState(false);
  const [cancelLoading, setCancelLoading] = useState(false);
  const [requeueLoading, setRequeueLoading] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const isFetchingRef = useRef(false);
  const detailRequestSeqRef = useRef(0);
  const dataRef = useRef<JobDetail | null>(null);
  const actionBusy = submitLoading || cancelLoading || requeueLoading || deleting;
  const lockLabel = deleting
    ? t('jobDetail.deleting')
    : requeueLoading
      ? t('jobDetail.requeueing')
      : cancelLoading
        ? t('jobDetail.cancelling')
        : submitLoading
          ? t('jobDetail.submitting')
          : t('job.status.processing');

  const load = useCallback(async (opts?: { force?: boolean }) => {
    if (!jobId) return;
    if (isFetchingRef.current && !opts?.force) return;
    const requestSeq = ++detailRequestSeqRef.current;
    const hasData = dataRef.current !== null;
    isFetchingRef.current = true;
    if (!hasData) {
      setLoading(true);
      setErr(null);
    }
    try {
      const next = await getJob(jobId);
      if (requestSeq !== detailRequestSeqRef.current) return;
      setErr(null);
      setData((prev) => {
        if (prev && jobDetailSignature(prev) === jobDetailSignature(next)) {
          dataRef.current = prev;
          return prev;
        }
        dataRef.current = next;
        return next;
      });
    } catch (e) {
      if (requestSeq !== detailRequestSeqRef.current) return;
      if (!hasData) {
        setErr(localizeErrorMessage(e, 'jobDetail.loadFailed'));
        dataRef.current = null;
        setData(null);
      } else if (import.meta.env.DEV) {
        console.error('Background job detail refresh failed:', e);
      }
    } finally {
      if (requestSeq === detailRequestSeqRef.current) {
        setLoading(false);
        isFetchingRef.current = false;
      }
    }
  }, [jobId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (err || !data) return;
    const terminal = ['completed', 'failed', 'cancelled'];
    if (terminal.includes(data.status)) return;

    const tick = () => {
      if (document.visibilityState === 'visible') {
        load().catch((e) => {
          if (import.meta.env.DEV) console.error('Load failed:', e);
        });
      }
    };
    const interval =
      data?.status === 'redacting' || data?.status === 'processing'
        ? JOB_DETAIL_POLL_ACTIVE_MS
        : JOB_DETAIL_POLL_IDLE_MS;
    const timer = window.setInterval(tick, interval);
    document.addEventListener('visibilitychange', tick);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', tick);
    };
  }, [data, err, load]);

  const onSubmit = async () => {
    if (!jobId || actionBusy) return;
    setSubmitLoading(true);
    setActionMsg(null);
    try {
      await submitJob(jobId);
      setActionMsg({ text: t('jobDetail.submitted'), tone: 'ok' });
      await load({ force: true });
    } catch (e) {
      setActionMsg({ text: localizeErrorMessage(e, 'jobDetail.submitFailed'), tone: 'err' });
    } finally {
      setSubmitLoading(false);
    }
  };

  const onCancel = async () => {
    if (!jobId || actionBusy) return;
    setCancelLoading(true);
    setActionMsg(null);
    try {
      await cancelJob(jobId);
      setActionMsg({ text: t('jobDetail.cancelled'), tone: 'ok' });
      await load({ force: true });
    } catch (e) {
      setActionMsg({ text: localizeErrorMessage(e, 'jobDetail.cancelFailed'), tone: 'err' });
    } finally {
      setCancelLoading(false);
    }
  };

  const onDeleteConfirm = async () => {
    if (!jobId || !data || actionBusy || !canDeleteJob(data.status)) return;
    setDeleting(true);
    setActionMsg(null);
    setDeleteConfirmOpen(false);
    try {
      await deleteJob(jobId);
      navigate('/jobs', { replace: true });
    } catch (e) {
      setActionMsg({ text: localizeErrorMessage(e, 'jobDetail.deleteFailed'), tone: 'err' });
    } finally {
      setDeleting(false);
    }
  };

  const onRequeueFailed = async () => {
    if (!jobId || actionBusy) return;
    setRequeueLoading(true);
    setActionMsg(null);
    try {
      await requeueFailed(jobId);
      setActionMsg({ text: t('jobDetail.requeuedSuccess'), tone: 'ok' });
      await load({ force: true });
    } catch (e) {
      setActionMsg({ text: localizeErrorMessage(e, 'jobDetail.requeueFailed'), tone: 'err' });
    } finally {
      setRequeueLoading(false);
    }
  };

  const items = useMemo(() => data?.items ?? [], [data]);

  const redactedCount = useMemo(
    () =>
      items.filter((it) => resolveRedactionState(Boolean(it.has_output), it.status) === 'redacted')
        .length,
    [items],
  );
  const awaitingCount = useMemo(
    () =>
      items.filter(
        (it) => resolveRedactionState(Boolean(it.has_output), it.status) === 'awaiting_review',
      ).length,
    [items],
  );

  if (!jobId) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="text-sm text-muted-foreground">{t('jobDetail.invalidJob')}</p>
      </div>
    );
  }

  if (loading && !data) {
    return (
      <div className="flex-1 flex flex-col gap-4 px-3 py-4 sm:px-5 max-w-5xl mx-auto w-full">
        <Skeleton className="h-5 w-48" />
        <Skeleton className="h-32 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    );
  }

  if (err || !data) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3 px-4">
        <p className="text-sm text-[var(--error-foreground)]">{err ?? t('jobDetail.notFound')}</p>
        <Button variant="outline" size="sm" asChild>
          <Link to="/jobs">{t('jobDetail.backToList')}</Link>
        </Button>
      </div>
    );
  }

  const j = data;
  const navLabels = buildJobPrimaryNavigationLabels(t);
  const primaryNav = resolveJobPrimaryNavigation({
    jobId,
    status: j.status,
    jobType: j.job_type,
    items: j.items,
    currentPage: 'job_detail',
    navHints: j.nav_hints,
    jobConfig: j.config,
    labels: navLabels,
  });
  const recoveryPlan = buildJobRecoveryPlan(j);

  return (
    <div
      className="flex-1 min-h-0 flex flex-col bg-background overflow-y-auto"
      data-testid="job-detail-page"
    >
      <div className="px-3 py-3 sm:px-5 sm:py-4 max-w-5xl mx-auto w-full space-y-4">
        <nav className="flex min-w-0 items-center gap-2 text-sm whitespace-nowrap">
          <Link to="/jobs" className="shrink-0 text-primary hover:underline">
            {t('jobDetail.jobCenter')}
          </Link>
          <span className="shrink-0 text-muted-foreground">/</span>
          <span className="font-medium truncate">{j.title || t('jobDetail.unnamedTask')}</span>
        </nav>

        {actionMsg && (
          <Alert
            variant={actionMsg.tone === 'err' ? 'destructive' : 'default'}
            data-testid="job-detail-action-alert"
          >
            <AlertDescription>{actionMsg.text}</AlertDescription>
          </Alert>
        )}

        <Card>
          <CardHeader className="pb-3">
            <div className="flex min-w-0 flex-nowrap items-center gap-3">
              <h2 className="text-lg font-semibold truncate">
                {j.title || t('jobDetail.unnamedTask')}
              </h2>
              <JobStatusBadge status={j.status} />
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex min-w-0 flex-nowrap gap-x-4 gap-y-1 overflow-hidden text-xs text-muted-foreground">
              <span className="shrink-0 whitespace-nowrap">
                {t('jobDetail.type')}
                {t('jobDetail.batchTask')}
              </span>
              <span className="shrink-0 whitespace-nowrap">
                {t('jobDetail.progressTotal').replace('{n}', String(j.progress.total_items))}
              </span>
              <span className="shrink-0 whitespace-nowrap text-[var(--success-foreground)]">
                {t('jobDetail.progressRedacted').replace('{n}', String(redactedCount))}
              </span>
              <span className="shrink-0 whitespace-nowrap text-[var(--warning-foreground)]">
                {t('jobDetail.progressAwaiting').replace('{n}', String(awaitingCount))}
              </span>
              {j.progress.failed > 0 && (
                <span className="shrink-0 whitespace-nowrap text-[var(--error-foreground)]">
                  {t('jobDetail.progressFailed').replace('{n}', String(j.progress.failed))}
                </span>
              )}
            </div>

            <div className="flex min-w-0 flex-nowrap gap-2 overflow-hidden">
              {j.status === 'draft' && (
                <Button
                  size="sm"
                  onClick={onSubmit}
                  disabled={actionBusy}
                  className="shrink-0 whitespace-nowrap"
                >
                  {submitLoading ? t('jobDetail.submitting') : t('jobDetail.submitQueue')}
                </Button>
              )}
              {!['completed', 'cancelled', 'failed'].includes(j.status) && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={onCancel}
                  disabled={actionBusy}
                  className="shrink-0 whitespace-nowrap"
                >
                  {cancelLoading ? t('jobDetail.cancelling') : t('jobDetail.cancelTask')}
                </Button>
              )}
              {canDeleteJob(j.status) ? (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={actionBusy}
                  className="shrink-0 whitespace-nowrap text-destructive border-destructive/25 hover:bg-destructive/10"
                  onClick={() => setDeleteConfirmOpen(true)}
                >
                  {deleting ? t('jobDetail.deleting') : t('jobDetail.deleteTask')}
                </Button>
              ) : (
                <span className="self-center truncate text-xs text-muted-foreground">
                  {t('jobDetail.deleteHintRunning')}
                </span>
              )}
              {j.progress.failed > 0 && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={actionBusy}
                  className="shrink-0 whitespace-nowrap text-destructive border-destructive/25 hover:bg-destructive/10"
                  onClick={onRequeueFailed}
                >
                  {requeueLoading
                    ? t('jobDetail.requeueing')
                    : t('jobDetail.requeueFailed.btn').replace('{n}', String(j.progress.failed))}
                </Button>
              )}
              {primaryNav.kind === 'link' && (
                <Button variant="outline" size="sm" className="shrink-0 whitespace-nowrap" asChild>
                  <Link to={primaryNav.to}>{primaryNav.label}</Link>
                </Button>
              )}
              {primaryNav.kind === 'none' && primaryNav.reason && (
                <span className="self-center truncate text-xs text-muted-foreground">
                  {primaryNav.reason}
                </span>
              )}
            </div>
          </CardContent>
        </Card>

        {recoveryPlan.failedItems.length > 0 && (
          <JobRecoveryPanel
            plan={recoveryPlan}
            actionBusy={actionBusy}
            requeueLoading={requeueLoading}
            onRequeueFailed={onRequeueFailed}
          />
        )}

        <Card>
          <CardHeader className="pb-2">
            <h3 className="text-sm font-semibold">{t('jobDetail.fileDetail')}</h3>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full table-fixed text-left text-xs">
                <colgroup>
                  <col />
                  <col className="w-64" />
                </colgroup>
                <thead className="bg-muted/40 text-muted-foreground border-b">
                  <tr>
                    <th className="px-4 py-2.5 font-medium whitespace-nowrap">
                      {t('jobDetail.col.file')}
                    </th>
                    <th className="px-4 py-2.5 font-medium text-right whitespace-nowrap">
                      {t('jobDetail.col.status')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {items.length === 0 ? (
                    <tr>
                      <td colSpan={2} className="px-4 py-8 text-center text-muted-foreground">
                        {t('jobDetail.noFiles')}
                      </td>
                    </tr>
                  ) : (
                    items.map((it) => {
                      const rs = resolveRedactionState(Boolean(it.has_output), it.status);
                      return (
                        <tr key={it.id} className="border-b last:border-b-0">
                          <td className="min-w-0 px-4 py-2.5">
                            <div
                              className="flex min-w-0 items-center gap-2"
                              title={it.filename || it.file_id}
                            >
                              <span className="truncate font-medium">
                                {it.filename || it.file_id}
                              </span>
                              <span className="shrink-0 whitespace-nowrap text-2xs text-muted-foreground">
                                {it.file_type ? String(it.file_type).toUpperCase() : '-'} {'\u00b7'}{' '}
                                {it.entity_count ?? 0} {t('jobDetail.items')}
                              </span>
                            </div>
                          </td>
                          <td className="px-4 py-2.5 text-right">
                            <RedactionStateBadge state={rs} />
                            {it.error_message && !it.error_message.startsWith('auto-repaired') && (
                              <span
                                className="ml-2 inline-block max-w-36 truncate align-middle text-[var(--error-foreground)] text-2xs"
                                title={it.error_message}
                              >
                                {it.error_message}
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      </div>

      <ConfirmDialog
        open={deleteConfirmOpen}
        title={t('jobDetail.deleteTask')}
        message={t('jobDetail.confirmDelete').replace(
          '{title}',
          j.title?.trim() || t('jobDetail.unnamedTask'),
        )}
        danger
        onConfirm={onDeleteConfirm}
        onCancel={() => setDeleteConfirmOpen(false)}
      />
      <InteractionLockOverlay active={actionBusy} label={lockLabel} />
    </div>
  );
}

function JobRecoveryPanel({
  plan,
  actionBusy,
  requeueLoading,
  onRequeueFailed,
}: {
  plan: JobRecoveryPlan;
  actionBusy: boolean;
  requeueLoading: boolean;
  onRequeueFailed: () => void;
}) {
  const t = useT();

  return (
    <Card data-testid="job-recovery-panel">
      <CardHeader className="pb-2">
        <div className="flex min-w-0 flex-nowrap items-center justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <h3 className="text-sm font-semibold">{t('jobDetail.recovery.title')}</h3>
            <p className="truncate text-xs leading-5 text-muted-foreground">
              {t('jobDetail.recovery.desc').replace('{n}', String(plan.failedItems.length))}
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            disabled={actionBusy}
            className="shrink-0 whitespace-nowrap text-destructive border-destructive/25 hover:bg-destructive/10"
            onClick={onRequeueFailed}
            data-testid="job-recovery-requeue"
          >
            {requeueLoading
              ? t('jobDetail.requeueing')
              : t('jobDetail.requeueFailed.btn').replace('{n}', String(plan.failedItems.length))}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {plan.partialReviewAction && (
          <div
            className="flex min-w-0 flex-nowrap items-center justify-between gap-3 rounded-xl border border-[var(--warning-border)] bg-[var(--warning-surface)] px-3 py-2"
            data-testid="job-recovery-partial-review"
          >
            <p className="truncate text-xs leading-5 text-[var(--warning-foreground)]">
              {t('jobDetail.recovery.partialReview').replace(
                '{n}',
                String(plan.partialReviewAction.count),
              )}
            </p>
            <Button
              variant="outline"
              size="sm"
              className="h-8 shrink-0 rounded-xl whitespace-nowrap"
              asChild
            >
              <Link to={plan.partialReviewAction.to}>{t('jobDetail.recovery.openReview')}</Link>
            </Button>
          </div>
        )}

        <div className="grid gap-2 md:grid-cols-2">
          {plan.actions.map((action) => (
            <RecoveryActionCard key={action.category} action={action} />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function RecoveryActionCard({ action }: { action: JobRecoveryAction }) {
  const t = useT();
  const visibleNames = action.filenames.join(', ');
  const moreCount = Math.max(0, action.count - action.filenames.length);

  return (
    <div
      className="rounded-xl border border-border/70 bg-muted/25 px-3 py-2"
      data-testid={`job-recovery-action-${action.category}`}
    >
      <div className="flex min-w-0 items-center justify-between gap-3">
        <div className="min-w-0">
          <h4 className="truncate text-xs font-semibold text-foreground">{t(action.titleKey)}</h4>
          <p className="truncate text-xs leading-5 text-muted-foreground">{t(action.descKey)}</p>
        </div>
        <span className="shrink-0 rounded-full border border-border bg-background px-2 py-0.5 text-caption text-muted-foreground">
          {action.count}
        </span>
      </div>
      {visibleNames && (
        <p className="mt-1 truncate text-caption text-muted-foreground" title={visibleNames}>
          {visibleNames}
          {moreCount > 0
            ? ` ${t('jobDetail.recovery.moreFiles').replace('{n}', String(moreCount))}`
            : ''}
        </p>
      )}
      <Button variant="outline" size="sm" className="mt-2 h-8 rounded-xl whitespace-nowrap" asChild>
        <Link to={action.to}>{t(action.ctaKey)}</Link>
      </Button>
    </div>
  );
}
