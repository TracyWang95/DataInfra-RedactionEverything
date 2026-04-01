import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { t } from '../i18n';
import {
  cancelJob,
  deleteJob,
  getJob,
  requeueFailed,
  submitJob,
  type JobDetail,
} from '../services/jobsApi';
import { resolveJobPrimaryNavigation } from '../utils/jobPrimaryNavigation';

import { resolveRedactionState, REDACTION_STATE_LABEL, REDACTION_STATE_CLASS } from '../utils/redactionState';

function pathLabel(_jobType: string): string {
  return t('jobDetail.batchTask');
}

function canDeleteJob(status: string): boolean {
  return ['draft', 'awaiting_review', 'completed', 'failed', 'cancelled'].includes(status);
}

export const JobDetailPage: React.FC = () => {
  const { jobId = '' } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<JobDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const isFetchingRef = useRef(false);

  const load = useCallback(async () => {
    if (!jobId) return;
    if (isFetchingRef.current) return;
    isFetchingRef.current = true;
    setLoading(true);
    setErr(null);
    try {
      const d = await getJob(jobId);
      setData(d);
    } catch (e) {
      setErr(e instanceof Error ? e.message : t('jobDetail.loadFailed'));
      setData(null);
    } finally {
      setLoading(false);
      isFetchingRef.current = false;
    }
  }, [jobId]);

  useEffect(() => {
    load();
  }, [load]);

  // Polling for progress updates (SSE removed — EventSource cannot carry Bearer tokens)
  useEffect(() => {
    const terminalStatuses = ['completed', 'failed', 'cancelled'];
    if (data && terminalStatuses.includes(data.status)) return;

    const tick = () => {
      if (document.visibilityState === 'visible') {
        load().catch((e) => { if (import.meta.env.DEV) console.error('Load failed:', e); });
      }
    };
    const interval = data?.status === 'redacting' || data?.status === 'processing' ? 5000 : 2000;
    const t = window.setInterval(tick, interval);
    document.addEventListener('visibilitychange', tick);
    return () => {
      window.clearInterval(t);
      document.removeEventListener('visibilitychange', tick);
    };
  }, [load, data?.status]);

  const onSubmit = async () => {
    if (!jobId) return;
    setActionMsg(null);
    try {
      await submitJob(jobId);
      setActionMsg(t('jobDetail.submitted'));
      await load();
    } catch (e) {
      setActionMsg(e instanceof Error ? e.message : t('jobDetail.submitFailed'));
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
      setActionMsg(e instanceof Error ? e.message : t('jobDetail.cancelFailed'));
    }
  };

  const onDelete = async () => {
    if (!jobId || !data || deleting || !canDeleteJob(data.status)) return;
    const title = data.title?.trim() || t('jobDetail.unnamedTask');
    const confirmed = window.confirm(
      t('jobDetail.confirmDelete').replace('{title}', title)
    );
    if (!confirmed) return;

    setDeleting(true);
    setActionMsg(null);
    try {
      await deleteJob(jobId);
      navigate('/jobs', { replace: true });
    } catch (e) {
      setActionMsg(e instanceof Error ? e.message : t('jobDetail.deleteFailed'));
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
      setActionMsg(e instanceof Error ? e.message : t('jobDetail.requeueFailed'));
    }
  };

  const detailItems = useMemo(() => data?.items ?? [], [data]);

  if (!jobId) return <p className="p-4 text-sm text-gray-500 dark:text-gray-400">{t('jobDetail.invalidJob')}</p>;
  if (loading && !data) return <p className="p-4 text-sm text-gray-500 dark:text-gray-400">{t('jobDetail.loading')}</p>;
  if (err || !data) {
    return (
      <div className="p-4 space-y-2">
        <p className="text-sm text-red-700 dark:text-red-400">{err ?? t('jobDetail.notFound')}</p>
        <Link to="/jobs" className="text-sm text-[#007AFF]">
          {t('jobDetail.backToList')}
        </Link>
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
    <div className="h-full min-h-0 flex flex-col bg-[#fafafa] dark:bg-gray-900 px-3 py-3 sm:px-5 sm:py-4 overflow-y-auto">
      <div className="max-w-5xl mx-auto w-full space-y-3">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Link to="/jobs" className="text-[#007AFF] hover:underline">
            {t('jobDetail.jobCenter')}
          </Link>
          <span className="text-gray-300 dark:text-gray-600">/</span>
          <span className="text-[#1d1d1f] dark:text-gray-100 font-medium truncate">{j.title || t('jobDetail.unnamedTask')}</span>
        </div>

        {actionMsg && (
          <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm px-3 py-2 text-gray-800 dark:text-gray-200">{actionMsg}</div>
        )}

        <div className="rounded-xl border border-black/[0.06] dark:border-gray-700 bg-white dark:bg-gray-800 shadow-sm dark:shadow-gray-900/30 p-3 sm:p-4 space-y-2">
          <div className="flex flex-wrap gap-2 text-2xs sm:text-xs text-gray-600 dark:text-gray-400">
            <span>{t('jobDetail.type')}{pathLabel(j.job_type)}</span>
            <span>{t('jobDetail.progressTotal').replace('{n}', String(j.progress.total_items))}</span>
            <span className="text-emerald-700">{t('jobDetail.progressRedacted').replace('{n}', String(detailItems.filter(it => resolveRedactionState(Boolean(it.has_output), it.status) === 'redacted').length))}</span>
            <span className="text-amber-700">{t('jobDetail.progressAwaiting').replace('{n}', String(detailItems.filter(it => resolveRedactionState(Boolean(it.has_output), it.status) === 'awaiting_review').length))}</span>
            {j.progress.failed > 0 && <span className="text-red-600">{t('jobDetail.progressFailed').replace('{n}', String(j.progress.failed))}</span>}
          </div>
          <div className="flex flex-wrap gap-2">
            {j.status === 'draft' && (
              <button
                type="button"
                onClick={onSubmit}
                className="text-xs sm:text-sm font-medium rounded-lg bg-[#1d1d1f] text-white px-3 py-1.5 hover:opacity-90"
              >
                {t('jobDetail.submitQueue')}
              </button>
            )}
            {!['completed', 'cancelled', 'failed'].includes(j.status) && (
              <button
                type="button"
                onClick={onCancel}
                className="text-xs sm:text-sm font-medium rounded-lg border border-gray-300 dark:border-gray-600 px-3 py-1.5 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700"
              >
                {t('jobDetail.cancelTask')}
              </button>
            )}
            {canDeleteJob(j.status) ? (
              <button
                type="button"
                disabled={deleting}
                onClick={onDelete}
                className="text-xs sm:text-sm font-medium rounded-lg border border-red-200 dark:border-red-800 px-3 py-1.5 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30 disabled:opacity-50"
              >
                {deleting ? t('jobDetail.deleting') : t('jobDetail.deleteTask')}
              </button>
            ) : (
              <span className="text-xs text-gray-400 dark:text-gray-500">{t('jobDetail.deleteHintRunning')}</span>
            )}
            {j.progress.failed > 0 && (
              <button
                type="button"
                onClick={onRequeueFailed}
                className="text-xs sm:text-sm font-medium rounded-lg border border-red-200 dark:border-red-800 px-3 py-1.5 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30"
              >
                {t('jobDetail.requeueFailed.btn').replace('{n}', String(j.progress.failed))}
              </button>
            )}
            {primaryNav.kind === 'link' && (
              <Link
                to={primaryNav.to}
                className="text-xs sm:text-sm font-medium rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-[#1d1d1f] dark:text-gray-100 px-3 py-1.5 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
              >
                {primaryNav.label}
              </Link>
            )}
            {primaryNav.kind === 'none' && primaryNav.reason && (
              <span className="text-xs text-gray-400 dark:text-gray-500">{primaryNav.reason}</span>
            )}
          </div>
        </div>

        <h3 className="text-sm font-semibold text-[#1d1d1f] dark:text-gray-100">{t('jobDetail.fileDetail')}</h3>
        <div className="rounded-xl border border-black/[0.06] dark:border-gray-700 bg-white dark:bg-gray-800 overflow-hidden">
          <table className="w-full text-left text-2xs sm:text-xs">
            <thead className="bg-gray-50 dark:bg-gray-900 text-gray-600 dark:text-gray-400 border-b border-gray-100 dark:border-gray-700">
              <tr>
                <th className="px-3 py-2 font-medium">{t('jobDetail.col.file')}</th>
                <th className="px-3 py-2 font-medium text-right">{t('jobDetail.col.status')}</th>
              </tr>
            </thead>
            <tbody>
              {detailItems.length === 0 ? (
                <tr>
                  <td colSpan={2} className="px-3 py-6 text-center text-gray-500 dark:text-gray-400">
                    {t('jobDetail.noFiles')}
                  </td>
                </tr>
              ) : (
                detailItems.map(it => {
                  const rs = resolveRedactionState(Boolean(it.has_output), it.status);
                  return (
                  <tr key={it.id} className="border-t border-gray-100 dark:border-gray-700">
                    <td className="px-3 py-2">
                      <div className="font-medium text-gray-900 dark:text-gray-100 truncate" title={it.filename || it.file_id}>
                        {it.filename || it.file_id}
                      </div>
                      <div className="text-2xs text-gray-500 dark:text-gray-400 mt-0.5">
                        {it.file_type ? String(it.file_type) : 'unknown'} · {it.entity_count ?? 0} {t('jobDetail.items')}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${REDACTION_STATE_CLASS[rs]}`}>
                        {REDACTION_STATE_LABEL[rs]}
                      </span>
                      {it.error_message && !it.error_message.startsWith('auto-repaired') && (
                        <div className="text-red-600 mt-0.5 max-w-xs truncate" title={it.error_message}>
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
      </div>
    </div>
  );
};
