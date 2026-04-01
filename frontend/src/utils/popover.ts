/**
 * 通用弹窗/popover 位置钳制工具
 * 从 Playground.tsx 和 Batch.tsx 中的重复代码提取
 */

/**
 * 将 popover 位置限制在画布/视口范围内
 */
export function clampPopoverInCanvas(
  x: number,
  y: number,
  popWidth: number,
  popHeight: number,
  canvasRect: { left: number; top: number; width: number; height: number }
): { x: number; y: number } {
  const padding = 8;
  let clampedX = x;
  let clampedY = y;

  // 右侧溢出
  if (clampedX + popWidth > canvasRect.left + canvasRect.width - padding) {
    clampedX = canvasRect.left + canvasRect.width - popWidth - padding;
  }
  // 左侧溢出
  if (clampedX < canvasRect.left + padding) {
    clampedX = canvasRect.left + padding;
  }
  // 底部溢出
  if (clampedY + popHeight > canvasRect.top + canvasRect.height - padding) {
    clampedY = canvasRect.top + canvasRect.height - popHeight - padding;
  }
  // 顶部溢出
  if (clampedY < canvasRect.top + padding) {
    clampedY = canvasRect.top + padding;
  }

  return { x: clampedX, y: clampedY };
}

/**
 * 区分性错误消息
 */
export function classifyError(error: unknown): {
  message: string;
  isNetwork: boolean;
  isAuth: boolean;
  isServer: boolean;
} {
  if (error instanceof TypeError && error.message === 'Failed to fetch') {
    return { message: '网络连接失败，请检查网络设置', isNetwork: true, isAuth: false, isServer: false };
  }
  if (error instanceof Response || (error && typeof error === 'object' && 'status' in error)) {
    const status = (error as { status: number }).status;
    if (status === 401 || status === 403) {
      return { message: '认证失败，请重新登录', isNetwork: false, isAuth: true, isServer: false };
    }
    if (status >= 500) {
      return { message: '服务器内部错误，请稍后重试', isNetwork: false, isAuth: false, isServer: true };
    }
  }
  if (error instanceof Error) {
    return { message: error.message, isNetwork: false, isAuth: false, isServer: false };
  }
  return { message: '操作失败', isNetwork: false, isAuth: false, isServer: false };
}
