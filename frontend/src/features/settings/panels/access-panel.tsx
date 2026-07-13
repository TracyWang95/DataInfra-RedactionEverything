// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useEffect, useState } from 'react';
import { EmptyState } from '@/components/EmptyState';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useAuth } from '@/features/auth/auth-context';
import { authFetch } from '@/services/api-client';
import { localizeErrorMessage } from '@/utils/localizeError';
import { MetricCard, PanelHeading, parseJson } from './shared';

interface AdminUser {
  username: string;
  role: string;
  created_at?: string | null;
  can_bulk_confirm?: boolean;
}

export function AdminAccessPanel() {
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
      setError(localizeErrorMessage(err, 'system.error.loadUsers'));
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
      setError(localizeErrorMessage(err, 'system.error.updatePermission'));
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
      setError(localizeErrorMessage(err, 'system.error.createUser'));
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
            {!users.length &&
              (loading ? (
                <div className="px-3 py-8 text-center text-sm text-muted-foreground">
                  正在加载用户...
                </div>
              ) : (
                <EmptyState title="暂无用户" description="使用右侧表单创建第一个账号。" />
              ))}
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

function formatDate(value?: string | null): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}
