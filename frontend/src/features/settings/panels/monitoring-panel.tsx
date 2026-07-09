// Copyright 2026 DataInfra-RedactionEverything Contributors

import { RefreshCw } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useServiceHealth, type ServiceInfo, type ServicesHealth } from '@/hooks/use-service-health';
import { cn } from '@/lib/utils';
import { MetricCard, PanelHeading } from './shared';

export function AdminMonitoringPanel() {
  const { health, checking, roundTripMs, refresh } = useServiceHealth();
  const services = serviceRows(health);
  const allOnline = health?.all_online;

  return (
    <section className="surface-subtle space-y-4 p-4" data-testid="admin-monitoring-panel">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <PanelHeading title="服务监控" description="查看模型服务、GPU 显存和健康探测状态。" />
        <Button variant="outline" size="sm" onClick={refresh}>
          <RefreshCw className={cn('mr-2 size-4', checking && 'animate-spin')} />
          刷新
        </Button>
      </div>
      <div className="grid gap-3 sm:grid-cols-4">
        <MetricCard label="整体状态" value={checking ? '检测中' : allOnline ? '全部在线' : '需处理'} />
        <MetricCard label="后端探测" value={roundTripMs == null ? '-' : `${roundTripMs} ms`} />
        <MetricCard label="GPU 显存" value={gpuText(health)} />
        <MetricCard
          label="数据盘"
          value={
            health?.disk
              ? `余 ${health.disk.free_gb}G / 已用 ${(health.disk.used_ratio * 100).toFixed(0)}%`
              : '-'
          }
        />
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
