// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useEffect, useState } from 'react';
import { EmptyState } from '@/components/EmptyState';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { authFetch } from '@/services/api-client';
import { localizeErrorMessage } from '@/utils/localizeError';
import { PanelHeading, parseJson } from './shared';

interface AuditEntry {
  timestamp?: string;
  user?: string;
  action?: string;
  resource_type?: string;
  resource_id?: string;
  detail?: Record<string, unknown>;
}

export function AdminAuditPanel() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [userFilter, setUserFilter] = useState('');
  const [actionFilter, setActionFilter] = useState('');
  const [keyword, setKeyword] = useState('');
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const buildQuery = () => {
    const params = new URLSearchParams();
    if (userFilter.trim()) params.set('user', userFilter.trim());
    if (actionFilter.trim()) params.set('action', actionFilter.trim());
    if (keyword.trim()) params.set('q', keyword.trim());
    return params.toString();
  };

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = buildQuery();
      const res = await authFetch(`/api/v1/audit/logs${qs ? `?${qs}` : ''}`);
      const body = await parseJson<{ entries?: AuditEntry[]; detail?: string }>(res);
      if (!res.ok || !body?.entries) throw new Error(body?.detail || `HTTP ${res.status}`);
      setEntries(body.entries);
    } catch (err) {
      setError(localizeErrorMessage(err, 'system.error.loadAudit'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function exportCsv() {
    setExporting(true);
    setError(null);
    try {
      const qs = buildQuery();
      const res = await authFetch(`/api/v1/audit/logs/export${qs ? `?${qs}` : ''}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'audit-logs.csv';
      a.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
    } catch (err) {
      setError(localizeErrorMessage(err, 'system.error.exportAudit'));
    } finally {
      setExporting(false);
    }
  }

  return (
    <section className="surface-subtle space-y-4 p-4" data-testid="admin-audit-panel">
      <PanelHeading title="审计日志" description="谁在什么时间上传、确认、导出了什么。仅管理员可见。" />
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <Label htmlFor="audit-user">用户</Label>
          <Input
            id="audit-user"
            className="h-9 w-40"
            value={userFilter}
            onChange={(event) => setUserFilter(event.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="audit-action">动作</Label>
          <Input
            id="audit-action"
            className="h-9 w-40"
            placeholder="upload / commit_all…"
            value={actionFilter}
            onChange={(event) => setActionFilter(event.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="audit-q">关键字</Label>
          <Input
            id="audit-q"
            className="h-9 w-52"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
          />
        </div>
        <Button size="sm" disabled={loading} onClick={() => void load()}>
          {loading ? '查询中…' : '查询'}
        </Button>
        <Button size="sm" variant="outline" disabled={exporting} onClick={() => void exportCsv()}>
          {exporting ? '导出中…' : '导出 CSV'}
        </Button>
      </div>
      <div className="overflow-hidden rounded-lg border border-border bg-background">
        <div className="grid grid-cols-[11rem_8rem_8rem_minmax(0,1fr)] border-b border-border px-3 py-2 text-xs font-semibold text-muted-foreground">
          <span>时间</span>
          <span>用户</span>
          <span>动作</span>
          <span>资源 / 详情</span>
        </div>
        <div className="max-h-[30rem] overflow-auto">
          {entries.map((entry, index) => (
            <div
              key={`${entry.timestamp}-${index}`}
              className="grid min-h-9 grid-cols-[11rem_8rem_8rem_minmax(0,1fr)] items-center border-b border-border/60 px-3 py-1.5 text-xs last:border-b-0"
            >
              <span className="truncate text-muted-foreground" title={entry.timestamp}>
                {(entry.timestamp || '').replace('T', ' ').slice(0, 19)}
              </span>
              <span className="truncate" title={entry.user}>
                {entry.user}
              </span>
              <Badge variant="secondary" className="w-fit">
                {entry.action}
              </Badge>
              <span
                className="truncate text-muted-foreground"
                title={`${entry.resource_type}:${entry.resource_id} ${JSON.stringify(entry.detail ?? {})}`}
              >
                {entry.resource_type}:{entry.resource_id}{' '}
                {JSON.stringify(entry.detail ?? {})}
              </span>
            </div>
          ))}
          {!entries.length &&
            (loading ? (
              <div className="px-3 py-8 text-center text-sm text-muted-foreground">正在加载…</div>
            ) : (
              <EmptyState
                title="暂无匹配的审计记录"
                description="调整用户、动作或关键字筛选后再查询。"
              />
            ))}
        </div>
      </div>
    </section>
  );
}
