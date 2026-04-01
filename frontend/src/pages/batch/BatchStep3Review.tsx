import React, { useState } from 'react';
import type { Step, BatchRow } from './batchTypes';
import { ANALYZE_STATUS_LABEL, RECOGNITION_DONE_STATUSES } from './batchTypes';

export interface BatchStep3ReviewProps {
  rows: BatchRow[];
  analyzeRunning: boolean;
  analyzeDoneCount: number;
  activeJobId: string | null;
  failedRows: BatchRow[];
  canGoStep: (target: Step) => boolean;
  goStep: (s: Step) => void;
  submitQueueToWorker: () => Promise<void>;
  requeueFailedItems: () => Promise<void>;
}

export const BatchStep3Review: React.FC<BatchStep3ReviewProps> = ({
  rows,
  analyzeRunning,
  analyzeDoneCount,
  activeJobId,
  failedRows,
  canGoStep,
  goStep,
  submitQueueToWorker,
  requeueFailedItems,
}) => {
  const allDone = rows.length > 0 && rows.every(r => RECOGNITION_DONE_STATUSES.has(r.analyzeStatus));
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      await submitQueueToWorker();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm space-y-4">
      <h3 className="font-semibold text-gray-900">③ 批量识别</h3>
      <p className="text-xs text-gray-500">
        点击「提交后台队列」将所有文件交给后台 Worker 逐个处理。全部文件识别完成后才可进入核对。
      </p>

      {/* 进度条 */}
      {rows.length > 0 && (
        <div className="space-y-1.5">
          <div className="flex justify-between text-xs text-gray-600">
            <span>识别进度</span>
            <span className="tabular-nums font-medium text-gray-800">
              {analyzeDoneCount} / {rows.length}
            </span>
          </div>
          <div className="h-2.5 rounded-full bg-gray-100 overflow-hidden">
            <div
              className={`h-full rounded-full bg-[#007AFF] transition-[width] duration-700 ease-out ${!allDone ? 'animate-pulse' : ''}`}
              style={{
                width: `${rows.length ? Math.min(100, (analyzeDoneCount / rows.length) * 100) : 0}%`,
              }}
            />
          </div>
        </div>
      )}

      {/* 操作按钮：上一步 | 提交后台队列 | 重新处理失败项 | 下一步 */}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => goStep(2)}
          className="px-4 py-2 text-sm border border-gray-200 rounded-lg bg-white"
        >
          上一步
        </button>

        {activeJobId && !allDone && (
          <button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={!rows.length || analyzeRunning || submitting}
            className="px-4 py-2 text-sm font-medium rounded-lg bg-[#1d1d1f] text-white disabled:opacity-40"
          >
            {submitting ? '提交中…' : analyzeRunning ? '处理中…' : '提交后台队列'}
          </button>
        )}

        {failedRows.length > 0 && (
          <button
            type="button"
            onClick={() => void requeueFailedItems()}
            disabled={analyzeRunning}
            className="px-4 py-2 text-sm font-medium rounded-lg border border-red-200 text-red-600 bg-white hover:bg-red-50 disabled:opacity-40"
          >
            重新处理失败项（{failedRows.length}）
          </button>
        )}

        {/* 下一步：始终显示，全部完成前置灰 */}
        <button
          type="button"
          onClick={() => goStep(4)}
          disabled={!allDone}
          className={`px-4 py-2 text-sm font-medium rounded-lg disabled:opacity-40 ${
            allDone
              ? 'bg-green-600 text-white hover:bg-green-700'
              : 'border border-gray-200 bg-white text-gray-400 cursor-not-allowed'
          }`}
        >
          {allDone ? '下一步：进入核对 →' : `下一步（${analyzeDoneCount}/${rows.length}）`}
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
