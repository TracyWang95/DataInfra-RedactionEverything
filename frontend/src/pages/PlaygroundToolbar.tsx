import React from 'react';

export interface PlaygroundToolbarProps {
  fileInfo: { filename?: string } | null;
  isImageMode: boolean;
  canUndo: boolean;
  canRedo: boolean;
  handleUndo: () => void;
  handleRedo: () => void;
  handleReset: () => void;
  // Popout (image mode only)
  onPopoutClick?: () => void;
  // Hint text
  hintText: string;
}

export const PlaygroundToolbar: React.FC<PlaygroundToolbarProps> = ({
  fileInfo,
  isImageMode,
  canUndo,
  canRedo,
  handleUndo,
  handleRedo,
  handleReset,
  onPopoutClick,
  hintText,
}) => {
  return (
    <div className="px-3 py-2 border-b border-[#f0f0f0] flex items-center justify-between bg-[#fafafa] dark:bg-gray-900 flex-shrink-0">
      <div className="min-w-0 flex-1">
        <h3 className="font-semibold text-[#1d1d1f] text-sm truncate">{fileInfo?.filename}</h3>
        <p className="text-xs text-[#737373]">{hintText}</p>
      </div>
      <div className="flex items-center gap-2 flex-shrink-0">
        {isImageMode && onPopoutClick && (
          <button
            type="button"
            onClick={onPopoutClick}
            className="text-xs text-[#737373] hover:text-[#1d1d1f] px-2 py-1 rounded hover:bg-[#f5f5f5]"
            title="在新窗口中拉框标注"
            aria-label="在新窗口中拉框标注"
          >
            新窗口标注
          </button>
        )}
        <button
          onClick={handleUndo}
          disabled={!canUndo}
          className="text-xs px-2 py-1 rounded hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed"
          title="撤销 (Ctrl+Z)"
          aria-label="撤销"
        >
          ↩ 撤销
        </button>
        <button
          onClick={handleRedo}
          disabled={!canRedo}
          className="text-xs px-2 py-1 rounded hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed"
          title="重做 (Ctrl+Y)"
          aria-label="重做"
        >
          ↪ 重做
        </button>
        <button onClick={handleReset} className="text-xs text-[#737373] hover:text-[#1d1d1f]">重新上传</button>
      </div>
    </div>
  );
};
