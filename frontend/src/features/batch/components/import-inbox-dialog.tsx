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
  const [tab, setTab] = useState<'inbox' | 'sftp'>('inbox');

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
              {tab === 'inbox'
                ? t('batchWizard.inbox.description').replace('{path}', inboxPath || '…')
                : t('batchWizard.sftp.description')}
            </DialogDescription>
          </DialogHeader>

          <div className="flex gap-1 rounded-lg border border-border/70 bg-muted/40 p-1 text-sm">
            {(['inbox', 'sftp'] as const).map((key) => (
              <button
                key={key}
                type="button"
                className={
                  'flex-1 rounded-md px-3 py-1 ' +
                  (tab === key ? 'bg-background font-medium shadow-sm' : 'text-muted-foreground')
                }
                onClick={() => setTab(key)}
                data-testid={`import-tab-${key}`}
              >
                {key === 'inbox' ? t('batchWizard.inbox.tabLocal') : t('batchWizard.sftp.tab')}
              </button>
            ))}
          </div>

          {tab === 'sftp' && <SftpPanel jobId={jobId} onImported={onImported} />}

          {tab === 'inbox' && (
          <>
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
          </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

interface SftpSource {
  source_id: string;
  name: string;
  host: string;
  root_path: string;
}

/** 远程 SFTP 拉取面板（第五段方案二）：选源→输路径→列文件→勾选→拉取。 */
function SftpPanel({ jobId, onImported }: { jobId: string | null; onImported: () => void }) {
  const t = useT();
  const [sources, setSources] = useState<SftpSource[]>([]);
  const [sourceId, setSourceId] = useState('');
  const [path, setPath] = useState('');
  const [files, setFiles] = useState<{ name: string; size: number }[]>([]);
  const [dirs, setDirs] = useState<string[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<'browse' | 'pull' | 'save' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ name: '', host: '', port: '22', username: '', password: '', root_path: '/' });

  const loadSources = useCallback(async () => {
    try {
      const res = await authFetch('/api/v1/files/import-sftp/sources');
      if (!res.ok) return;
      const data = (await res.json()) as SftpSource[];
      setSources(data);
      if (data.length && !data.some((s) => s.source_id === sourceId)) {
        setSourceId(data[0].source_id);
      }
      if (!data.length) setShowAdd(true);
    } catch {
      /* 空态提示兜底 */
    }
  }, [sourceId]);

  useEffect(() => {
    void loadSources();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSaveSource() {
    setBusy('save');
    setError(null);
    try {
      const res = await authFetch('/api/v1/files/import-sftp/sources', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...form, port: Number(form.port) || 22 }),
      });
      const data = (await res.json().catch(() => null)) as { message?: string; source_id?: string } | null;
      if (!res.ok) throw new Error(data?.message || `HTTP ${res.status}`);
      setShowAdd(false);
      setForm({ name: '', host: '', port: '22', username: '', password: '', root_path: '/' });
      await loadSources();
      if (data?.source_id) setSourceId(data.source_id);
    } catch (err) {
      setError(localizeErrorMessage(err, 'batchWizard.sftp.saveFailed'));
    } finally {
      setBusy(null);
    }
  }

  async function handleBrowse(nextPath?: string) {
    if (!sourceId) return;
    const target = nextPath ?? path;
    setBusy('browse');
    setError(null);
    try {
      const res = await authFetch(
        `/api/v1/files/import-sftp/browse?source_id=${encodeURIComponent(sourceId)}&path=${encodeURIComponent(target)}`,
      );
      const data = (await res.json().catch(() => null)) as
        | { message?: string; path?: string; files?: { name: string; size: number }[]; dirs?: string[] }
        | null;
      if (!res.ok) throw new Error(data?.message || `HTTP ${res.status}`);
      setPath(target);
      setFiles(data?.files ?? []);
      setDirs(data?.dirs ?? []);
      setSelected(new Set((data?.files ?? []).map((f) => f.name)));
    } catch (err) {
      setError(localizeErrorMessage(err, 'batchWizard.sftp.browseFailed'));
    } finally {
      setBusy(null);
    }
  }

  async function handlePull() {
    const names = files.filter((f) => selected.has(f.name)).map((f) => f.name);
    if (!names.length || busy) return;
    setBusy('pull');
    setError(null);
    setSummary(null);
    let ok = 0;
    let fail = 0;
    try {
      for (let i = 0; i < names.length; i += 100) {
        const res = await authFetch('/api/v1/files/import-sftp/pull', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            source_id: sourceId,
            names: names.slice(i, i + 100),
            path,
            job_id: jobId ?? undefined,
          }),
        });
        const data = (await res.json().catch(() => null)) as
          | { message?: string; imported?: unknown[]; failed?: unknown[] }
          | null;
        if (!res.ok) throw new Error(data?.message || `HTTP ${res.status}`);
        ok += data?.imported?.length ?? 0;
        fail += data?.failed?.length ?? 0;
      }
      setSummary(
        t('batchWizard.inbox.done').replace('{ok}', String(ok)).replace('{fail}', String(fail)),
      );
      if (ok > 0) onImported();
      await handleBrowse();
    } catch (err) {
      setError(localizeErrorMessage(err, 'batchWizard.sftp.pullFailed'));
    } finally {
      setBusy(null);
    }
  }

  const inputCls =
    'h-8 rounded-lg border border-border bg-background px-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]';

  return (
    <div className="space-y-2.5" data-testid="sftp-panel">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={sourceId}
          onChange={(event) => setSourceId(event.target.value)}
          className={inputCls}
          data-testid="sftp-source-select"
        >
          {sources.map((s) => (
            <option key={s.source_id} value={s.source_id}>
              {s.name}（{s.host}）
            </option>
          ))}
          {!sources.length && <option value="">{t('batchWizard.sftp.noSources')}</option>}
        </select>
        <Button type="button" variant="outline" size="sm" className="h-8" onClick={() => setShowAdd((v) => !v)}>
          {t('batchWizard.sftp.addSource')}
        </Button>
        <input
          value={path}
          onChange={(event) => setPath(event.target.value)}
          placeholder={t('batchWizard.sftp.pathPlaceholder')}
          className={inputCls + ' min-w-40 flex-1'}
          data-testid="sftp-path-input"
        />
        <Button
          type="button"
          size="sm"
          className="h-8"
          disabled={!sourceId || busy !== null}
          onClick={() => void handleBrowse()}
          data-testid="sftp-browse"
        >
          {busy === 'browse' ? t('batchWizard.sftp.browsing') : t('batchWizard.sftp.browse')}
        </Button>
      </div>

      {showAdd && (
        <div className="grid grid-cols-2 gap-2 rounded-lg border border-border/70 p-3 sm:grid-cols-3">
          {(
            [
              ['name', t('batchWizard.sftp.fieldName')],
              ['host', 'Host'],
              ['port', 'Port'],
              ['username', t('batchWizard.sftp.fieldUser')],
              ['password', t('batchWizard.sftp.fieldPassword')],
              ['root_path', t('batchWizard.sftp.fieldRoot')],
            ] as const
          ).map(([key, label]) => (
            <input
              key={key}
              type={key === 'password' ? 'password' : 'text'}
              value={form[key]}
              onChange={(event) => setForm((prev) => ({ ...prev, [key]: event.target.value }))}
              placeholder={label}
              className={inputCls}
              data-testid={`sftp-field-${key}`}
            />
          ))}
          <Button
            type="button"
            size="sm"
            className="h-8 sm:col-span-3"
            disabled={busy !== null || !form.name || !form.host || !form.username || !form.password}
            onClick={() => void handleSaveSource()}
            data-testid="sftp-save-source"
          >
            {busy === 'save' ? t('batchWizard.sftp.saving') : t('batchWizard.sftp.saveSource')}
          </Button>
        </div>
      )}

      {error && <p className="text-sm text-[var(--error-foreground)]">{error}</p>}
      {summary && <p className="text-sm text-[var(--success-foreground)]">{summary}</p>}

      {dirs.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {path && (
            <Button type="button" variant="outline" size="sm" className="h-7 px-2 text-xs"
              onClick={() => void handleBrowse(path.split('/').slice(0, -1).join('/'))}>
              ..
            </Button>
          )}
          {dirs.slice(0, 30).map((d) => (
            <Button key={d} type="button" variant="outline" size="sm" className="h-7 px-2 text-xs"
              onClick={() => void handleBrowse(path ? `${path}/${d}` : d)}>
              {d}/
            </Button>
          ))}
        </div>
      )}

      <div className="max-h-56 space-y-1 overflow-y-auto" data-testid="sftp-file-list">
        {files.length === 0 && (
          <p className="py-6 text-center text-sm text-muted-foreground">
            {t('batchWizard.sftp.empty')}
          </p>
        )}
        {files.slice(0, 500).map((f) => (
          <label
            key={f.name}
            className="flex cursor-pointer items-center justify-between gap-3 rounded-lg border border-border/70 px-3 py-1.5 text-sm"
          >
            <span className="flex min-w-0 items-center gap-2">
              <Checkbox
                checked={selected.has(f.name)}
                onCheckedChange={(checked) =>
                  setSelected((prev) => {
                    const next = new Set(prev);
                    if (checked) next.add(f.name);
                    else next.delete(f.name);
                    return next;
                  })
                }
              />
              <span className="truncate">{f.name}</span>
            </span>
            <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
              {formatSize(f.size)}
            </span>
          </label>
        ))}
      </div>

      <div className="flex justify-end">
        <Button
          type="button"
          disabled={selected.size === 0 || busy !== null}
          onClick={() => void handlePull()}
          data-testid="sftp-pull"
        >
          {busy === 'pull'
            ? t('batchWizard.sftp.pulling')
            : t('batchWizard.sftp.pullSelected').replace('{n}', String(selected.size))}
        </Button>
      </div>
    </div>
  );
}
