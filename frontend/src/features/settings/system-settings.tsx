// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useAuth } from '@/features/auth/auth-context';
import { useServiceHealth, type ServiceInfo, type ServicesHealth } from '@/hooks/use-service-health';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { authFetch } from '@/services/api-client';

interface ConcurrencySettings {
  job_concurrency: number;
  default_job_concurrency: number;
  min_job_concurrency: number;
  max_job_concurrency: number;
}

interface AdminUser {
  username: string;
  role: string;
  created_at?: string | null;
  can_bulk_confirm?: boolean;
}

async function parseJson<T>(res: Response): Promise<T | null> {
  try {
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

export function SystemSettings() {
  const { status } = useAuth();

  if (!status?.is_super_admin) {
    return (
      <div className="saas-page flex min-h-0 min-w-0 flex-1 flex-col bg-background">
        <div className="page-shell !max-w-[min(100%,1920px)] !px-3 !py-2 sm:!px-4 sm:!py-3">
          <Alert variant="destructive">
            <AlertDescription>需要管理员权限。</AlertDescription>
          </Alert>
        </div>
      </div>
    );
  }

  return (
    <div className="saas-page flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background">
      <div className="page-shell !max-w-[min(100%,1920px)] !px-3 !py-2 sm:!px-4 sm:!py-3">
        <Tabs defaultValue="runtime" className="page-stack gap-3 overflow-hidden">
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight text-foreground">系统设置</h1>
              <p className="text-sm text-muted-foreground">运行配置、用户权限和本地服务监控。</p>
            </div>
            <TabsList className="rounded-xl border border-border/70 bg-muted/40 p-1">
              <TabsTrigger value="runtime">运行配置</TabsTrigger>
              <TabsTrigger value="access">权限信息</TabsTrigger>
              <TabsTrigger value="audit">审计日志</TabsTrigger>
              <TabsTrigger value="monitoring">服务监控</TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="runtime" className="mt-0 overflow-auto">
            <AdminRuntimePanel />
          </TabsContent>
          <TabsContent value="access" className="mt-0 overflow-auto">
            <AdminAccessPanel />
          </TabsContent>
          <TabsContent value="audit" className="mt-0 overflow-auto">
            <AdminAuditPanel />
          </TabsContent>
          <TabsContent value="monitoring" className="mt-0 overflow-auto">
            <AdminMonitoringPanel />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

function AdminRuntimePanel() {
  const t = useT();
  const [settings, setSettings] = useState<ConcurrencySettings | null>(null);
  const [value, setValue] = useState('3');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await authFetch('/api/v1/auth/concurrency');
        const body = await parseJson<ConcurrencySettings & { detail?: string }>(res);
        if (!res.ok || !body) throw new Error(body?.detail || `HTTP ${res.status}`);
        if (!cancelled) {
          setSettings(body);
          setValue(String(body.job_concurrency));
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : t('auth.error.generic'));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [t]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const next = Number.parseInt(value, 10);
      const res = await authFetch('/api/v1/auth/concurrency', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_concurrency: next }),
      });
      const body = await parseJson<ConcurrencySettings & { detail?: string }>(res);
      if (!res.ok || !body) throw new Error(body?.detail || `HTTP ${res.status}`);
      setSettings(body);
      setValue(String(body.job_concurrency));
    } catch (err) {
      setError(err instanceof Error ? err.message : t('auth.error.generic'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="surface-subtle max-w-2xl space-y-4 p-4" data-testid="admin-runtime-panel">
      <PanelHeading title="运行配置" description="控制后台批量任务并发，不需要重启模型服务。" />
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <div className="space-y-2">
        <Label htmlFor="job-concurrency">{t('settings.runtime.jobConcurrency')}</Label>
        <div className="flex max-w-xs items-center gap-2">
          <Input
            id="job-concurrency"
            type="number"
            min={settings?.min_job_concurrency ?? 1}
            max={settings?.max_job_concurrency ?? 16}
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
          <Button type="button" disabled={saving} onClick={() => void save()}>
            {saving ? t('settings.saving') : t('settings.save')}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          {t('settings.runtime.jobConcurrencyHint')
            .replace('{current}', String(settings?.job_concurrency ?? 3))
            .replace('{default}', String(settings?.default_job_concurrency ?? 3))}
        </p>
      </div>
    </section>
  );
}

function AdminAccessPanel() {
  const { status } = useAuth();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [role, setRole] = useState('user');
  const roleLabels: Record<string, string> = {
    super_admin: '管理员',
    reviewer: '审核员',
    user: '普通用户',
    operator: '操作员',
    viewer: '只读',
  };
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadUsers = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetch('/api/v1/auth/users');
      const body = await parseJson<(AdminUser[] & { detail?: string }) | { detail?: string }>(res);
      if (!res.ok || !Array.isArray(body)) {
        throw new Error((body && 'detail' in body && body.detail) || `HTTP ${res.status}`);
      }
      setUsers(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : '用户列表加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadUsers();
  }, []);

  async function toggleBulkConfirm(user: AdminUser) {
    if (user.role === 'super_admin') return; // super admins always have it
    const next = !user.can_bulk_confirm;
    setUsers((prev) =>
      prev.map((u) => (u.username === user.username ? { ...u, can_bulk_confirm: next } : u)),
    );
    setError(null);
    try {
      const res = await authFetch(
        `/api/v1/auth/users/${encodeURIComponent(user.username)}/permissions`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ bulk_confirm: next }),
        },
      );
      const body = await parseJson<{ detail?: string }>(res);
      if (!res.ok) throw new Error(body?.detail || `HTTP ${res.status}`);
    } catch (err) {
      setUsers((prev) =>
        prev.map((u) => (u.username === user.username ? { ...u, can_bulk_confirm: !next } : u)),
      );
      setError(err instanceof Error ? err.message : '权限更新失败');
    }
  }

  async function createUser() {
    if (password !== confirmPassword) {
      setError('两次输入的密码不一致。');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const res = await authFetch('/api/v1/auth/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password, role }),
      });
      const body = await parseJson<{ detail?: string }>(res);
      if (!res.ok) throw new Error(body?.detail || `HTTP ${res.status}`);
      setUsername('');
      setPassword('');
      setConfirmPassword('');
      setRole('user');
      await loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建用户失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_22rem]" data-testid="admin-access-panel">
      <div className="surface-subtle space-y-4 p-4">
        <PanelHeading title="权限信息" description="每个用户只访问自己的文件、任务和结果。" />
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <div className="grid gap-3 sm:grid-cols-3">
          <MetricCard label="当前账号" value={status?.username || '-'} />
          <MetricCard label="当前角色" value={status?.role || 'user'} />
          <MetricCard label="账号数量" value={loading ? '...' : String(users.length)} />
        </div>
        <div className="overflow-hidden rounded-lg border border-border bg-background">
          <div className="grid grid-cols-[minmax(0,1fr)_7rem_7rem_10rem] border-b border-border px-3 py-2 text-xs font-semibold text-muted-foreground">
            <span>用户</span>
            <span>角色</span>
            <span title="允许在批量审阅时一键确认剩余全部文件">批量确认</span>
            <span>创建时间</span>
          </div>
          <div className="max-h-[26rem] overflow-auto">
            {users.map((user) => (
              <div
                key={user.username}
                className="grid min-h-10 grid-cols-[minmax(0,1fr)_7rem_7rem_10rem] items-center border-b border-border/60 px-3 py-2 text-sm last:border-b-0"
              >
                <span className="truncate" title={user.username}>
                  {user.username}
                </span>
                <Badge variant={user.role === 'super_admin' ? 'default' : 'secondary'}>
                  {roleLabels[user.role] ?? user.role}
                </Badge>
                <span>
                  {user.role === 'super_admin' ? (
                    <span className="text-xs text-muted-foreground">始终允许</span>
                  ) : (
                    <Button
                      type="button"
                      size="sm"
                      variant={user.can_bulk_confirm ? 'default' : 'outline'}
                      className="h-7 px-2 text-xs"
                      onClick={() => void toggleBulkConfirm(user)}
                    >
                      {user.can_bulk_confirm ? '已允许' : '未允许'}
                    </Button>
                  )}
                </span>
                <span className="truncate text-xs text-muted-foreground">
                  {formatDate(user.created_at)}
                </span>
              </div>
            ))}
            {!users.length && (
              <div className="px-3 py-8 text-center text-sm text-muted-foreground">
                {loading ? '正在加载用户...' : '暂无用户'}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="surface-subtle space-y-4 p-4">
        <PanelHeading title="创建用户" description="管理员可以创建普通用户或管理员。" />
        <div className="space-y-2">
          <Label htmlFor="admin-new-username">用户名</Label>
          <Input id="admin-new-username" value={username} onChange={(event) => setUsername(event.target.value)} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="admin-new-password">密码</Label>
          <Input
            id="admin-new-password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="admin-new-confirm-password">确认密码</Label>
          <Input
            id="admin-new-confirm-password"
            type="password"
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="admin-new-role">角色</Label>
          <select
            id="admin-new-role"
            className="flex h-10 w-full rounded-xl border border-input bg-[var(--surface-control)] px-3 py-2 text-sm shadow-[var(--shadow-control)]"
            value={role}
            onChange={(event) => setRole(event.target.value)}
          >
            <option value="user">普通用户（完整流程）</option>
            <option value="reviewer">审核员（完整流程，可授批量确认）</option>
            <option value="operator">操作员（上传/识别/导出，不可确认审核）</option>
            <option value="viewer">只读（仅查看）</option>
            <option value="super_admin">管理员</option>
          </select>
        </div>
        <Button className="w-full" disabled={saving || !username || !password} onClick={() => void createUser()}>
          {saving ? '创建中...' : '创建用户'}
        </Button>
      </div>
    </section>
  );
}

interface AuditEntry {
  timestamp?: string;
  user?: string;
  action?: string;
  resource_type?: string;
  resource_id?: string;
  detail?: Record<string, unknown>;
}

function AdminAuditPanel() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [userFilter, setUserFilter] = useState('');
  const [actionFilter, setActionFilter] = useState('');
  const [keyword, setKeyword] = useState('');
  const [loading, setLoading] = useState(false);
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
      setError(err instanceof Error ? err.message : '审计日志加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function exportCsv() {
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
      setError(err instanceof Error ? err.message : '导出失败');
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
        <Button size="sm" variant="outline" onClick={() => void exportCsv()}>
          导出 CSV
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
          {!entries.length && (
            <div className="px-3 py-8 text-center text-sm text-muted-foreground">
              {loading ? '正在加载…' : '暂无匹配的审计记录'}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function AdminMonitoringPanel() {
  const { health, checking, roundTripMs, refresh } = useServiceHealth();
  const services = serviceRows(health);
  const allOnline = health?.all_online;

  return (
    <section className="surface-subtle space-y-4 p-4" data-testid="admin-monitoring-panel">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <PanelHeading title="服务监控" description="查看模型服务、GPU 显存和健康探测状态。" />
        <Button variant="outline" size="sm" onClick={refresh}>
          <RefreshCw className={cn('mr-2 h-4 w-4', checking && 'animate-spin')} />
          刷新
        </Button>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <MetricCard label="整体状态" value={checking ? '检测中' : allOnline ? '全部在线' : '需处理'} />
        <MetricCard label="后端探测" value={roundTripMs == null ? '-' : `${roundTripMs} ms`} />
        <MetricCard label="GPU 显存" value={gpuText(health)} />
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {services.map(({ key, service }) => (
          <div key={key} className="rounded-lg border border-border bg-background p-3">
            <div className="flex items-center justify-between gap-2">
              <h3 className="truncate text-sm font-semibold">{service.name}</h3>
              <StatusBadge status={service.status} />
            </div>
            <dl className="mt-3 space-y-1 text-xs text-muted-foreground">
              <InfoRow label="运行时" value={service.detail?.runtime || '-'} />
              <InfoRow label="模式" value={service.detail?.runtime_mode || '-'} />
              <InfoRow label="设备" value={service.detail?.device || '-'} />
            </dl>
          </div>
        ))}
      </div>
    </section>
  );
}

function PanelHeading({ title, description }: { title: string; description: string }) {
  return (
    <div>
      <h2 className="text-base font-semibold tracking-tight">{title}</h2>
      <p className="mt-1 text-sm leading-6 text-muted-foreground">{description}</p>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-background p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 truncate text-sm font-semibold" title={value}>
        {value}
      </p>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <dt>{label}</dt>
      <dd className="truncate text-foreground" title={value}>
        {value}
      </dd>
    </div>
  );
}

function StatusBadge({ status }: { status: ServiceInfo['status'] }) {
  const normalized = status === 'busy' ? 'online' : status;
  return (
    <Badge
      variant={normalized === 'online' ? 'default' : normalized === 'offline' ? 'destructive' : 'secondary'}
    >
      {normalized}
    </Badge>
  );
}

function serviceRows(health: ServicesHealth | null): Array<{ key: string; service: ServiceInfo }> {
  const fallback: Required<ServicesHealth['services']> = {
    paddle_ocr: { name: 'PaddleOCR', status: 'offline' },
    has_ner: { name: 'HaS Text', status: 'offline' },
    visual_features: { name: '视觉特征', status: 'offline' },
  };
  const services = health?.services ?? fallback;
  return [
    { key: 'paddle_ocr', service: services.paddle_ocr },
    { key: 'has_ner', service: services.has_ner },
    { key: 'visual_features', service: services.visual_features },
  ];
}

function gpuText(health: ServicesHealth | null): string {
  if (!health?.gpu_memory) return '-';
  const usedGb = (health.gpu_memory.used_mb / 1024).toFixed(1);
  const totalGb = (health.gpu_memory.total_mb / 1024).toFixed(1);
  return `${usedGb}/${totalGb} GB`;
}

function formatDate(value?: string | null): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}
