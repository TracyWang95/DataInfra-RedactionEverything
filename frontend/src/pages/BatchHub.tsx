import React, { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { createJob, listJobs, type JobSummary, type JobTypeApi } from '../services/jobsApi';
import { resolveJobPrimaryNavigation } from '../utils/jobPrimaryNavigation';
import { formatAggregateJobStatus } from '../utils/jobStatusLabels';

function batchPath(jobType: JobTypeApi): string {
  if (jobType === 'image_batch') return '/batch/image';
  if (jobType === 'smart_batch') return '/batch/smart';
  return '/batch/text';
}

function isActiveJob(status: string): boolean {
  return ['draft', 'queued', 'running', 'awaiting_review', 'redacting'].includes(status);
}

export const BatchHub: React.FC = () => {
  const nav = useNavigate();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [recentJobs, setRecentJobs] = useState<JobSummary[]>([]);
  const [recentLoading, setRecentLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setRecentLoading(true);
      try {
        const res = await listJobs({ page: 1, page_size: 20 });
        if (!cancelled) {
          setRecentJobs(res.jobs.filter(j => isActiveJob(j.status)));
        }
      } catch {
        if (!cancelled) setRecentJobs([]);
      } finally {
        if (!cancelled) setRecentLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const recentByType = useMemo(() => {
    const seen = new Set<JobTypeApi>();
    const out: JobSummary[] = [];
    for (const j of recentJobs) {
      if (seen.has(j.job_type)) continue;
      seen.add(j.job_type);
      out.push(j);
    }
    return out;
  }, [recentJobs]);

  const start = async (jobType: JobTypeApi) => {
    setErr(null);
    setBusy(true);
    try {
      const j = await createJob({
        job_type: jobType,
        title: `批量任务 ${new Date().toLocaleString()}`,
        config: {},
      });
      nav(`${batchPath(jobType)}?jobId=${encodeURIComponent(j.id)}&step=1`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : '创建失败');
    } finally {
      setBusy(false);
    }
  };

  const continueTask = (job: JobSummary) => {
    const navTarget = resolveJobPrimaryNavigation({
      jobId: job.id,
      status: job.status,
      jobType: job.job_type,
      items: [],
      currentPage: 'other',
      navHints: job.nav_hints,
      jobConfig: job.config,
    });
    if (navTarget.kind === 'link') {
      nav(navTarget.to);
    } else {
      nav(`/jobs/${encodeURIComponent(job.id)}`);
    }
  };

  return (
    <div className="h-full min-h-0 flex flex-col bg-[#fafafa] px-3 py-4 sm:px-6 overflow-y-auto">
      <div className="max-w-3xl mx-auto w-full space-y-4">
        <div>
          <h2 className="text-lg font-semibold text-[#1d1d1f]">开始或恢复批量任务</h2>
          <p className="text-sm text-gray-500 mt-1">
            先创建任务工单，再进入配置、上传、识别和审阅。最近活跃任务可以直接继续，不必重新创建。
          </p>
        </div>
        {err && <div className="rounded-lg border border-red-200 bg-red-50 text-red-900 text-sm px-3 py-2">{err}</div>}

        <div className="grid gap-3">
          <button
            type="button"
            disabled={busy}
            onClick={() => void start('smart_batch')}
            className="text-left rounded-xl border border-black/[0.08] bg-white p-5 shadow-sm hover:border-[#1d1d1f]/20 transition-colors disabled:opacity-50"
          >
            <div className="text-sm font-semibold text-[#1d1d1f]">新建批量任务</div>
            <p className="text-2xs text-gray-500 mt-1">
              支持 Word / PDF / 图片混合上传，系统自动识别文件类型并选择最佳处理方式。
            </p>
          </button>
        </div>

        <div className="rounded-2xl border border-black/[0.06] bg-white shadow-sm overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-semibold text-[#1d1d1f]">继续最近任务</h3>
              <p className="text-2xs text-gray-500 mt-0.5">按任务状态跳转到配置、上传、监控或审阅。</p>
            </div>
            <Link to="/jobs" className="text-xs font-medium text-[#007AFF] hover:underline">
              任务中心
            </Link>
          </div>
          {recentLoading ? (
            <div className="px-4 py-6 text-sm text-gray-500">加载中...</div>
          ) : recentByType.length === 0 ? (
            <div className="px-4 py-6 text-sm text-gray-500">暂无可恢复的活跃任务。可以直接新建一个批量工单。</div>
          ) : (
            <ul className="divide-y divide-gray-100">
              {recentByType.map(job => {
                const primary = resolveJobPrimaryNavigation({
                  jobId: job.id,
                  status: job.status,
                  jobType: job.job_type,
                  items: [],
                  currentPage: 'other',
                  navHints: job.nav_hints,
                  jobConfig: job.config,
                });
                return (
                  <li key={job.id} className="px-4 py-3 flex flex-wrap items-center justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-2xs font-semibold px-1.5 py-0.5 rounded bg-gray-100 text-gray-700">
                          {job.job_type === 'text_batch' ? '文本' : job.job_type === 'smart_batch' ? '智能' : '图像'}
                        </span>
                        <span className="text-sm font-medium text-[#1d1d1f] truncate">{job.title || '未命名任务'}</span>
                        <span className="text-2xs text-gray-500">{formatAggregateJobStatus(job.status)}</span>
                      </div>
                      <div className="text-2xs text-gray-500 mt-1 tabular-nums">
                        共 {job.progress.total_items} 项 · 待审 {job.progress.awaiting_review} · 已完成 {job.progress.completed}
                        {job.progress.failed ? ` · 失败 ${job.progress.failed}` : ''}
                      </div>
                    </div>
                    <div className="shrink-0 flex flex-wrap items-center gap-2 justify-end">
                      {primary.kind === 'link' ? (
                        <button
                          type="button"
                          onClick={() => continueTask(job)}
                          className="text-sm font-medium text-[#007AFF] hover:underline"
                        >
                          {primary.label}
                        </button>
                      ) : (
                        <Link
                          to={`/jobs/${job.id}`}
                          className="text-sm font-medium text-[#007AFF] hover:underline"
                        >
                          查看详情
                        </Link>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <p className="text-2xs text-gray-400">
          {busy ? '正在创建…' : ' '}
          <Link to="/jobs" className="text-[#007AFF] hover:underline ml-2">
            任务中心
          </Link>
          <span className="mx-1">·</span>
          <Link to="/history" className="text-[#007AFF] hover:underline">
            处理历史
          </Link>
        </p>
      </div>
    </div>
  );
};
