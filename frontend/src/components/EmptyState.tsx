import React from 'react';

interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: { label: string; onClick: () => void };
}

export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-5 py-20 animate-fade-in">
      <div className="flex h-16 w-16 items-center justify-center rounded-[20px] border border-border/70 bg-card shadow-[0_20px_44px_-30px_rgba(15,23,42,0.26)]">
        {icon || (
          <svg className="w-8 h-8 text-primary/40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4"
            />
          </svg>
        )}
      </div>
      <div className="max-w-xs text-center">
        <p className="mb-1 text-sm font-medium text-foreground/80">{title}</p>
        {description && (
          <p className="text-xs text-muted-foreground">{description}</p>
        )}
      </div>
      {action && (
        <button
          type="button"
          onClick={action.onClick}
          className="rounded-xl border border-input bg-card px-4 py-2 text-xs font-medium shadow-[0_16px_34px_-26px_rgba(15,23,42,0.22)] transition-all hover:-translate-y-0.5 hover:border-foreground/20"
        >
          {action.label}
        </button>
      )}
    </div>
  );
}

export default EmptyState;
