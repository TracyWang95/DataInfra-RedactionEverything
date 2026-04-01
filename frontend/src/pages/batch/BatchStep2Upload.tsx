import React from 'react';
import { Link } from 'react-router-dom';
import type { Step, BatchRow, BatchWizardMode } from './batchTypes';

export interface BatchStep2UploadProps {
  mode: BatchWizardMode;
  activeJobId: string | null;
  rows: BatchRow[];
  loading: boolean;
  isDragActive: boolean;
  getRootProps: () => Record<string, unknown>;
  getInputProps: () => Record<string, unknown>;
  goStep: (s: Step) => void;
}

export const BatchStep2Upload: React.FC<BatchStep2UploadProps> = ({
  mode,
  activeJobId,
  rows,
  loading,
  isDragActive,
  getRootProps,
  getInputProps,
  goStep,
}) => {
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="flex flex-col gap-4">
        {activeJobId && (
          <div className="text-2xs sm:text-xs text-gray-600 rounded-lg border border-gray-100 bg-white px-3 py-2">
            当前任务工单{' '}
            <Link to={`/jobs/${activeJobId}`} className="font-mono text-[#007AFF] hover:underline break-all">
              {activeJobId}
            </Link>
            ；上传文件将自动归入此任务。
          </div>
        )}
        <div
          {...getRootProps()}
          className={`min-h-[220px] rounded-xl border-2 border-dashed flex flex-col items-center justify-center px-6 py-8 cursor-pointer transition-all ${
            isDragActive ? 'border-[#1d1d1f] bg-white shadow-sm' : 'border-[#e5e5e5] bg-white hover:border-[#d4d4d4]'
          } ${loading ? 'opacity-50 pointer-events-none' : ''}`}
        >
          <input {...getInputProps()} />
          <p className="text-base font-medium text-[#1d1d1f]">拖放多个文件，或点击选择</p>
          <p className="text-xs text-[#a3a3a3] mt-2">
            {mode === 'smart'
              ? '支持 Word (.docx)、PDF、图片 (.jpg .png)，系统自动识别文件类型'
              : mode === 'image'
                ? '支持图片 (.jpg .png) 和扫描件 PDF'
                : '支持 Word (.docx .doc) 和 PDF 文档'}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => goStep(1)}
            className="px-4 py-2 text-sm border border-gray-200 rounded-lg bg-white"
          >
            上一步
          </button>
          <button
            type="button"
            onClick={() => goStep(3)}
            disabled={!rows.length}
            className="px-4 py-2 text-sm font-medium rounded-lg bg-[#1d1d1f] text-white disabled:opacity-40"
          >
            下一步：批量识别
          </button>
        </div>
      </div>
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden flex flex-col min-h-[240px]">
        <div className="px-4 py-3 border-b border-gray-100">
          <h3 className="font-semibold text-gray-900 text-sm">上传队列</h3>
          <p className="text-xs text-gray-400">共 {rows.length} 个</p>
        </div>
        <div className="flex-1 overflow-y-auto max-h-[320px] divide-y divide-gray-50">
          {rows.length === 0 ? (
            <p className="p-6 text-sm text-gray-400 text-center">暂无文件</p>
          ) : (
            rows.map(r => (
              <div key={r.file_id} className="px-4 py-2 flex justify-between gap-2 text-sm">
                <span className="truncate">{r.original_filename}</span>
                <span className="text-xs text-gray-400 shrink-0">{r.file_type}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};
