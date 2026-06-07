// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { type RefObject, useEffect } from 'react';

type LockSnapshot = {
  root: HTMLElement | null;
  rootAriaHidden: string | null;
  rootWasInert: boolean;
  bodyOverflow: string;
  bodyPointerEvents: string;
  bodyTouchAction: string;
  activeElement: HTMLElement | null;
};

let lockDepth = 0;
let snapshot: LockSnapshot | null = null;

function captureSnapshot(): LockSnapshot {
  const root = document.getElementById('root');
  return {
    root,
    rootAriaHidden: root ? root.getAttribute('aria-hidden') : null,
    rootWasInert: root?.hasAttribute('inert') ?? false,
    bodyOverflow: document.body.style.overflow,
    bodyPointerEvents: document.body.style.pointerEvents,
    bodyTouchAction: document.body.style.touchAction,
    activeElement: document.activeElement instanceof HTMLElement ? document.activeElement : null,
  };
}

function applyLock(lockSnapshot: LockSnapshot) {
  lockSnapshot.root?.setAttribute('inert', '');
  lockSnapshot.root?.setAttribute('aria-hidden', 'true');
  document.body.style.overflow = 'hidden';
  document.body.style.pointerEvents = 'none';
  document.body.style.touchAction = 'none';
}

function restoreLock(lockSnapshot: LockSnapshot) {
  document.body.style.overflow = lockSnapshot.bodyOverflow;
  document.body.style.pointerEvents = lockSnapshot.bodyPointerEvents;
  document.body.style.touchAction = lockSnapshot.bodyTouchAction;

  const { root } = lockSnapshot;
  if (root) {
    if (!lockSnapshot.rootWasInert) root.removeAttribute('inert');
    if (lockSnapshot.rootAriaHidden === null) root.removeAttribute('aria-hidden');
    else root.setAttribute('aria-hidden', lockSnapshot.rootAriaHidden);
  }

  if (lockSnapshot.activeElement && document.contains(lockSnapshot.activeElement)) {
    lockSnapshot.activeElement.focus();
  }
}

export function useInteractionLock<T extends HTMLElement>(
  active: boolean,
  panelRef: RefObject<T | null>,
): void {
  useEffect(() => {
    if (!active || typeof document === 'undefined') return;

    if (lockDepth === 0) {
      snapshot = captureSnapshot();
      applyLock(snapshot);
    }
    lockDepth += 1;
    panelRef.current?.focus();

    return () => {
      lockDepth = Math.max(0, lockDepth - 1);
      if (lockDepth === 0 && snapshot) {
        restoreLock(snapshot);
        snapshot = null;
      }
    };
  }, [active, panelRef]);
}
