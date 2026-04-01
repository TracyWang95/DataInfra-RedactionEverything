import React from 'react';

interface Props {
  children: React.ReactNode;
  fallback?: React.ReactNode;
  onReset?: () => void;
}

interface State {
  hasError: boolean;
  error?: Error;
}

export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('ErrorBoundary caught:', error, info);
  }

  private handleReset = () => {
    this.props.onReset?.();
    this.setState({ hasError: false, error: undefined });
  };

  render() {
    if (this.state.hasError) {
      return this.props.fallback ?? (
        <div
          role="alert"
          aria-live="assertive"
          className="flex flex-col items-center justify-center p-12 text-center"
        >
          <p className="text-sm font-medium text-red-700 mb-2">页面出现异常</p>
          <p className="text-xs text-gray-500 mb-4 max-w-md break-all">
            {this.state.error?.message}
          </p>
          <button
            onClick={this.handleReset}
            className="px-4 py-2 text-sm rounded-lg bg-[#1d1d1f] text-white hover:bg-[#333]"
          >
            重试
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
