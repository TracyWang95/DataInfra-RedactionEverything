import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  approveItemReview,
  cancelJob,
  deleteJob,
  getJob,
  rejectItemReview,
  submitJob,
  type JobDetail,
  type JobItemRow,
} from '../services/jobsApi';
import { resolveJobPrimaryNavigation } from '../utils/jobPrimaryNavigation';
import { formatAggregateJobStatus, formatJobItemStatus } from '../utils/jobStatusLabels';

function pathLabel(jobType: string): string {
  return jobType === 'image_batch' ? '图像批量' : '文本批量';
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
      setErr(e instanceof Error ? e.message : '加载失败');
      setData(null);
    } finally {
      setLoading(false);
      isFetchingRef.current = false;
    }
  }, [jobId]);

  useEffect(() => {
    load();
  }, [load]);

  // SSE for real-time progress updates
  const sseActiveRef = useRef(false);
  useEffect(() => {
    if (!jobId) return;
    const terminalStatuses = ['completed', 'failed', 'cancelled'];
    if (data && terminalStatuses.includes(data.status)) {
      sseActiveRef.current = false;
      return;
    }

    const es = new EventSource(`/api/v1/jobs/${jobId}/stream`);

    es.onopen = () => {
      sseActiveRef.current = true;
    };

    es.onmessage = (event) => {
      try {
        const progress = JSON.parse(event.data);
        if (progress.error) {
          es.close();
          sseActiveRef.current = false;
          return;
        }
        // Update progress and status within current data
        setData((prev) => {
          if (!prev) return prev;
          const { status, ...progressFields } = progress;
          return {
            ...prev,
            status: status ?? prev.status,
            progress: { ...prev.progress, ...progressFields },
          };
        });
        // If terminal, close SSE and do a full reload
        if (progress.status && terminalStatuses.includes(progress.status)) {
          es.close();
          sseActiveRef.current = false;
          load();
        }
      } catch {
        // ignore parse errors
      }
    };

    es.onerror = () => {
      es.close();
      sseActiveRef.current = false;
      // Polling fallback will continue working
    };

    return () => {
      es.close();
      sseActiveRef.current = false;
    };
  }, [jobId, data?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  // Polling fallback (runs at slower rate when SSE is active)
  useEffect(() => {
    const tick = () => {
      if (document.visibilityState === 'visible') {
        load().catch((err) => { if (import.meta.env.DEV) console.error('Load failed:', err); });
      }
    };
    const interval = sseActiveRef.current ? 15000 : 3500;
    const t = window.setInterval(tick, interval);
    document.addEventListener('visibilitychange', tick);
    return () => {
      window.clearInterval(t);
      document.removeEventListener('visibilitychange', tick);
    };
  }, [load]);

  const batchPath = (j: JobDetail) => (j.job_type === 'image_batch' ? '/batch/image' : j.job_type === 'smart_batch' ? '/batch/smart' : '/batch/text');
  const editHref = (item: JobItemRow) =>
    `${batchPath(data!)}?jobId=${encodeURIComponent(jobId)}&itemId=${encodeURIComponent(item.id)}&step=4`;

  const onSubmit = async () => {
    if (!jobId) return;
    setActionMsg(null);
    try {
      await submitJob(jobId);
      setActionMsg('已提交队列');
      await load();
    } catch (e) {
      setActionMsg(e instanceof Error ? e.message : '提交失败');
    }
  };

  const onCancel = async () => {
    if (!jobId) return;
    setActionMsg(null);
    try {
      await cancelJob(jobId);
      setActionMsg('已取消');
      await load();
    } catch (e) {
      setActionMsg(e instanceof Error ? e.message : '取消失败');
    }
  };

  const onDelete = async () => {
    if (!jobId || !data || deleting || !canDeleteJob(data.status)) return;
    const title = data.title?.trim() || '未命名任务';
    const confirmed = window.confirm(
      `确定删除任务「${title}」吗？\n\n将删除任务中心中的工单与文件项记录，但保留已上传原件和脱敏结果，处理历史仍可查看。`
    );
    if (!confirmed) return;

    setDeleting(true);
    setActionMsg(null);
    try {
      await deleteJob(jobId);
      navigate('/jobs', { replace: true });
    } catch (e) {
      setActionMsg(e instanceof Error ? e.message : '删除任务失败');
    } finally {
      setDeleting(false);
    }
  };

  const onApprove = async (item: JobItemRow) => {
    setActionMsg(null);
    try {
      await approveItemReview(jobId, item.id);
      setActionMsg('已确认');
      await load();
    } catch (e) {
      setActionMsg(e instanceof Error ? e.message : '操作失败');
    }
  };

  const onReject = async (item: JobItemRow) => {
    setActionMsg(null);
    try {
      await rejectItemReview(jobId, item.id);
      setActionMsg('已打回重跑');
      await load();
    } catch (e) {
      setActionMsg(e instanceof Error ? e.message : '操作失败');
    }
  };

  const detailItems = useMemo(() => data?.items ?? [], [data]);

  if (!jobId) return <p className="p-4 text-sm text-gray-500">无效任务</p>;
  if (loading && !data) return <p className="p-4 text-sm text-gray-500">加载中...</p>;
  if (err || !data) {
    return (
      <div className="p-4 space-y-2">
        <p className="text-sm text-red-700">{err ?? '未找到任务'}</p>
        <Link to="/jobs" className="text-sm text-[#007AFF]">
          返回列表
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
    <div className="h-full min-h-0 flex flex-col bg-[#fafafa] px-3 py-3 sm:px-5 sm:py-4 overflow-y-auto">
      <div className="max-w-5xl mx-auto w-full space-y-3">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Link to="/jobs" className="text-[#007AFF] hover:underline">
            任务中心
          </Link>
          <span className="text-gray-300">/</span>
          <span className="text-[#1d1d1f] font-medium truncate">{j.title || '未命名任务'}</span>
        </div>

        {actionMsg && (
          <div className="rounded-lg border border-gray-200 bg-white text-sm px-3 py-2 text-gray-800">{actionMsg}</div>
        )}

        <div className="rounded-xl border border-black/[0.06] bg-white shadow-sm p-3 sm:p-4 space-y-2">
          <div className="flex flex-wrap gap-2 text-2xs sm:text-xs text-gray-600">
            <span>类型：{pathLabel(j.job_type)}</span>
            <span>状态：{formatAggregateJobStatus(j.status)}</span>
            <span>共 {j.progress.total_items} 项</span>
            <span>待审 {j.progress.awaiting_review}</span>
            <span>完成 {j.progress.completed}</span>
            {j.skip_item_review && <span className="text-amber-700 font-medium">已开启跳过逐项确认</span>}
          </div>
          <div className="flex flex-wrap gap-2">
            {j.status === 'draft' && (
              <button
                type="button"
                onClick={onSubmit}
                className="text-xs sm:text-sm font-medium rounded-lg bg-[#1d1d1f] text-white px-3 py-1.5 hover:opacity-90"
              >
                提交队列
              </button>
            )}
            {!['completed', 'cancelled', 'failed'].includes(j.status) && (
              <button
                type="button"
                onClick={onCancel}
                className="text-xs sm:text-sm font-medium rounded-lg border border-gray-300 px-3 py-1.5 text-gray-700 hover:bg-gray-50"
              >
                取消任务
              </button>
            )}
            {canDeleteJob(j.status) ? (
              <button
                type="button"
                disabled={deleting}
                onClick={onDelete}
                className="text-xs sm:text-sm font-medium rounded-lg border border-red-200 px-3 py-1.5 text-red-600 hover:bg-red-50 disabled:opacity-50"
              >
                {deleting ? '删除中…' : '删除任务'}
              </button>
            ) : (
              <span className="text-xs text-gray-400">运行中任务请先取消，再删除</span>
            )}
            {primaryNav.kind === 'link' && (
              <Link
                to={primaryNav.to}
                className="text-xs sm:text-sm font-medium rounded-lg bg-[#007AFF] text-white px-3 py-1.5 hover:opacity-95"
              >
                {primaryNav.label}
              </Link>
            )}
            {primaryNav.kind === 'none' && primaryNav.reason && (
              <span className="text-xs text-gray-400">{primaryNav.reason}</span>
            )}
          </div>
          {detailItems.some(it => it.status === 'awaiting_review') && (
            <p className="text-2xs text-gray-500 pt-1 border-t border-gray-100 mt-2">
              「快速确认」将本文件标为审阅通过并入队脱敏；完整划词/拉框修改请在主按钮进入的批量向导第 4 步中操作并保存草稿。
            </p>
          )}
        </div>

        <h3 className="text-sm font-semibold text-[#1d1d1f]">文件明细</h3>
        <div className="rounded-xl border border-black/[0.06] bg-white overflow-hidden">
          <table className="w-full text-left text-2xs sm:text-xs">
            <thead className="bg-gray-50 text-gray-600 border-b border-gray-100">
              <tr>
                <th className="px-3 py-2 font-medium">文件</th>
                <th className="px-3 py-2 font-medium">状态</th>
                <th className="px-3 py-2 font-medium">草稿</th>
                <th className="px-3 py-2 font-medium text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {detailItems.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-3 py-6 text-center text-gray-500">
                    暂无文件，请先在批量入口上传。
                  </td>
                </tr>
              ) : (
                detailItems.map(it => (
                  <tr key={it.id} className="border-t border-gray-100">
                    <td className="px-3 py-2">
                      <div className="font-medium text-gray-900 truncate" title={it.filename || it.file_id}>
                        {it.filename || it.file_id}
                      </div>
                      <div className="text-2xs text-gray-400 font-mono break-all">{it.file_id}</div>
                      <div className="text-2xs text-gray-500 mt-0.5">
                        {it.file_type ? String(it.file_type) : 'unknown'} · {it.entity_count ?? 0} 项
                        {it.has_output ? ' · 已脱敏' : ''}
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <span className="text-gray-800">{formatJobItemStatus(it.status)}</span>
                      {it.error_message && (
                        <div className="text-red-600 mt-0.5 max-w-xs truncate" title={it.error_message}>
                          {it.error_message}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {it.has_review_draft ? (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-amber-50 text-amber-800">
                          有草稿 {it.review_draft_updated_at ? `· ${new Date(it.review_draft_updated_at).toLocaleString()}` : ''}
                        </span>
                      ) : (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">无草稿</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right space-x-2 whitespace-nowrap">
                      {j.status === 'cancelled' ? (
                        <span className="text-gray-400 text-2xs">已取消</span>
                      ) : (
                        <>
                          <Link to={editHref(it)} className="text-[#007AFF] font-medium hover:underline">
                            进入审阅
                          </Link>
                          {it.status === 'awaiting_review' && (
                            <>
                              <button
                                type="button"
                                className="text-emerald-700 font-medium hover:underline"
                                onClick={() => onApprove(it)}
                              >
                                快速确认
                              </button>
                              <button
                                type="button"
                                className="text-gray-600 hover:underline"
                                onClick={() => onReject(it)}
                              >
                                打回
                              </button>
                            </>
                          )}
                        </>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
