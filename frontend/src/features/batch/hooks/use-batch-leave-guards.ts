// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useEffect, useState } from 'react';
import { type Blocker } from 'react-router-dom';
import { type Step } from '../types';

/**
 * step4 审阅未保存草稿的离开守卫：路由 blocker 落盘 / beforeunload / pagehide。
 * 纯搬运自 useBatchWizard，行为与依赖数组保持不变；返回 showLeaveConfirmModal。
 */
export function useBatchLeaveGuards(
  step: Step,
  navigationBlocker: Blocker,
  flushCurrentReviewDraft: () => Promise<boolean>,
  reviewDraftDirtyRef: React.MutableRefObject<boolean>,
): boolean {
  const [leaveConfirmOpen, _setLeaveConfirmOpen] = useState(false);
  const showLeaveConfirmModal = leaveConfirmOpen || navigationBlocker.state === 'blocked';

  useEffect(() => {
    if (navigationBlocker.state !== 'blocked') return;
    void (async () => {
      const ok = await flushCurrentReviewDraft();
      if (ok && navigationBlocker.state === 'blocked') navigationBlocker.proceed();
    })();
  }, [flushCurrentReviewDraft, navigationBlocker]);

  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (step !== 4 || !reviewDraftDirtyRef.current) return;
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [step, reviewDraftDirtyRef]);

  useEffect(() => {
    if (step !== 4) return;
    const onPageHide = () => {
      void flushCurrentReviewDraft();
    };
    window.addEventListener('pagehide', onPageHide);
    return () => window.removeEventListener('pagehide', onPageHide);
  }, [flushCurrentReviewDraft, step]);

  return showLeaveConfirmModal;
}
