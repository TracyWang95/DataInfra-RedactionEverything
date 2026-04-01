import React from 'react';

interface PlaygroundLoadingOverlayProps {
  loadingMessage: string;
  isImageMode: boolean;
  elapsedSec: number;
}

export const PlaygroundLoadingOverlay: React.FC<PlaygroundLoadingOverlayProps> = ({
  loadingMessage,
  isImageMode,
  elapsedSec,
}) => (
  <div
    className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center"
    role="alertdialog"
    aria-busy="true"
    aria-label={loadingMessage || '处理中'}
  >
    <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl dark:shadow-gray-900/50 px-8 py-6 text-center max-w-sm">
      <div className="w-12 h-12 border-3 border-gray-600 dark:border-gray-400 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
      <p className="text-base font-medium text-[#1d1d1f] dark:text-gray-100 mb-1">{loadingMessage || '处理中...'}</p>
      {isImageMode ? (
        <>
          <p className="text-xs text-[#737373] dark:text-gray-400 leading-relaxed">
            仅勾选「文字 OCR+HaS」时才会跑 Paddle；只勾选「HaS Image」则不走 OCR。
            若含 OCR+HaS，<strong className="font-medium text-[#1d1d1f]">CPU 跑 Paddle 时常需 30–90 秒甚至更久</strong>
            ，等待较久为正常现象，请勿刷新。
          </p>
          {elapsedSec > 0 && (
            <p className="text-xs text-[#737373] dark:text-gray-400 mt-2 tabular-nums">已等待 {elapsedSec} 秒…</p>
          )}
        </>
      ) : (
        <p className="text-xs text-[#a3a3a3] dark:text-gray-500">处理中，请稍候</p>
      )}
    </div>
  </div>
);
