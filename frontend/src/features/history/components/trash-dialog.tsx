// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useCallback, useEffect, useState } from 'react';
import { Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useT } from '@/i18n';
import { authFetch } from '@/services/api-client';
import { localizeErrorMessage } from '@/utils/localizeError';

interface TrashItem {
  file_id: string;
  original_filename?: string | null;
  file_type?: string | null;
  deleted_at?: string | null;
}

/** 回收站（R1-4）：软删文件列表 + 还原/彻底删除。自足组件，关闭后由调用方刷新列表。 */
export function TrashRecycleDialog({ onChanged }: { onChanged?: () => void }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<TrashItem[]>([]);
  const [retentionDays, setRetentionDays] = useState(7);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mutated, setMutated] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await authFetch('/api/v1/files/trash');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { items: TrashItem[]; retention_days: number };
      setItems(data.items ?? []);
      setRetentionDays(data.retention_days ?? 7);
    } catch (err) {
      setError(localizeErrorMessage(err, 'history.trash.loadFailed'));
    }
  }, []);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  async function act(fileId: string, action: 'restore' | 'purge') {
    setBusyId(fileId);
    setError(null);
    try {
      const res =
        action === 'restore'
          ? await authFetch(`/api/v1/files/${encodeURIComponent(fileId)}/restore`, {
              method: 'POST',
            })
          : await authFetch(`/api/v1/files/${encodeURIComponent(fileId)}?purge=true`, {
              method: 'DELETE',
            });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setMutated(true);
      await load();
    } catch (err) {
      setError(localizeErrorMessage(err, 'history.trash.actionFailed'));
    } finally {
      setBusyId(null);
    }
  }

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next && mutated) {
      setMutated(false);
      onChanged?.();
    }
  }

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className="h-8"
        onClick={() => setOpen(true)}
        data-testid="history-trash-open"
      >
        <Trash2 className="mr-1.5 size-3.5" />
        {t('history.trash.title')}
      </Button>
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>{t('history.trash.title')}</DialogTitle>
            <DialogDescription>
              {t('history.trash.description').replace('{days}', String(retentionDays))}
            </DialogDescription>
          </DialogHeader>
          {error && <p className="text-sm text-[var(--error-foreground)]">{error}</p>}
          <div className="max-h-80 space-y-1.5 overflow-y-auto" data-testid="history-trash-list">
            {items.length === 0 && (
              <p className="py-8 text-center text-sm text-muted-foreground">
                {t('history.trash.empty')}
              </p>
            )}
            {items.map((item) => (
              <div
                key={item.file_id}
                className="flex items-center justify-between gap-3 rounded-lg border border-border/70 px-3 py-2"
                data-testid={`trash-row-${item.file_id}`}
              >
                <div className="min-w-0">
                  <div className="truncate text-sm">{item.original_filename || item.file_id}</div>
                  <div className="text-xs text-muted-foreground">
                    {(item.deleted_at || '').slice(0, 19).replace('T', ' ')}
                  </div>
                </div>
                <div className="flex shrink-0 gap-1.5">
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 px-2 text-xs"
                    disabled={busyId === item.file_id}
                    onClick={() => void act(item.file_id, 'restore')}
                    data-testid={`trash-restore-${item.file_id}`}
                  >
                    {t('history.trash.restore')}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 px-2 text-xs text-[var(--error-foreground)]"
                    disabled={busyId === item.file_id}
                    onClick={() => void act(item.file_id, 'purge')}
                    data-testid={`trash-purge-${item.file_id}`}
                  >
                    {t('history.trash.purge')}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
