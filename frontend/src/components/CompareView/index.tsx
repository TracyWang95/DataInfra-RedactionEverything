import React, { useState } from 'react';
import { useFileStore, useRedactionConfigStore } from '../../hooks/useRedaction';
import {
  ArrowsRightLeftIcon,
  Square2StackIcon,
  DocumentArrowDownIcon,
} from '@heroicons/react/24/outline';
import clsx from 'clsx';
import { fileApi } from '../../services/api';

type CompareMode = 'side-by-side' | 'overlay' | 'changes-only';

export const CompareView: React.FC = () => {
  const fileInfo = useFileStore((s) => s.fileInfo);
  const compareData = useRedactionConfigStore((s) => s.compareData);
  const redactionResult = useRedactionConfigStore((s) => s.redactionResult);
  const [mode, setMode] = useState<CompareMode>('side-by-side');

  if (!compareData || !redactionResult) {
    return (
      <div className="flex items-center justify-center h-full text-ink-subtle">
        <p>暂无对比数据</p>
      </div>
    );
  }

  const handleDownload = () => {
    if (fileInfo) {
      const url = fileApi.getDownloadUrl(fileInfo.file_id, true);
      window.open(url, '_blank');
    }
  };

  return (
    <div className="h-full flex flex-col bg-surface-secondary">
      {/* 工具栏 */}
      <div className="p-4 bg-white dark:bg-gray-800 border-b border-line dark:border-gray-700 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm text-ink-muted">对比模式:</span>
          <div className="flex bg-surface-tertiary rounded-lg p-1" role="tablist" aria-label="对比模式">
            <button
              role="tab"
              aria-selected={mode === 'side-by-side'}
              aria-label="左右对比模式"
              onClick={() => setMode('side-by-side')}
              className={clsx(
                'px-3 py-1.5 text-sm rounded-md flex items-center gap-1.5 transition-colors',
                mode === 'side-by-side'
                  ? 'bg-white dark:bg-gray-700 text-ink shadow-sm'
                  : 'text-ink-muted hover:text-ink'
              )}
            >
              <ArrowsRightLeftIcon className="w-4 h-4" />
              左右对比
            </button>
            <button
              role="tab"
              aria-selected={mode === 'changes-only'}
              aria-label="仅显示变更"
              onClick={() => setMode('changes-only')}
              className={clsx(
                'px-3 py-1.5 text-sm rounded-md flex items-center gap-1.5 transition-colors',
                mode === 'changes-only'
                  ? 'bg-white dark:bg-gray-700 text-ink shadow-sm'
                  : 'text-ink-muted hover:text-ink'
              )}
            >
              <Square2StackIcon className="w-4 h-4" />
              仅显示变更
            </button>
          </div>
        </div>

        <button
          onClick={handleDownload}
          className="px-4 py-2 bg-primary-600 text-white rounded-lg flex items-center gap-2 hover:bg-primary-700 transition-colors"
        >
          <DocumentArrowDownIcon className="w-5 h-5" />
          下载脱敏文件
        </button>
      </div>

      {/* 统计信息 */}
      <div className="px-4 py-3 bg-green-50 dark:bg-green-900/30 border-b border-green-200 dark:border-green-800">
        <div className="flex items-center gap-4 text-sm">
          <span className="text-green-700 font-medium">
            ✓ 脱敏完成
          </span>
          <span className="text-ink-muted">
            共脱敏 <strong className="text-green-700">{redactionResult.redacted_count}</strong> 处敏感信息
          </span>
        </div>
      </div>

      {/* 对比内容 */}
      <div className="flex-1 overflow-hidden p-4">
        {mode === 'side-by-side' ? (
          <SideBySideView
            original={compareData.original_content}
            redacted={compareData.redacted_content}
          />
        ) : (
          <ChangesOnlyView changes={compareData.changes} />
        )}
      </div>
    </div>
  );
};

// 左右对比视图
interface SideBySideViewProps {
  original: string;
  redacted: string;
}

const SideBySideView: React.FC<SideBySideViewProps> = ({ original, redacted }) => {
  return (
    <div className="h-full grid grid-cols-2 gap-4">
      {/* 原始文档 */}
      <div className="flex flex-col h-full">
        <div className="px-4 py-2 bg-surface-tertiary rounded-t-lg border border-b-0 border-line">
          <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300">原始文档</h4>
        </div>
        <div className="flex-1 overflow-auto bg-white dark:bg-gray-800 rounded-b-lg border border-line dark:border-gray-700 p-4">
          <pre className="whitespace-pre-wrap font-serif text-ink leading-relaxed text-sm">
            {original}
          </pre>
        </div>
      </div>

      {/* 脱敏后文档 */}
      <div className="flex flex-col h-full">
        <div className="px-4 py-2 bg-green-100 rounded-t-lg border border-b-0 border-green-200">
          <h4 className="text-sm font-medium text-green-700">脱敏后文档</h4>
        </div>
        <div className="flex-1 overflow-auto bg-white rounded-b-lg border border-green-200 p-4">
          <pre className="whitespace-pre-wrap font-serif text-ink leading-relaxed text-sm">
            {redacted}
          </pre>
        </div>
      </div>
    </div>
  );
};

// 仅显示变更视图
interface ChangesOnlyViewProps {
  changes: Array<{
    original: string;
    replacement: string;
    count: number;
  }>;
}

const ChangesOnlyView: React.FC<ChangesOnlyViewProps> = ({ changes }) => {
  if (changes.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-ink-subtle">
        <p>没有变更记录</p>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg border border-line dark:border-gray-700 overflow-hidden">
      <table className="w-full">
        <thead>
          <tr className="bg-surface-secondary border-b border-line">
            <th className="px-4 py-3 text-left text-sm font-medium text-gray-700 dark:text-gray-300">
              原始内容
            </th>
            <th className="px-4 py-3 text-center text-sm font-medium text-gray-700 dark:text-gray-300 w-16">
              →
            </th>
            <th className="px-4 py-3 text-left text-sm font-medium text-gray-700 dark:text-gray-300">
              替换内容
            </th>
            <th className="px-4 py-3 text-center text-sm font-medium text-gray-700 dark:text-gray-300 w-20">
              次数
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
          {changes.map((change, index) => (
            <tr key={index} className="hover:bg-surface-secondary">
              <td className="px-4 py-3">
                <span className="px-2 py-1 bg-red-100 text-red-800 rounded text-sm font-mono">
                  {change.original}
                </span>
              </td>
              <td className="px-4 py-3 text-center text-ink-subtle">→</td>
              <td className="px-4 py-3">
                <span className="px-2 py-1 bg-green-100 text-green-800 rounded text-sm font-mono">
                  {change.replacement}
                </span>
              </td>
              <td className="px-4 py-3 text-center">
                <span className="inline-flex items-center justify-center w-8 h-8 bg-surface-tertiary text-gray-700 rounded-full text-sm font-medium">
                  {change.count}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export default CompareView;
