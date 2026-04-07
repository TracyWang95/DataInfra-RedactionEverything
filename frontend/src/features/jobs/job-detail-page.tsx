// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0


import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { t } from '@/i18n';
import {
  cancelJob,
  deleteJob,
  getJob,
  requeueFailed,
  submitJob,
  type JobDetail,
} from '@/services/jobsApi';
import { resolveJobPrimaryNavigation } from '@/utils/jobPrimaryNavigation';
import { localizeErrorMessage } from '@/utils/localizeError';
import { resolveRedactionState } from '@/utils/redactionState';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { JobStatusBadge, RedactionStateBadge } from './components/jobs-status-badge';

function canDeleteJob(status: string): boolean {
  return ['draft', 'awaiting_review', 'completed', 'failed', 'cancelled'].includes(status);
}

export function JobDetailPage() {
  const { jobId = '' } = useParams<{ jobId: string }>();
  const navigate = useNavigate();

  const [data, setData] = useState<JobDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const isFetchingRef = useRef(false);

  const load = useCallback(async () => {
    if (!jobId || isFetchingRef.current) return;
    isFetchingRef.current = true;
    setLoading(true);
    setErr(null);
    try {
      setData(await getJob(jobId));
    } catch (e) {
      setErr(localizeErrorMessage(e, 'jobDetail.loadFailed'));
      setData(null);
    } finally {
      setLoading(false);
      isFetchingRef.current = false;
    }
  }, [jobId]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (err || !data) return;
    const terminal = ['completed', 'failed', 'cancelled'];
    if (terminal.includes(data.status)) return;

    const tick = () => {
      if (document.visibilityState === 'visible') {
        load().catch((e) => { if (import.meta.env.DEV) console.error('Load failed:', e); });
      }
    };
    const interval = data?.status === 'redacting' || data?.status === 'processing' ? 5000 : 2000;
    const timer = window.setInterval(tick, interval);
    document.addEventListener('visibilitychange', tick);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', tick);
    };
  }, [data, err, load]);

  const onSubmit = async () => {
    if (!jobId) return;
    setActionMsg(null);
    try {
      await submitJob(jobId);
      setActionMsg(t('jobDetail.submitted'));
      await load();
    } catch (e) {
      setActionMsg(localizeErrorMessage(e, 'jobDetail.submitFailed'));
    }
  };

  const onCancel = async () => {
    if (!jobId) return;
    setActionMsg(null);
    try {
      await cancelJob(jobId);
      setActionMsg(t('jobDetail.cancelled'));
      await load();
    } catch (e) {
      setActionMsg(localizeErrorMessage(e, 'jobDetail.cancelFailed'));
    }
  };

  const onDeleteConfirm = async () => {
    if (!jobId || !data || deleting || !canDeleteJob(data.status)) return;
    setDeleting(true);
    setActionMsg(null);
    setDeleteConfirmOpen(false);
    try {
      await deleteJob(jobId);
      navigate('/jobs', { replace: true });
    } catch (e) {
      setActionMsg(localizeErrorMessage(e, 'jobDetail.deleteFailed'));
    } finally {
      setDeleting(false);
    }
  };

  const onRequeueFailed = async () => {
    if (!jobId) return;
    setActionMsg(null);
    try {
      await requeueFailed(jobId);
      setActionMsg(t('jobDetail.requeuedSuccess'));
      await load();
    } catch (e) {
      setActionMsg(localizeErrorMessage(e, 'jobDetail.requeueFailed'));
    }
  };

  const items = useMemo(() => data?.items ?? [], [data]);

  const redactedCount = useMemo(
    () => items.filter(it => resolveRedactionState(Boolean(it.has_output), it.status) === 'redacted').length,
    [items],
  );
  const awaitingCount = useMemo(
    () => items.filter(it => resolveRedactionState(Boolean(it.has_output), it.status) === 'awaiting_review').length,
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
        <p className="text-sm text-destructive">{err ?? t('jobDetail.notFound')}</p>
        <Button variant="outline" size="sm" asChild>
          <Link to="/jobs">{t('jobDetail.backToList')}</Link>
        </Button>
      </div>
    );
  }

  const j = data;
  const primaryNav = resolveJobPrimaryNavigation({
    jobId,
    status: j.status,
    jobType: j.job_type,
    items: j.items,
    currentPage: 'job_detail',
    navHints: j.nav_hints,
    jobConfig: j.config,
  });

  return (
    <div className="flex-1 min-h-0 flex flex-col bg-background overflow-y-auto" data-testid="job-detail-page">
      <div className="px-3 py-3 sm:px-5 sm:py-4 max-w-5xl mx-auto w-full space-y-4">

        <nav className="flex items-center gap-2 text-sm">
          <Link to="/jobs" className="text-primary hover:underline">
            {t('jobDetail.jobCenter')}
          </Link>
          <span className="text-muted-foreground">/</span>
          <span className="font-medium truncate">{j.title || t('jobDetail.unnamedTask')}</span>
        </nav>

        {actionMsg && (
          <Alert>
            <AlertDescription>{actionMsg}</AlertDescription>
          </Alert>
        )}

        <Card>
          <CardHeader className="pb-3">
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="text-lg font-semibold truncate">{j.title || t('jobDetail.unnamedTask')}</h2>
              <JobStatusBadge status={j.status} />
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span>{t('jobDetail.type')}{t('jobDetail.batchTask')}</span>
              <span>{t('jobDetail.progressTotal').replace('{n}', String(j.progress.total_items))}</span>
              <span className="text-[var(--success-foreground)]">{t('jobDetail.progressRedacted').replace('{n}', String(redactedCount))}</span>
              <span className="text-[var(--warning-foreground)]">{t('jobDetail.progressAwaiting').replace('{n}', String(awaitingCount))}</span>
              {j.progress.failed > 0 && (
                <span className="text-destructive">{t('jobDetail.progressFailed').replace('{n}', String(j.progress.failed))}</span>
              )}
            </div>

            <div className="flex flex-wrap gap-2">
              {j.status === 'draft' && (
                <Button size="sm" onClick={onSubmit}>
                  {t('jobDetail.submitQueue')}
                </Button>
              )}
              {!['completed', 'cancelled', 'failed'].includes(j.status) && (
                <Button variant="outline" size="sm" onClick={onCancel}>
                  {t('jobDetail.cancelTask')}
                </Button>
              )}
              {canDeleteJob(j.status) ? (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={deleting}
                  className="text-destructive border-destructive/30 hover:bg-destructive/10"
                  onClick={() => setDeleteConfirmOpen(true)}
                >
                  {deleting ? t('jobDetail.deleting') : t('jobDetail.deleteTask')}
                </Button>
              ) : (
                <span className="text-xs text-muted-foreground self-center">{t('jobDetail.deleteHintRunning')}</span>
              )}
              {j.progress.failed > 0 && (
                <Button
                  variant="outline"
                  size="sm"
                  className="text-destructive border-destructive/30 hover:bg-destructive/10"
                  onClick={onRequeueFailed}
                >
                  {t('jobDetail.requeueFailed.btn').replace('{n}', String(j.progress.failed))}
                </Button>
              )}
              {primaryNav.kind === 'link' && (
                <Button variant="outline" size="sm" asChild>
                  <Link to={primaryNav.to}>{primaryNav.label}</Link>
                </Button>
              )}
              {primaryNav.kind === 'none' && primaryNav.reason && (
                <span className="text-xs text-muted-foreground self-center">{primaryNav.reason}</span>
              )}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <h3 className="text-sm font-semibold">{t('jobDetail.fileDetail')}</h3>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-muted/40 text-muted-foreground border-b">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">{t('jobDetail.col.file')}</th>
                    <th className="px-4 py-2.5 font-medium text-right">{t('jobDetail.col.status')}</th>
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
                    items.map(it => {
                      const rs = resolveRedactionState(Boolean(it.has_output), it.status);
                      return (
                        <tr key={it.id} className="border-b last:border-b-0">
                          <td className="px-4 py-2.5">
                            <div className="font-medium truncate" title={it.filename || it.file_id}>
                              {it.filename || it.file_id}
                            </div>
                            <div className="text-2xs text-muted-foreground mt-0.5">
                              {it.file_type ? String(it.file_type).toUpperCase() : '-'} · {it.entity_count ?? 0} {t('jobDetail.items')}
                            </div>
                          </td>
                          <td className="px-4 py-2.5 text-right">
                            <RedactionStateBadge state={rs} />
                            {it.error_message && !it.error_message.startsWith('auto-repaired') && (
                              <div className="text-destructive text-2xs mt-0.5 max-w-xs truncate ml-auto" title={it.error_message}>
                                {it.error_message}
                              </div>
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
        message={t('jobDetail.confirmDelete').replace('{title}', j.title?.trim() || t('jobDetail.unnamedTask'))}
        danger
        onConfirm={onDeleteConfirm}
        onCancel={() => setDeleteConfirmOpen(false)}
      />
    </div>
  );
}
