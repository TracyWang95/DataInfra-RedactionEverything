import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  deleteJob,
  getJob,
  listJobs,
  type JobDetail,
  type JobItemRow,
  type JobProgress,
  type JobSummary,
  type JobTypeApi,
} from '../services/jobsApi';
import { buildBatchWorkbenchUrl, resolveJobPrimaryNavigation } from '../utils/jobPrimaryNavigation';
import {
  formatAggregateJobStatus,
  formatJobItemStatus,
  getAggregateJobStatusMeta,
  getJobItemStatusMeta,
  type JobStatusTone,
} from '../utils/jobStatusLabels';

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const;
const DELETABLE_STATUSES = new Set(['draft', 'awaiting_review', 'completed', 'failed', 'cancelled']);
const ACTIVE_STATUSES = new Set(['queued', 'running', 'redacting']);

function pathLabel(jobType: JobTypeApi): string {
  return jobType === 'image_batch' ? '图像批量' : '文本批量';
}

function executionLabel(config: Record<string, unknown>): string {
  return String(config.preferred_execution ?? 'queue') === 'local' ? '本页闭环' : '后台队列';
}

function canDeleteJob(status: string): boolean {
  return DELETABLE_STATUSES.has(status);
}

function outlineActionClass(tone: 'neutral' | 'info' | 'danger' = 'neutral'): string {
  if (tone === 'info') {
    return 'text-xs font-medium rounded-lg border border-[#007AFF]/20 bg-[#007AFF]/[0.06] text-[#0a4a8c] px-3 py-1.5 hover:bg-[#007AFF]/[0.10] transition-colors';
  }
  if (tone === 'danger') {
    return 'text-xs font-medium rounded-lg border border-red-200 bg-white text-red-600 px-3 py-1.5 hover:bg-red-50 disabled:opacity-50 transition-colors';
  }
  return 'text-xs font-medium rounded-lg border border-gray-200 bg-white text-[#1d1d1f] px-3 py-1.5 hover:bg-gray-50 transition-colors';
}

function passiveOutlineClass(): string {
  return 'text-xs font-medium rounded-lg border border-gray-200 bg-[#fafafa] text-gray-400 px-3 py-1.5';
}

function primaryActionClass(status: string): string {
  return status === 'awaiting_review' ? outlineActionClass('info') : outlineActionClass('neutral');
}

function toneClass(tone: JobStatusTone): string {
  if (tone === 'success') return 'bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200';
  if (tone === 'danger') return 'bg-red-50 text-red-600 ring-1 ring-inset ring-red-200';
  if (tone === 'warning') return 'bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-200';
  if (tone === 'review') return 'bg-sky-50 text-sky-700 ring-1 ring-inset ring-sky-200';
  if (tone === 'brand') return 'bg-indigo-50 text-indigo-700 ring-1 ring-inset ring-indigo-200';
  if (tone === 'muted') return 'bg-gray-100 text-gray-500 ring-1 ring-inset ring-gray-200';
  return 'bg-slate-100 text-slate-600 ring-1 ring-inset ring-slate-200';
}

function statusToneClass(status: string): string {
  return toneClass(getAggregateJobStatusMeta(status).tone);
}

function itemStatusToneClass(status: string): string {
  return toneClass(getJobItemStatusMeta(status).tone);
}

function typeToneClass(jobType: JobTypeApi): string {
  return jobType === 'text_batch' ? 'bg-sky-50 text-sky-700' : 'bg-indigo-50 text-indigo-700';
}

function formatUpdatedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '更新时间未知';
  return date.toLocaleString('zh-CN');
}

function jobsPollSignature(jobs: JobSummary[]): string {
  return jobs
    .map(job => {
      const ids = job.config?.entity_type_ids;
      const entityTypes =
        Array.isArray(ids) && ids.every((x): x is string => typeof x === 'string')
          ? [...ids].sort().join(',')
          : '';
      return [
        job.id,
        job.status,
        job.updated_at,
        job.title ?? '',
        job.progress.total_items,
        job.progress.awaiting_review,
        job.progress.completed,
        job.progress.failed,
        job.nav_hints?.item_count ?? '',
        job.nav_hints?.wizard_furthest_step ?? '',
        job.nav_hints?.batch_step1_configured === true ? '1' : '0',
        job.nav_hints?.first_awaiting_review_item_id ?? '',
        entityTypes,
      ].join('\x1e');
    })
    .join('\x1f');
}

function itemTreeGlyph(index: number, total: number): string {
  if (total <= 1) return '└';
  return index === total - 1 ? '└' : '├';
}

function buildProgressHeadline(progress: JobProgress): string {
  const parts = [`待复核 ${progress.awaiting_review}`, `完成 ${progress.completed}`];
  if (progress.failed > 0) parts.push(`异常 ${progress.failed}`);
  else if ((progress.cancelled ?? 0) > 0) parts.push(`取消 ${progress.cancelled}`);
  return parts.join(' · ');
}

function buildProgressSummary(progress: JobProgress, itemCount: number, finishedCount: number): string {
  if (itemCount <= 0) return '任务内暂无文件';
  if (finishedCount >= itemCount) return '全部文件已走完处理链路';

  const waiting = progress.pending + progress.queued;
  const processing = progress.parsing + progress.ner + progress.vision;
  const review = progress.awaiting_review;
  const generating = progress.review_approved + progress.redacting;
  const failed = progress.failed;
  const cancelled = progress.cancelled ?? 0;

  const parts = [
    waiting > 0 ? `待执行 ${waiting}` : null,
    processing > 0 ? `识别中 ${processing}` : null,
    review > 0 ? `待复核 ${review}` : null,
    generating > 0 ? `生成中 ${generating}` : null,
    failed > 0 ? `异常 ${failed}` : null,
    cancelled > 0 ? `已取消 ${cancelled}` : null,
  ].filter((part): part is string => Boolean(part));

  if (parts.length === 0) {
    return finishedCount > 0 ? `已完成 ${finishedCount} 项` : '等待系统开始处理';
  }

  return parts.slice(0, 3).join(' · ');
}

export const Jobs: React.FC = () => {
  const [tab, setTab] = useState<JobTypeApi | 'all'>('all');
  const [rows, setRows] = useState<JobSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [jumpPage, setJumpPage] = useState('');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [deletingJobId, setDeletingJobId] = useState<string | null>(null);
  const [expandedJobIds, setExpandedJobIds] = useState<Set<string>>(() => new Set());
  const [jobDetails, setJobDetails] = useState<Record<string, JobDetail>>({});
  const [detailLoadingIds, setDetailLoadingIds] = useState<Set<string>>(() => new Set());

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const load = useCallback(
    async (opts?: { targetPage?: number; targetPageSize?: number }) => {
      const targetPage = opts?.targetPage ?? page;
      const targetPageSize = opts?.targetPageSize ?? pageSize;
      const hasRows = rows.length > 0;
      if (hasRows) setRefreshing(true);
      else setLoading(true);
      setErr(null);

      try {
        const jobType = tab === 'all' ? undefined : tab;
        let result = await listJobs({ job_type: jobType, page: targetPage, page_size: targetPageSize });
        const resolvedTotalPages = Math.max(1, Math.ceil(result.total / result.page_size));
        if (targetPage > resolvedTotalPages && result.total > 0) {
          result = await listJobs({ job_type: jobType, page: resolvedTotalPages, page_size: targetPageSize });
        }
        setRows(prev => (jobsPollSignature(prev) === jobsPollSignature(result.jobs) ? prev : result.jobs));
        setTotal(prev => (prev === result.total ? prev : result.total));
        setPage(prev => (prev === result.page ? prev : result.page));
        setPageSize(prev => (prev === result.page_size ? prev : result.page_size));
        return result;
      } catch (e) {
        setErr(e instanceof Error ? e.message : '加载失败');
        if (!hasRows) setRows([]);
        return null;
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [page, pageSize, rows.length, tab]
  );

  const fetchJobDetails = useCallback(async (jobIds: string[]) => {
    const ids = [...new Set(jobIds)].filter(Boolean);
    if (ids.length === 0) return;
    setDetailLoadingIds(prev => {
      const next = new Set(prev);
      ids.forEach(id => next.add(id));
      return next;
    });
    const results = await Promise.allSettled(ids.map(async id => ({ id, detail: await getJob(id) })));
    const patch: Record<string, JobDetail> = {};
    let firstError: string | null = null;
    results.forEach(result => {
      if (result.status === 'fulfilled') patch[result.value.id] = result.value.detail;
      else if (!firstError) firstError = result.reason instanceof Error ? result.reason.message : '展开任务失败';
    });
    if (Object.keys(patch).length > 0) setJobDetails(prev => ({ ...prev, ...patch }));
    if (firstError) setErr(firstError);
    setDetailLoadingIds(prev => {
      const next = new Set(prev);
      ids.forEach(id => next.delete(id));
      return next;
    });
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const refreshList = useCallback(async () => {
    const result = await load({ targetPage: page });
    if (!result) return;
    const expandedVisibleIds = [...expandedJobIds].filter(id => result.jobs.some(job => job.id === id));
    if (expandedVisibleIds.length > 0) await fetchJobDetails(expandedVisibleIds);
  }, [expandedJobIds, fetchJobDetails, load, page]);

  const goPage = (next: number) => {
    const clamped = Math.min(Math.max(1, next), totalPages);
    if (clamped === page) return;
    setPage(clamped);
    setJumpPage('');
  };

  const changePageSize = (next: number) => {
    if (next === pageSize) return;
    setPageSize(next);
    setPage(1);
    setJumpPage('');
  };

  const changeTab = (next: JobTypeApi | 'all') => {
    if (next === tab) return;
    setTab(next);
    setPage(1);
    setJumpPage('');
  };

  const toggleExpand = useCallback(
    async (job: JobSummary) => {
      const itemCount = job.nav_hints?.item_count ?? job.progress.total_items;
      if (itemCount <= 0) return;
      const opening = !expandedJobIds.has(job.id);
      setExpandedJobIds(prev => {
        const next = new Set(prev);
        if (opening) next.add(job.id);
        else next.delete(job.id);
        return next;
      });
      if (opening && !jobDetails[job.id] && !detailLoadingIds.has(job.id)) await fetchJobDetails([job.id]);
    },
    [detailLoadingIds, expandedJobIds, fetchJobDetails, jobDetails]
  );

  const onDelete = useCallback(
    async (job: JobSummary) => {
      if (!canDeleteJob(job.status) || deletingJobId) return;
      const title = job.title?.trim() || '未命名任务';
      const confirmed = window.confirm(
        `确定删除任务「${title}」吗？\n\n将删除任务中心中的工单与文件项记录，但保留已上传原件和脱敏结果，处理历史仍可查看。`
      );
      if (!confirmed) return;
      setDeletingJobId(job.id);
      setNotice(null);
      setErr(null);
      try {
        await deleteJob(job.id);
        setExpandedJobIds(prev => {
          const next = new Set(prev);
          next.delete(job.id);
          return next;
        });
        setJobDetails(prev => {
          const next = { ...prev };
          delete next[job.id];
          return next;
        });
        setNotice(`已删除任务「${title}」`);
        const nextPage = rows.length === 1 && page > 1 ? page - 1 : page;
        if (nextPage !== page) setPage(nextPage);
        else await refreshList();
      } catch (e) {
        setErr(e instanceof Error ? e.message : '删除任务失败');
      } finally {
        setDeletingJobId(null);
      }
    },
    [deletingJobId, page, refreshList, rows.length]
  );

  const visibleRows = useMemo(() => rows, [rows]);
  const tableBusy = loading || refreshing || deletingJobId !== null;
  const rangeStart = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const rangeEnd = total === 0 ? 0 : Math.min(page * pageSize, total);

  const pageMetrics = useMemo(
    () =>
      visibleRows.reduce(
        (acc, job) => {
          if (job.status === 'draft') acc.draft += 1;
          else if (ACTIVE_STATUSES.has(job.status)) acc.processing += 1;
          else if (job.status === 'awaiting_review') acc.awaitingReview += 1;
          else if (job.status === 'completed') acc.completed += 1;
          else if (job.status === 'failed' || job.status === 'cancelled') acc.risk += 1;
          return acc;
        },
        { draft: 0, processing: 0, awaitingReview: 0, completed: 0, risk: 0 }
      ),
    [visibleRows]
  );

  const stopEvent = (event: React.MouseEvent) => {
    event.stopPropagation();
  };

  return (
    <div className="jobs-root flex-1 min-h-0 min-w-0 flex flex-col bg-[#f5f5f7] overflow-hidden">
      <div className="flex-1 flex flex-col min-h-0 min-w-0 px-3 py-3 sm:px-5 sm:py-4 w-full max-w-[min(100%,1920px)] mx-auto items-stretch">
        <div className="flex flex-wrap items-center gap-2 mb-3 flex-shrink-0">
          <div className="flex items-center gap-1.5">
            {(
              [
                { k: 'all' as const, label: '全部' },
                { k: 'text_batch' as const, label: '文本批量' },
                { k: 'image_batch' as const, label: '图像批量' },
              ] as const
            ).map(({ k, label }) => (
              <button
                key={k}
                type="button"
                onClick={() => changeTab(k)}
                className={`text-2xs sm:text-xs font-medium px-2.5 py-1 rounded-lg border transition-colors ${
                  tab === k
                    ? 'border-[#1d1d1f] bg-[#1d1d1f] text-white'
                    : 'border-gray-200 bg-white text-gray-600 hover:bg-gray-50'
                }`}
              >
                {label}
              </button>
            ))}
            <button
              type="button"
              onClick={() => void refreshList()}
              disabled={tableBusy}
              className={outlineActionClass('neutral')}
              title="手动刷新列表"
            >
              {refreshing ? '刷新中...' : '点击刷新'}
            </button>
          </div>

          <div className="ml-auto flex flex-wrap items-center gap-2 text-xs text-gray-500">
            <span>本页 {visibleRows.length} 条</span>
            <span className="text-gray-300">|</span>
            <span>待配置 {pageMetrics.draft}</span>
            <span className="text-gray-300">|</span>
            <span>处理中 {pageMetrics.processing}</span>
            <span className="text-gray-300">|</span>
            <span>待复核 {pageMetrics.awaitingReview}</span>
            <span className="text-gray-300">|</span>
            <span>已完成 {pageMetrics.completed}</span>
            <span className="text-gray-300">|</span>
            <span>异常 {pageMetrics.risk}</span>
          </div>
        </div>

        {notice && (
          <div className="mb-3 rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-900 text-sm px-3 py-2 flex-shrink-0">
            {notice}
          </div>
        )}
        {err && (
          <div className="mb-3 rounded-lg border border-red-200 bg-red-50 text-red-900 text-sm px-3 py-2 flex-shrink-0">
            {err}
          </div>
        )}

        <div className="jobs-surface w-full flex flex-col flex-1 min-h-0 bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="px-4 py-2.5 border-b border-gray-100 flex flex-wrap items-center justify-between gap-2 flex-shrink-0">
            <div>
              <h3 className="font-semibold text-gray-900 text-sm">任务记录</h3>
              <p className="text-xs text-gray-400 mt-0.5">共 {total} 条 · 第 {page} / {totalPages} 页 · 当前为手动刷新</p>
            </div>
            <div className="flex flex-wrap items-center gap-3 text-2xs text-gray-500">
              <span>支持展开查看任务内文件</span>
              <span className="text-gray-300">|</span>
              <span className="text-amber-700">运行中任务需先取消后删除</span>
            </div>
          </div>

          {visibleRows.length > 0 && (
            <div className="jobs-table-head px-4 py-2 border-b border-gray-50 bg-[#fafafa] text-xs text-gray-500 font-medium flex-shrink-0">
              <span />
              <span>任务</span>
              <span>执行方式</span>
              <span>进度</span>
              <span>当前状态</span>
              <span>更新时间</span>
              <span className="text-right">操作</span>
            </div>
          )}

          <div className="relative flex-1 min-h-0 overflow-y-auto flex flex-col">
            {refreshing && visibleRows.length > 0 && (
              <div className="absolute inset-0 bg-white/60 flex items-center justify-center z-10 backdrop-blur-[1px]">
                <div className="w-7 h-7 border-2 border-[#e5e5e5] border-t-[#1d1d1f] rounded-full animate-spin" />
              </div>
            )}

            {loading && visibleRows.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 gap-3">
                <div className="w-7 h-7 border-2 border-[#e5e5e5] border-t-[#1d1d1f] rounded-full animate-spin" />
                <p className="text-sm text-gray-400">加载中...</p>
              </div>
            ) : visibleRows.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 gap-4">
                <div className="w-16 h-16 rounded-2xl bg-gray-100 flex items-center justify-center">
                  <svg className="w-8 h-8 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={1.5}
                      d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                    />
                  </svg>
                </div>
                <div className="text-center">
                  <p className="text-sm text-gray-500 mb-1">暂无任务记录</p>
                  <p className="text-xs text-gray-400">从批量任务入口创建后，会在这里持续管理进度、展开文件树和删除工单</p>
                </div>
                <Link to="/batch" className={outlineActionClass('neutral')}>
                  前往批量任务
                </Link>
              </div>
            ) : (
              <ul className="flex w-full flex-col divide-y divide-gray-100">
                {visibleRows.map((job, index) => {
                  const primary = resolveJobPrimaryNavigation({
                    jobId: job.id,
                    status: job.status,
                    jobType: job.job_type,
                    items: [],
                    currentPage: 'other',
                    navHints: job.nav_hints,
                    jobConfig: job.config,
                  });
                  const detailHref = `/jobs/${encodeURIComponent(job.id)}`;
                  const showPrimaryAction = primary.kind === 'link' && primary.to !== detailHref;
                  const showWorkbenchShortcut = ACTIVE_STATUSES.has(job.status);
                  const deleteBlocked = !canDeleteJob(job.status);
                  const stripe = index % 2 === 1 ? 'bg-[#fafafa]' : 'bg-white';
                  const itemCount = job.nav_hints?.item_count ?? job.progress.total_items;
                  const finishedCount = job.progress.completed + job.progress.failed + (job.progress.cancelled ?? 0);
                  const progressPercent = itemCount > 0 ? Math.min(100, Math.round((finishedCount / itemCount) * 100)) : 0;
                  const progressHeadline = buildProgressHeadline(job.progress);
                  const progressSummary = buildProgressSummary(job.progress, itemCount, finishedCount);
                  const expanded = expandedJobIds.has(job.id);
                  const detail = jobDetails[job.id];
                  const detailLoading = detailLoadingIds.has(job.id);
                  const expandable = itemCount > 0;
                  return (
                    <li key={job.id}>
                      <div
                        className={`${stripe} transition-colors ${expandable ? 'cursor-pointer hover:bg-gray-50/90' : 'hover:bg-gray-50/70'}`}
                        onClick={expandable ? () => void toggleExpand(job) : undefined}
                      >
                        <div className="jobs-row-main flex flex-col gap-2 px-3 sm:px-4 py-2.5">
                          <div className="flex items-center justify-start md:justify-center">
                            {itemCount > 0 ? (
                              <button
                                type="button"
                                onClick={event => {
                                  event.stopPropagation();
                                  void toggleExpand(job);
                                }}
                                className="w-6 h-6 rounded-md border border-gray-200 bg-white text-gray-500 hover:bg-gray-50 transition-colors flex items-center justify-center"
                                title={expanded ? '收起文件' : '展开文件'}
                                aria-expanded={expanded}
                              >
                                <svg
                                  className={`w-3.5 h-3.5 transition-transform ${expanded ? 'rotate-90' : ''}`}
                                  fill="none"
                                  stroke="currentColor"
                                  viewBox="0 0 24 24"
                                >
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                                </svg>
                              </button>
                            ) : (
                              <span className="w-6 h-6 rounded-md bg-gray-100 text-gray-300 flex items-center justify-center text-xs">·</span>
                            )}
                          </div>

                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className={`text-2xs font-semibold px-1.5 py-0.5 rounded ${typeToneClass(job.job_type)}`}>
                                {pathLabel(job.job_type)}
                              </span>
                              <p className="text-sm font-medium text-gray-900 truncate" title={job.title || '未命名任务'}>
                                {job.title || '未命名任务'}
                              </p>
                            </div>
                            <p className="text-caption text-gray-500 mt-0.5">ID {job.id.slice(0, 8)}... · {itemCount} 项</p>
                            <p className="text-caption text-gray-400 mt-0.5 md:hidden">更新时间 {formatUpdatedAt(job.updated_at)}</p>
                          </div>

                          <div className="flex items-center gap-2">
                            <span className="text-xs text-gray-400 md:hidden">执行</span>
                            <span className="inline-flex px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 text-2xs whitespace-nowrap">
                              {executionLabel(job.config)}
                            </span>
                          </div>

                          <div className="min-w-0">
                            <div className="flex flex-col gap-1.5">
                              <div className="flex items-center justify-between gap-2">
                                <span className="text-xs font-medium text-gray-700 tabular-nums truncate">
                                  {progressHeadline}
                                </span>
                                <span className="text-caption text-gray-400 tabular-nums shrink-0">{progressPercent}%</span>
                              </div>
                              <div className="h-1.5 rounded-full bg-gray-100 overflow-hidden">
                                <div
                                  className={`h-full rounded-full ${
                                    job.status === 'failed'
                                      ? 'bg-red-400'
                                      : job.status === 'completed'
                                        ? 'bg-emerald-500'
                                        : 'bg-[#1d1d1f]'
                                  }`}
                                  style={{ width: `${progressPercent}%` }}
                                />
                              </div>
                              <p className="text-caption text-gray-400 truncate">{progressSummary}</p>
                            </div>
                          </div>

                          <div className="flex items-center gap-2">
                            <span className="text-xs text-gray-400 md:hidden">状态</span>
                            <span
                              className={`inline-flex text-2xs font-medium px-2 py-0.5 rounded-full whitespace-nowrap ${statusToneClass(job.status)}`}
                              title={getAggregateJobStatusMeta(job.status).description}
                            >
                              {formatAggregateJobStatus(job.status)}
                            </span>
                          </div>

                          <div className="hidden md:block text-caption text-gray-400 tabular-nums whitespace-nowrap">
                            {formatUpdatedAt(job.updated_at)}
                          </div>

                          <div className="flex flex-wrap items-center gap-2 md:flex-nowrap md:justify-end" onClick={stopEvent}>
                            {showPrimaryAction ? (
                              <Link to={primary.to} onClick={stopEvent} className={primaryActionClass(job.status)}>
                                {primary.label}
                              </Link>
                            ) : null}
                            <Link to={detailHref} onClick={stopEvent} className={outlineActionClass('neutral')}>
                              查看详情
                            </Link>
                            {showWorkbenchShortcut && (
                              <Link
                                to={buildBatchWorkbenchUrl(job.id, job.job_type, 3)}
                                onClick={stopEvent}
                                className={outlineActionClass('neutral')}
                              >
                                打开工作台
                              </Link>
                            )}
                            {deleteBlocked ? (
                              <span className={passiveOutlineClass()}>先取消后删除</span>
                            ) : (
                              <button
                                type="button"
                                disabled={deletingJobId === job.id}
                                onClick={event => {
                                  event.stopPropagation();
                                  void onDelete(job);
                                }}
                                className={outlineActionClass('danger')}
                              >
                                {deletingJobId === job.id ? '删除中...' : '删除任务'}
                              </button>
                            )}
                          </div>
                        </div>

                        {expanded && (
                          <div className="border-t border-gray-100 bg-[#fafafa]" onClick={stopEvent}>
                            {detailLoading ? (
                              <div className="px-4 py-4 text-xs text-gray-400 flex items-center gap-2">
                                <div className="w-4 h-4 border-2 border-[#e5e5e5] border-t-[#1d1d1f] rounded-full animate-spin" />
                                加载文件明细...
                              </div>
                            ) : detail && detail.items.length > 0 ? (
                              <div className="px-3 sm:px-4 py-2">
                                <div className="jobs-child-head px-0 py-1.5 border-b border-gray-100 text-2xs text-gray-500 bg-white/70">
                                  <span />
                                  <span>文件</span>
                                  <span>状态</span>
                                  <span>结果</span>
                                  <span>更新时间</span>
                                </div>
                                <ul className="divide-y divide-gray-100">
                                  {detail.items.map((item: JobItemRow, itemIndex: number) => (
                                    <li key={item.id} className="py-2.5">
                                      <div className="jobs-child-row flex flex-col gap-2">
                                        <span className="text-gray-300 text-sm text-center select-none" aria-hidden>
                                          {itemTreeGlyph(itemIndex, detail.items.length)}
                                        </span>
                                        <div className="min-w-0">
                                          <p className="text-sm font-medium text-gray-800 break-words" title={item.filename || item.file_id}>
                                            {item.filename || item.file_id}
                                          </p>
                                          <p className="text-caption text-gray-400 mt-0.5">
                                            {item.file_type ? String(item.file_type) : 'unknown'} · 识别 {item.entity_count ?? 0}
                                            {item.has_review_draft ? ' · 有草稿' : ''}
                                          </p>
                                        </div>
                                        <div className="flex md:block items-center gap-2">
                                          <span className={`inline-flex rounded-md px-2.5 py-1 text-xs font-medium leading-none ${itemStatusToneClass(item.status)}`}>
                                            {formatJobItemStatus(item.status)}
                                          </span>
                                        </div>
                                        <div className="flex md:block items-center gap-2">
                                          <span
                                            className={`inline-flex rounded-md px-2.5 py-1 text-xs font-medium leading-none ${
                                              item.has_output
                                                ? 'bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200'
                                                : 'bg-gray-100 text-gray-500 ring-1 ring-inset ring-gray-200'
                                            }`}
                                          >
                                            {item.has_output ? '已脱敏' : '未脱敏'}
                                          </span>
                                        </div>
                                        <div className="text-caption text-gray-400 tabular-nums whitespace-nowrap">
                                          {formatUpdatedAt(item.updated_at)}
                                        </div>
                                      </div>
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            ) : (
                              <div className="px-4 py-4 text-xs text-gray-400">当前任务没有文件明细。</div>
                            )}
                          </div>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {total > 0 && (
            <div className="px-4 py-2.5 border-t border-gray-100 flex flex-wrap items-center justify-between gap-2 bg-[#fafafa] flex-shrink-0">
              <div className="flex items-center gap-2 text-xs text-gray-500">
                <span>显示 {rangeStart}-{rangeEnd} 条，共 {total} 条</span>
                <span className="text-gray-300">|</span>
                <span>每页</span>
                <select
                  value={pageSize}
                  onChange={e => changePageSize(Number(e.target.value))}
                  className="border border-gray-200 rounded-lg px-1.5 py-1 bg-white text-[#0a0a0a] text-xs"
                >
                  {PAGE_SIZE_OPTIONS.map(size => (
                    <option key={size} value={size}>
                      {size} 条
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  disabled={page <= 1 || tableBusy}
                  onClick={() => goPage(1)}
                  className="px-2 py-1.5 text-xs font-medium rounded-lg border border-gray-200 bg-white hover:bg-gray-50 disabled:opacity-40"
                  title="首页"
                >
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
                  </svg>
                </button>
                <button
                  type="button"
                  disabled={page <= 1 || tableBusy}
                  onClick={() => goPage(page - 1)}
                  className="px-2.5 py-1.5 text-xs font-medium rounded-lg border border-gray-200 bg-white hover:bg-gray-50 disabled:opacity-40"
                >
                  上一页
                </button>
                <div className="flex items-center gap-1 px-1">
                  <input
                    type="text"
                    value={jumpPage}
                    onChange={e => setJumpPage(e.target.value.replace(/\D/g, ''))}
                    onKeyDown={e => {
                      if (e.key !== 'Enter') return;
                      const next = Number.parseInt(jumpPage, 10);
                      if (next >= 1 && next <= totalPages) {
                        goPage(next);
                        setJumpPage('');
                      }
                    }}
                    placeholder={String(page)}
                    className="w-10 text-center text-xs border border-gray-200 rounded-lg py-1 bg-white focus:border-gray-400 focus:outline-none"
                  />
                  <span className="text-xs text-gray-400">/ {totalPages}</span>
                </div>
                <button
                  type="button"
                  disabled={page >= totalPages || tableBusy}
                  onClick={() => goPage(page + 1)}
                  className="px-2.5 py-1.5 text-xs font-medium rounded-lg border border-gray-200 bg-white hover:bg-gray-50 disabled:opacity-40"
                >
                  下一页
                </button>
                <button
                  type="button"
                  disabled={page >= totalPages || tableBusy}
                  onClick={() => goPage(totalPages)}
                  className="px-2 py-1.5 text-xs font-medium rounded-lg border border-gray-200 bg-white hover:bg-gray-50 disabled:opacity-40"
                  title="末页"
                >
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 5l7 7-7 7M5 5l7 7-7 7" />
                  </svg>
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
