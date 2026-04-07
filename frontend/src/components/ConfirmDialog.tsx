// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useT } from '@/i18n';

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
  confirmText,
  cancelText,
  danger = false,
  onConfirm,
  onCancel,
}) => {
  const t = useT();

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => { if (!nextOpen) onCancel(); }}>
      <DialogContent className="max-w-md p-6 [&>button]:hidden">
        <DialogHeader className="flex flex-col gap-2 text-left">
          <DialogTitle className="text-base font-semibold tracking-[-0.02em]">{title}</DialogTitle>
          <DialogDescription className="whitespace-pre-line text-sm text-muted-foreground">
            {message}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2 pt-1 sm:justify-end">
          <Button type="button" onClick={onCancel} variant="outline">
            {cancelText ?? t('common.cancel')}
          </Button>
          <Button type="button" onClick={onConfirm} variant={danger ? 'destructive' : 'default'}>
            {confirmText ?? t('common.confirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
