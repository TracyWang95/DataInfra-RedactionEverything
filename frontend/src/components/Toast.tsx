// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { AlertCircle, CheckCircle2, Info } from 'lucide-react';
import { Toaster, toast } from 'sonner';

type ToastType = 'success' | 'error' | 'info';

const TOAST_ICON: Record<ToastType, typeof CheckCircle2> = {
  success: CheckCircle2,
  error: AlertCircle,
  info: Info,
};

const TOAST_CLASS: Record<ToastType, string> = {
  success: 'border-[var(--success-border)] bg-[var(--surface-overlay)] text-foreground',
  error: 'border-[var(--error-border)] bg-[var(--surface-overlay)] text-foreground',
  info: 'border-[var(--info-border)] bg-[var(--surface-overlay)] text-foreground',
};

const TOAST_ICON_CLASS: Record<ToastType, string> = {
  success: 'text-[var(--success-foreground)]',
  error: 'text-[var(--error-foreground)]',
  info: 'text-[var(--info-foreground)]',
};

export function showToast(message: string, type: ToastType = 'info') {
  const Icon = TOAST_ICON[type];

  toast(message, {
    duration: 3500,
    className: [
      'rounded-2xl border px-4 py-3 shadow-[var(--shadow-lg)] backdrop-blur-xl',
      TOAST_CLASS[type],
    ].join(' '),
    descriptionClassName: 'text-sm text-muted-foreground',
    icon: <Icon className={TOAST_ICON_CLASS[type]} />,
  });
}

export function ToastContainer() {
  return (
    <Toaster
      position="bottom-right"
      theme="light"
      gap={10}
      closeButton
      richColors={false}
      toastOptions={{
        classNames: {
          toast:
            'group rounded-2xl border border-border bg-[var(--surface-overlay)] text-foreground shadow-[var(--shadow-lg)] backdrop-blur-xl',
          title: 'text-sm font-medium text-foreground',
          closeButton:
            'border-border bg-[var(--surface-control)] text-muted-foreground hover:bg-accent hover:text-foreground',
        },
      }}
    />
  );
}
