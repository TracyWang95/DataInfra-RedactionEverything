// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '../../test-utils';
import { ErrorBoundary } from '@/components/ErrorBoundary';

// Suppress console.error from React error boundary internals during tests
beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

function ThrowingChild({ message }: { message: string }): never {
  throw new Error(message);
}

function GoodChild() {
  return <div>All is well</div>;
}

describe('ErrorBoundary', () => {
  it('renders children when no error occurs', () => {
    render(
      <ErrorBoundary>
        <GoodChild />
      </ErrorBoundary>,
    );
    expect(screen.getByText('All is well')).toBeInTheDocument();
  });

  it('renders default fallback UI when child throws', () => {
    render(
      <ErrorBoundary>
        <ThrowingChild message="Something broke" />
      </ErrorBoundary>,
    );
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText('Something broke')).toBeInTheDocument();
  });

  it('renders custom fallback when provided', () => {
    render(
      <ErrorBoundary fallback={<div>Custom error page</div>}>
        <ThrowingChild message="fail" />
      </ErrorBoundary>,
    );
    expect(screen.getByText('Custom error page')).toBeInTheDocument();
  });

  it('calls onReset and recovers when retry button is clicked', async () => {
    const onReset = vi.fn();
    const { rerender } = render(
      <ErrorBoundary onReset={onReset}>
        <ThrowingChild message="boom" />
      </ErrorBoundary>,
    );

    // Should be in error state
    expect(screen.getByRole('alert')).toBeInTheDocument();

    // Find and click the retry button (the button in default fallback)
    const buttons = screen.getAllByRole('button');
    const retryButton = buttons.find((b) => b.textContent);
    expect(retryButton).toBeTruthy();
    retryButton!.click();

    expect(onReset).toHaveBeenCalledTimes(1);

    // After reset, re-render with a non-throwing child to confirm recovery
    rerender(
      <ErrorBoundary onReset={onReset}>
        <GoodChild />
      </ErrorBoundary>,
    );
    expect(screen.getByText('All is well')).toBeInTheDocument();
  });
});
