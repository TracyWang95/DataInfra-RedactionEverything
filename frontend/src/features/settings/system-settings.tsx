// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

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
  updated_at?: string | null;
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
        <div className="page-shell">
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
              <h2 className="text-base font-semibold tracking-tight">系统设置</h2>
              <p className="text-sm text-muted-foreground">运行配置、用户权限和本地服务监控。</p>
            </div>
            <TabsList className="rounded-xl border border-border/70 bg-muted/40 p-1">
              <TabsTrigger value="runtime">运行配置</TabsTrigger>
              <TabsTrigger value="access">权限信息</TabsTrigger>
              <TabsTrigger value="monitoring">服务监控</TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="runtime" className="mt-0 overflow-auto">
            <AdminRuntimePanel />
          </TabsContent>
          <TabsContent value="access" className="mt-0 overflow-auto">
            <AdminAccessPanel />
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
      <PanelHeading
        title="运行配置"
        description="控制后台批量任务队列。并发用户不会触发重新部署或换端口，而是在同一服务内排队执行。"
      />
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
  const [role, setRole] = useState<'user' | 'super_admin'>('user');
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
        <PanelHeading
          title="权限信息"
          description="每个用户只访问自己上传的文件、任务和结果。普通用户也可以在登录页自行注册。"
        />
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
          <div className="grid grid-cols-[minmax(0,1fr)_8rem_11rem] border-b border-border px-3 py-2 text-xs font-semibold text-muted-foreground">
            <span>用户</span>
            <span>角色</span>
            <span>创建时间</span>
          </div>
          <div className="max-h-[26rem] overflow-auto">
            {users.map((user) => (
              <div
                key={user.username}
                className="grid min-h-10 grid-cols-[minmax(0,1fr)_8rem_11rem] items-center border-b border-border/60 px-3 py-2 text-sm last:border-b-0"
              >
                <span className="truncate" title={user.username}>
                  {user.username}
                </span>
                <Badge variant={user.role === 'super_admin' ? 'default' : 'secondary'}>
                  {user.role}
                </Badge>
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
        <PanelHeading title="创建用户" description="管理员可预先创建普通用户或其他管理员。" />
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
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            value={role}
            onChange={(event) => setRole(event.target.value === 'super_admin' ? 'super_admin' : 'user')}
          >
            <option value="user">普通用户</option>
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

function AdminMonitoringPanel() {
  const { health, checking, roundTripMs, refresh } = useServiceHealth();
  const services = serviceRows(health);
  const allOnline = health?.all_online;

  return (
    <section className="surface-subtle space-y-4 p-4" data-testid="admin-monitoring-panel">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <PanelHeading
          title="服务监控"
          description="查看后端、模型服务、GPU 显存和服务探测状态。"
        />
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
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
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
    <div className="rounded-lg border border-border bg-background px-3 py-2">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 truncate text-sm font-semibold" title={value}>
        {value}
      </p>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[4rem_minmax(0,1fr)] gap-2">
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
    has_image: { name: 'HaS Image', status: 'offline' },
    vlm: { name: 'VLM', status: 'offline' },
  };
  const services = health?.services ?? fallback;
  return [
    { key: 'paddle_ocr', service: services.paddle_ocr },
    { key: 'has_ner', service: services.has_ner },
    { key: 'has_image', service: services.has_image },
    { key: 'vlm', service: services.vlm ?? fallback.vlm },
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
