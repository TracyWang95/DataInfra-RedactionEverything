// Copyright 2026 DataInfra-RedactionEverything Contributors

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useAuth } from '@/features/auth/auth-context';
import { AdminRuntimePanel } from './panels/runtime-panel';
import { AdminAccessPanel } from './panels/access-panel';
import { AdminAuditPanel } from './panels/audit-panel';
import { AdminLicensePanel } from './panels/license-panel';
import { AdminMonitoringPanel } from './panels/monitoring-panel';

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
              <TabsTrigger value="license">授权许可</TabsTrigger>
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
          <TabsContent value="license" className="mt-0 overflow-auto">
            <AdminLicensePanel />
          </TabsContent>
          <TabsContent value="monitoring" className="mt-0 overflow-auto">
            <AdminMonitoringPanel />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
