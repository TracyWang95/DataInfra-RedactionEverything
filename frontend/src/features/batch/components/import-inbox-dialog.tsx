// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useCallback, useEffect, useMemo, useState } from 'react';
import { FolderInput, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
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

interface InboxItem {
  name: string;
  size: number;
  mtime: string;
}

const BATCH_SIZE = 500;

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** 内网落地目录导入（第五段方案一）：运维 scp 文件到服务器 inbox，
 * 这里一键登记进当前批量任务（服务端本地 move，零 HTTP 传输）。 */
export function ImportInboxDialog({
  jobId,
  onImported,
}: {
  jobId: string | null;
  onImported: () => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<InboxItem[]>([]);
  const [inboxPath, setInboxPath] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetch('/api/v1/files/import-inbox');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { path: string; items: InboxItem[] };
      setItems(data.items ?? []);
      setInboxPath(data.path ?? '');
      setSelected(new Set((data.items ?? []).map((item) => item.name)));
    } catch (err) {
      setError(localizeErrorMessage(err, 'batchWizard.inbox.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      setSummary(null);
      setProgress(null);
      void load();
    }
  }, [open, load]);

  const allSelected = items.length > 0 && selected.size === items.length;
  const totalSize = useMemo(
    () => items.filter((item) => selected.has(item.name)).reduce((sum, item) => sum + item.size, 0),
    [items, selected],
  );

  async function handleImport() {
    const names = items.filter((item) => selected.has(item.name)).map((item) => item.name);
    if (!names.length || importing) return;
    setImporting(true);
    setError(null);
    setSummary(null);
    let imported = 0;
    let failed = 0;
    const failReasons: string[] = [];
    try {
      for (let i = 0; i < names.length; i += BATCH_SIZE) {
        const batch = names.slice(i, i + BATCH_SIZE);
        setProgress({ done: i, total: names.length });
        const res = await authFetch('/api/v1/files/import-inbox', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filenames: batch, job_id: jobId ?? undefined }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as {
          imported: { name: string }[];
          failed: { name: string; reason: string }[];
        };
        imported += data.imported.length;
        failed += data.failed.length;
        for (const f of data.failed.slice(0, 3)) {
          if (failReasons.length < 3) failReasons.push(`${f.name}: ${f.reason}`);
        }
      }
      setProgress({ done: names.length, total: names.length });
      setSummary(
        t('batchWizard.inbox.done')
          .replace('{ok}', String(imported))
          .replace('{fail}', String(failed)) +
          (failReasons.length ? ` ${failReasons.join('；')}` : ''),
      );
      if (imported > 0) onImported();
      await load();
    } catch (err) {
      setError(localizeErrorMessage(err, 'batchWizard.inbox.importFailed'));
    } finally {
      setImporting(false);
    }
  }

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-8"
        onClick={() => setOpen(true)}
        data-testid="import-inbox-open"
      >
        <FolderInput className="mr-1.5 size-3.5" />
        {t('batchWizard.inbox.button')}
      </Button>
      <Dialog open={open} onOpenChange={(next) => !importing && setOpen(next)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{t('batchWizard.inbox.title')}</DialogTitle>
            <DialogDescription className="break-all">
              {t('batchWizard.inbox.description').replace('{path}', inboxPath || '…')}
            </DialogDescription>
          </DialogHeader>

          <div className="flex items-center justify-between gap-2">
            <label className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={allSelected}
                onCheckedChange={(checked) =>
                  setSelected(checked ? new Set(items.map((item) => item.name)) : new Set())
                }
                data-testid="import-inbox-select-all"
              />
              {t('batchWizard.inbox.selectAll')}
              <span className="text-xs text-muted-foreground tabular-nums">
                {selected.size}/{items.length} · {formatSize(totalSize)}
              </span>
            </label>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7"
              disabled={loading || importing}
              onClick={() => void load()}
            >
              <RefreshCw className={loading ? 'size-3.5 animate-spin' : 'size-3.5'} />
            </Button>
          </div>

          {error && <p className="text-sm text-[var(--error-foreground)]">{error}</p>}
          {summary && <p className="text-sm text-[var(--success-foreground)]">{summary}</p>}

          <div className="max-h-72 space-y-1 overflow-y-auto" data-testid="import-inbox-list">
            {items.length === 0 && !loading && (
              <p className="py-8 text-center text-sm text-muted-foreground">
                {t('batchWizard.inbox.empty')}
              </p>
            )}
            {items.slice(0, 500).map((item) => (
              <label
                key={item.name}
                className="flex cursor-pointer items-center justify-between gap-3 rounded-lg border border-border/70 px-3 py-1.5 text-sm"
              >
                <span className="flex min-w-0 items-center gap-2">
                  <Checkbox
                    checked={selected.has(item.name)}
                    onCheckedChange={(checked) =>
                      setSelected((prev) => {
                        const next = new Set(prev);
                        if (checked) next.add(item.name);
                        else next.delete(item.name);
                        return next;
                      })
                    }
                  />
                  <span className="truncate">{item.name}</span>
                </span>
                <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                  {formatSize(item.size)}
                </span>
              </label>
            ))}
            {items.length > 500 && (
              <p className="py-1 text-center text-xs text-muted-foreground">
                {t('batchWizard.inbox.moreItems').replace('{n}', String(items.length - 500))}
              </p>
            )}
          </div>

          <div className="flex items-center justify-end gap-2">
            {progress && (
              <span className="text-xs text-muted-foreground tabular-nums">
                {progress.done}/{progress.total}
              </span>
            )}
            <Button
              type="button"
              disabled={selected.size === 0 || importing || loading}
              onClick={() => void handleImport()}
              data-testid="import-inbox-submit"
            >
              {importing
                ? t('batchWizard.inbox.importing')
                : t('batchWizard.inbox.importSelected').replace('{n}', String(selected.size))}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
