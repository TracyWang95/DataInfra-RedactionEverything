// Copyright 2026 DataInfra-RedactionEverything Contributors

import { showToast } from '@/components/Toast';

/**
 * 任务完成通知（W2-2）：万级批量跑十几分钟，用户不会盯屏。
 * 页内永远 toast；页签隐藏时追加系统通知（权限需在用户手势里预请求）。
 */

/** 纯函数：活跃数从 >0 归 0 即视为该阶段完成（供 vitest 与调用方复用）。 */
export function phaseJustFinished(prevActive: number, nextActive: number): boolean {
  return prevActive > 0 && nextActive === 0;
}

/** 在用户手势上下文（如点击「开始识别」）里预请求系统通知权限。 */
export function ensureNotifyPermission(): void {
  try {
    if (typeof window === 'undefined' || !('Notification' in window)) return;
    if (Notification.permission === 'default') {
      void Notification.requestPermission();
    }
  } catch {
    /* 通知权限失败不影响业务 */
  }
}

/** 完成通知：toast 常显；页签隐藏时再发系统通知。 */
export function notifyDone(title: string, body?: string): void {
  showToast(body ? `${title}：${body}` : title, 'success');
  try {
    if (typeof document === 'undefined' || document.visibilityState === 'visible') return;
    if (typeof window === 'undefined' || !('Notification' in window)) return;
    if (Notification.permission === 'granted') {
      new Notification(title, body ? { body } : undefined);
    }
  } catch {
    /* 系统通知失败静默，toast 已兜底 */
  }
}
