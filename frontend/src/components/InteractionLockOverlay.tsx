// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useRef } from 'react';
import { createPortal } from 'react-dom';
import { useInteractionLock } from '@/hooks/use-interaction-lock';

interface InteractionLockOverlayProps {
  active: boolean;
  label?: string;
  testId?: string;
}

export function InteractionLockOverlay({
  active,
  label = 'Processing',
  testId = 'interaction-lock-overlay',
}: InteractionLockOverlayProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  useInteractionLock(active, panelRef);

  if (!active) return null;

  const overlay = (
    <div
      className="fixed inset-0 z-40 flex cursor-wait items-center justify-center bg-background/60 backdrop-blur-[2px]"
      role="status"
      aria-busy="true"
      aria-live="polite"
      aria-label={label}
      data-testid={testId}
      style={{ pointerEvents: 'auto' }}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        className="inline-flex min-h-14 min-w-44 items-center justify-center gap-3 rounded-2xl border border-border/70 bg-[var(--surface-overlay)] px-4 py-3 text-sm font-medium text-foreground shadow-[var(--shadow-floating)] outline-none"
      >
        <span className="size-5 animate-spin rounded-full border-2 border-muted border-t-foreground" />
        <span className="whitespace-nowrap">{label}</span>
      </div>
    </div>
  );

  if (typeof document === 'undefined') return overlay;
  return createPortal(overlay, document.body);
}
