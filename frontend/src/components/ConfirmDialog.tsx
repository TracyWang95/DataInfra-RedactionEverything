import React, { useEffect, useRef } from 'react';
import { Button } from '@/components/ui/button';

interface Props {
  open: boolean;
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export const ConfirmDialog: React.FC<Props> = ({
  open,
  title,
  message,
  confirmText = '确认',
  cancelText = '取消',
  danger = false,
  onConfirm,
  onCancel,
}) => {
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (open) cancelRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onCancel} />
      <div className="relative w-full max-w-md space-y-5 rounded-[24px] border border-border/80 bg-popover p-6 shadow-[0_32px_90px_-40px_rgba(15,23,42,0.45)] backdrop-blur-2xl animate-scale-in">
        <h3 className="text-base font-semibold tracking-[-0.02em]">{title}</h3>
        <p className="text-sm text-muted-foreground whitespace-pre-line">{message}</p>
        <div className="flex justify-end gap-2 pt-1">
          <Button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            variant="outline"
          >
            {cancelText}
          </Button>
          <Button
            type="button"
            onClick={onConfirm}
            variant={danger ? 'destructive' : 'default'}
          >
            {confirmText}
          </Button>
        </div>
      </div>
    </div>
  );
};
