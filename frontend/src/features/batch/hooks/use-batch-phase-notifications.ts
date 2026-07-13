// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useEffect, useMemo, useRef } from 'react';
import { t } from '@/i18n';
import { notifyDone, phaseJustFinished } from '@/lib/notifications';
import { type BatchRow, type Step } from '../types';

/**
 * 阶段完成通知（W2-2）：识别全部完成 / 成品全部生成的活跃数 >0 → 0 翻转通知。
 * 纯搬运自 useBatchWizard，行为与依赖数组保持不变。
 */
export function useBatchPhaseNotifications(rows: BatchRow[], step: Step, isPreviewMode: boolean) {
  // 识别全部完成通知（W2-2）：analyzing/pending 活跃数 >0 → 0 的翻转，
  // 仅在识别步（step3）响，避免 step2 清空队列误报。
  const recognitionActiveCount = useMemo(
    () =>
      rows.filter((row) => row.analyzeStatus === 'analyzing' || row.analyzeStatus === 'pending')
        .length,
    [rows],
  );

  // 成品全部生成通知：批量确认后 review_approved/redacting 归零=可进导出
  //（万级要几分钟，用户多半已切走页签——PM 5188 份实战反馈）。
  const settlingActiveCount = useMemo(
    () =>
      rows.filter(
        (row) => row.analyzeStatus === 'review_approved' || row.analyzeStatus === 'redacting',
      ).length,
    [rows],
  );
  const prevSettlingActiveRef = useRef(0);
  useEffect(() => {
    const prev = prevSettlingActiveRef.current;
    prevSettlingActiveRef.current = settlingActiveCount;
    if (step === 4 && !isPreviewMode && phaseJustFinished(prev, settlingActiveCount)) {
      notifyDone(t('notify.outputsReady'));
    }
  }, [settlingActiveCount, step, isPreviewMode, t]);
  const prevRecognitionActiveRef = useRef(0);
  useEffect(() => {
    const prev = prevRecognitionActiveRef.current;
    prevRecognitionActiveRef.current = recognitionActiveCount;
    if (step === 3 && !isPreviewMode && phaseJustFinished(prev, recognitionActiveCount)) {
      notifyDone(t('notify.recognitionDone'), t('notify.recognitionDoneBody').replace('{n}', String(rows.length)));
    }
  }, [recognitionActiveCount, step, isPreviewMode, rows.length, t]);
}
