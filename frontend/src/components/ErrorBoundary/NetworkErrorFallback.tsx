import React from 'react';

export interface NetworkErrorFallbackProps {
  error: Error;
  onRetry?: () => void;
}

/** Returns true when the error looks like a network / fetch failure. */
export function isNetworkError(error: Error): boolean {
  const msg = error.message.toLowerCase();
  return (
    error.name === 'TypeError' && msg.includes('fetch') ||
    msg.includes('network') ||
    msg.includes('failed to fetch') ||
    msg.includes('networkerror') ||
    msg.includes('net::')
  );
}

/** Returns true when the error indicates an authentication / authorisation failure. */
export function isAuthError(error: Error): boolean {
  const msg = error.message.toLowerCase();
  return (
    msg.includes('401') ||
    msg.includes('403') ||
    msg.includes('unauthorized') ||
    msg.includes('unauthenticated') ||
    msg.includes('token') && msg.includes('expired')
  );
}

/**
 * A fallback UI that distinguishes network errors from auth errors.
 *
 * - Network errors: shows a "网络连接失败" message with a retry button.
 * - Auth errors:    shows a "认证已过期" message with a login redirect button.
 * - Other errors:   falls back to a generic message.
 */
export const NetworkErrorFallback: React.FC<NetworkErrorFallbackProps> = ({
  error,
  onRetry,
}) => {
  if (isAuthError(error)) {
    return (
      <div
        role="alert"
        aria-live="assertive"
        className="flex flex-col items-center justify-center p-12 text-center"
      >
        <p className="text-sm font-medium text-red-700 mb-2">认证已过期</p>
        <p className="text-xs text-gray-500 mb-4 max-w-md">
          您的登录凭证已失效，请重新登录。
        </p>
        <button
          onClick={() => {
            window.location.href = '/login';
          }}
          className="px-4 py-2 text-sm rounded-lg bg-[#1d1d1f] text-white hover:bg-[#333]"
        >
          前往登录
        </button>
      </div>
    );
  }

  if (isNetworkError(error)) {
    return (
      <div
        role="alert"
        aria-live="assertive"
        className="flex flex-col items-center justify-center p-12 text-center"
      >
        <p className="text-sm font-medium text-red-700 mb-2">网络连接失败</p>
        <p className="text-xs text-gray-500 mb-4 max-w-md">
          无法连接到服务器，请检查您的网络后重试。
        </p>
        {onRetry && (
          <button
            onClick={onRetry}
            className="px-4 py-2 text-sm rounded-lg bg-[#1d1d1f] text-white hover:bg-[#333]"
          >
            重试
          </button>
        )}
      </div>
    );
  }

  // Generic fallback for unrecognised error types
  return (
    <div
      role="alert"
      aria-live="assertive"
      className="flex flex-col items-center justify-center p-12 text-center"
    >
      <p className="text-sm font-medium text-red-700 mb-2">页面出现异常</p>
      <p className="text-xs text-gray-500 mb-4 max-w-md break-all">
        {error.message}
      </p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="px-4 py-2 text-sm rounded-lg bg-[#1d1d1f] text-white hover:bg-[#333]"
        >
          重试
        </button>
      )}
    </div>
  );
};
