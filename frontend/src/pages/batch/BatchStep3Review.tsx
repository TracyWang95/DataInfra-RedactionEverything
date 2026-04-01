import React, { useState, useRef } from 'react';
import type { Step, BatchRow } from './batchTypes';
import { ANALYZE_STATUS_LABEL, RECOGNITION_DONE_STATUSES } from './batchTypes';

export interface BatchStep3ReviewProps {
  rows: BatchRow[];
  activeJobId: string | null;
  failedRows: BatchRow[];
  goStep: (s: Step) => void;
  submitQueueToWorker: () => Promise<void>;
  requeueFailedItems: () => Promise<void>;
}

export const BatchStep3Review: React.FC<BatchStep3ReviewProps> = ({
  rows,
  activeJobId,
  failedRows,
  goStep,
  submitQueueToWorker,
  requeueFailedItems,
}) => {
  const doneCount = rows.filter(r => RECOGNITION_DONE_STATUSES.has(r.analyzeStatus)).length;
  const allDone = rows.length > 0 && doneCount === rows.length;
  // 记住"已提交过"，即使 submitting 结束也保持 true
  const [everSubmitted, setEverSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  const isProcessing = everSubmitted && !allDone;

  const handleSubmit = async () => {
    setSubmitting(true);
    setEverSubmitted(true);
    await submitQueueToWorker();
    // 延迟清 submitting，让第一次轮询有时间返回
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setSubmitting(false), 2000);
  };

  // 进度文案
  const progressLabel = allDone
    ? '✓ 全部完成'
    : isProcessing
      ? `批量任务进行中 ${doneCount}/${rows.length}`
      : `${rows.length} 个文件待提交`;

  // 进度百分比：处理中但还没有完成的给一个最小值，让进度条可见
  const pct = rows.length > 0
    ? Math.min(100, (doneCount / rows.length) * 100)
    : 0;
  const displayPct = isProcessing && pct === 0 ? 3 : pct; // 最小 3% 可见

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm space-y-4">
      <h3 className="font-semibold text-gray-900">③ 批量识别</h3>
      <p className="text-xs text-gray-500">
        点击「提交后台队列」将所有文件交给后台 Worker 逐个处理。全部文件识别完成后才可进入核对。
      </p>

      {/* 进度条：始终显示 */}
      {rows.length > 0 && (
        <div className="space-y-1.5">
          <div className="flex justify-between text-xs">
            <span className={allDone ? 'text-green-600 font-medium' : isProcessing ? 'text-blue-600' : 'text-gray-500'}>
              {progressLabel}
            </span>
            <span className="tabular-nums font-medium text-gray-800">
              {doneCount} / {rows.length}
            </span>
          </div>
          <div className="h-2.5 rounded-full bg-gray-100 overflow-hidden">
            <div
              className={`h-full rounded-full transition-[width] duration-700 ease-out ${
                allDone
                  ? 'bg-green-500'
                  : isProcessing
                    ? 'bg-[#007AFF] animate-pulse'
                    : 'bg-gray-300'
              }`}
              style={{ width: `${displayPct}%` }}
            />
          </div>
        </div>
      )}

      {/* 三个固定按钮 */}
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => goStep(2)}
          className="px-4 py-2 text-sm border border-gray-200 rounded-lg bg-white">
          上一步
        </button>

        <button type="button" onClick={() => void handleSubmit()}
          disabled={!activeJobId || !rows.length || allDone || isProcessing || submitting}
          className="px-4 py-2 text-sm font-medium rounded-lg bg-[#1d1d1f] text-white disabled:opacity-40">
          提交后台队列
        </button>

        {failedRows.length > 0 && (
          <button type="button" onClick={() => void requeueFailedItems()}
            className="px-4 py-2 text-sm font-medium rounded-lg border border-red-200 text-red-600 bg-white hover:bg-red-50">
            重新处理失败项（{failedRows.length}）
          </button>
        )}

        <button type="button" onClick={() => goStep(4)} disabled={!allDone}
          className={`px-4 py-2 text-sm font-medium rounded-lg disabled:opacity-40 ${
            allDone
              ? 'bg-green-600 text-white hover:bg-green-700'
              : 'border border-gray-200 bg-white text-gray-400 cursor-not-allowed'
          }`}>
          {allDone ? '下一步：进入核对 →' : `下一步（${doneCount}/${rows.length}）`}
        </button>
      </div>

      {/* 文件状态列表 */}
      <div className="border border-gray-100 rounded-lg divide-y divide-gray-50 max-h-80 overflow-y-auto">
        {rows.map(r => (
          <div key={r.file_id} className="px-4 py-2 flex flex-wrap items-center gap-2 text-sm">
            <span className="truncate flex-1 min-w-0">{r.original_filename}</span>
            <span className={`text-xs ${r.analyzeStatus === 'completed' ? 'text-green-600' : r.analyzeStatus === 'failed' ? 'text-red-500' : RECOGNITION_DONE_STATUSES.has(r.analyzeStatus) ? 'text-amber-600' : 'text-gray-500'}`}>
              {ANALYZE_STATUS_LABEL[r.analyzeStatus] ?? r.analyzeStatus}
            </span>
            {r.analyzeError && <span className="text-xs text-violet-700">{r.analyzeError}</span>}
          </div>
        ))}
      </div>
    </div>
  );
};
