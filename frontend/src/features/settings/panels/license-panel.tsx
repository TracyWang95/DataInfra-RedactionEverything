// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useCallback, useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { authFetch } from '@/services/api-client';
import { localizeErrorMessage } from '@/utils/localizeError';
import { MetricCard, PanelHeading } from './shared';

interface LicenseStatus {
  state: string;
  customer?: string | null;
  edition?: string | null;
  expires_at?: string | null;
  days_left?: number | null;
  max_users?: number | null;
  seats_used?: number | null;
  features?: Record<string, unknown> | null;
}

const LICENSE_STATE_LABEL: Record<string, string> = {
  unlicensed: '未启用授权（开发/评估模式）',
  valid: '授权有效',
  expiring_soon: '即将到期',
  grace_readonly: '已过期（宽限期·只读）',
  blocked: '已停用（超出宽限期）',
  invalid: '证书无效',
};

export function AdminLicensePanel() {
  const [status, setStatus] = useState<LicenseStatus | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await authFetch('/api/v1/license/status');
      if (res.ok) setStatus((await res.json()) as LicenseStatus);
    } catch {
      /* 状态加载失败面板显示占位 */
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function handleUpload(files: FileList | null) {
    const file = files?.[0];
    if (!file) return;
    setMsg(null);
    setErr(null);
    try {
      const document = JSON.parse(await file.text()) as Record<string, unknown>;
      const res = await authFetch('/api/v1/license/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(document),
      });
      if (!res.ok) {
        const detail = (await res.json().catch(() => null)) as { message?: string } | null;
        throw new Error(detail?.message || `HTTP ${res.status}`);
      }
      setMsg('授权证书已安装并生效');
      await load();
    } catch (e) {
      setErr(localizeErrorMessage(e, 'system.error.licenseUpload'));
    }
  }

  const industries = Array.isArray(status?.features?.industries)
    ? (status.features.industries as string[]).join('、')
    : '-';

  return (
    <section className="surface-subtle space-y-4 p-4" data-testid="admin-license-panel">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <PanelHeading
          title="授权许可"
          description="离线签名证书：状态、席位与续期。默认关闭强制（unlicensed），客户交付构建才启用。"
        />
        <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-border bg-background px-3 py-1.5 text-sm font-medium hover:bg-muted">
          上传续期证书
          <input
            type="file"
            accept=".json"
            className="hidden"
            onChange={(event) => {
              void handleUpload(event.target.files);
              event.target.value = '';
            }}
            data-testid="license-upload-input"
          />
        </label>
      </div>
      {msg && <p className="text-sm text-[var(--success-foreground)]">{msg}</p>}
      {err && <p className="text-sm text-[var(--error-foreground)]">{err}</p>}
      <div className="grid gap-3 sm:grid-cols-4">
        <MetricCard
          label="授权状态"
          value={status ? (LICENSE_STATE_LABEL[status.state] ?? status.state) : '加载中…'}
        />
        <MetricCard label="客户" value={status?.customer || '-'} />
        <MetricCard
          label="到期日"
          value={
            status?.expires_at
              ? `${status.expires_at}${status.days_left != null ? `（余 ${status.days_left} 天）` : ''}`
              : '-'
          }
        />
        <MetricCard
          label="席位"
          value={
            status?.max_users != null ? `${status.seats_used ?? '-'} / ${status.max_users}` : '-'
          }
        />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <MetricCard label="版本" value={status?.edition || '-'} />
        <MetricCard label="已授权行业包" value={industries} />
      </div>
      <AdminApiKeysSection />
    </section>
  );
}

interface ApiKeyRow {
  key_id: string;
  name: string;
  scope: string;
  expires_at?: string | null;
  created_at?: string | null;
  last_used_at?: string | null;
  revoked: boolean;
}

function AdminApiKeysSection() {
  const [keys, setKeys] = useState<ApiKeyRow[]>([]);
  const [name, setName] = useState('');
  const [scope, setScope] = useState<'readonly' | 'readwrite'>('readonly');
  const [creating, setCreating] = useState(false);
  const [plaintext, setPlaintext] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await authFetch('/api/v1/auth/api-keys');
      if (res.ok) setKeys((await res.json()) as ApiKeyRow[]);
    } catch {
      /* 列表失败下方显示空态 */
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim() || creating) return;
    setCreating(true);
    setErr(null);
    setPlaintext(null);
    try {
      const res = await authFetch('/api/v1/auth/api-keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), scope }),
      });
      const data = (await res.json().catch(() => null)) as
        | { api_key?: string; message?: string; detail?: string }
        | null;
      if (!res.ok) throw new Error(data?.message || data?.detail || `HTTP ${res.status}`);
      setPlaintext(data?.api_key ?? null);
      setName('');
      await load();
    } catch (e) {
      setErr(localizeErrorMessage(e, 'system.error.apiKeyCreate'));
    } finally {
      setCreating(false);
    }
  }

  async function handleRevoke(keyId: string) {
    setErr(null);
    try {
      const res = await authFetch(`/api/v1/auth/api-keys/${encodeURIComponent(keyId)}`, {
        method: 'DELETE',
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await load();
    } catch (e) {
      setErr(localizeErrorMessage(e, 'system.error.apiKeyRevoke'));
    }
  }

  return (
    <div className="space-y-3 border-t border-border/70 pt-4" data-testid="admin-api-keys">
      <div>
        <h3 className="text-sm font-semibold tracking-tight">API 密钥（系统对接）</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          供外部系统以 X-API-Key 请求头调用；明文只在创建时显示一次。只读密钥不能执行任何修改操作。
        </p>
      </div>
      <form className="flex flex-wrap items-center gap-2" onSubmit={handleCreate}>
        <input
          value={name}
          maxLength={64}
          onChange={(event) => setName(event.target.value)}
          placeholder="密钥名称（如 etl-sync）"
          className="h-8 w-56 rounded-lg border border-border bg-background px-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
          data-testid="api-key-name-input"
        />
        <select
          value={scope}
          onChange={(event) => setScope(event.target.value as 'readonly' | 'readwrite')}
          className="h-8 rounded-lg border border-border bg-background px-2 text-sm"
          data-testid="api-key-scope-select"
        >
          <option value="readonly">只读</option>
          <option value="readwrite">读写</option>
        </select>
        <Button type="submit" size="sm" className="h-8" disabled={!name.trim() || creating}>
          {creating ? '创建中…' : '创建密钥'}
        </Button>
      </form>
      {plaintext && (
        <div
          className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--warning-border)] bg-[var(--warning-surface)] px-3 py-2 text-xs"
          data-testid="api-key-plaintext"
        >
          <span className="font-medium text-[var(--warning-foreground)]">
            请立即复制，此明文不再显示：
          </span>
          <code className="select-all break-all font-mono">{plaintext}</code>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-6 px-2 text-xs"
            onClick={() => void navigator.clipboard?.writeText(plaintext)}
          >
            复制
          </Button>
        </div>
      )}
      {err && <p className="text-sm text-[var(--error-foreground)]">{err}</p>}
      <div className="space-y-1.5">
        {keys.length === 0 && (
          <p className="py-3 text-center text-sm text-muted-foreground">暂无密钥</p>
        )}
        {keys.map((row) => (
          <div
            key={row.key_id}
            className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/70 px-3 py-2 text-sm"
            data-testid={`api-key-row-${row.key_id}`}
          >
            <div className="min-w-0">
              <span className="font-medium">{row.name}</span>
              <span className="ml-2 rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground">
                {row.scope === 'readwrite' ? '读写' : '只读'}
              </span>
              {row.revoked && (
                <span className="ml-2 text-xs text-[var(--error-foreground)]">已吊销</span>
              )}
              <div className="text-xs text-muted-foreground">
                最近使用：{row.last_used_at ? row.last_used_at.slice(0, 19).replace('T', ' ') : '从未'}
              </div>
            </div>
            {!row.revoked && (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-7 px-2 text-xs text-[var(--error-foreground)]"
                onClick={() => void handleRevoke(row.key_id)}
                data-testid={`api-key-revoke-${row.key_id}`}
              >
                吊销
              </Button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
