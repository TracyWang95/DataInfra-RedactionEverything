// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { NavLink, useLocation } from 'react-router-dom';
import { RefreshCw, ShieldCheck } from 'lucide-react';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { useAuth } from '@/features/auth/auth-context';
import { useServiceHealth, type ServiceInfo, type ServicesHealth } from '@/hooks/use-service-health';
import {
  HomeIcon,
  PlayIcon,
  BatchIcon,
  HistoryIcon,
  JobsCenterIcon,
  ModelIcon,
  RulesIcon,
} from '@/components/shared/nav-icons';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarSeparator,
} from '@/components/ui/sidebar';

interface NavItem {
  path: string;
  label: string;
  sublabel?: string;
  icon: React.FC<{ className?: string }>;
  end?: boolean;
}

export function AppSidebar() {
  const t = useT();
  const location = useLocation();
  const { status } = useAuth();
  const { health, checking, roundTripMs, refresh } = useServiceHealth();
  const isAdmin = Boolean(status?.is_super_admin);

  const workflowNavItems: NavItem[] = [
    { path: '/', label: t('nav.start'), sublabel: t('nav.start.sub'), icon: HomeIcon, end: true },
    {
      path: '/single',
      label: t('nav.playground'),
      sublabel: t('nav.playground.sub'),
      icon: PlayIcon,
      end: true,
    },
    { path: '/batch', label: t('nav.batch'), sublabel: t('nav.batch.sub'), icon: BatchIcon },
    { path: '/jobs', label: t('nav.jobs'), sublabel: t('nav.jobs.sub'), icon: JobsCenterIcon },
    {
      path: '/history',
      label: t('nav.history'),
      sublabel: t('nav.history.sub'),
      icon: HistoryIcon,
    },
  ];

  const configNavItems: NavItem[] = [
    {
      path: '/settings',
      label: t('nav.recognitionSettings'),
      sublabel: t('nav.recognitionSettings.sub'),
      icon: RulesIcon,
      end: true,
    },
    {
      path: '/settings/redaction',
      label: t('nav.redactionList'),
      sublabel: t('nav.redactionList.sub'),
      icon: RulesIcon,
    },
    ...(isAdmin
      ? [
          {
            path: '/settings/system',
            label: t('nav.systemSettings'),
            sublabel: t('nav.systemSettings.sub'),
            icon: ModelIcon,
          },
        ]
      : []),
  ];

  return (
    <Sidebar collapsible="offcanvas" variant="inset">
      <SidebarHeader className="h-[4.25rem] flex-row items-center gap-3 border-b border-sidebar-border px-4">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-xl border border-sidebar-border bg-sidebar-accent text-sidebar-foreground shadow-[var(--shadow-sm)]">
          <ShieldCheck className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <span className="block truncate text-sm font-semibold leading-tight tracking-[-0.03em] text-sidebar-foreground">
            {t('sidebar.productName')}
          </span>
          <p className="mt-0.5 truncate text-xs text-sidebar-foreground/55">
            {t('sidebar.subtitle')}
          </p>
        </div>
      </SidebarHeader>

      <SidebarContent className="px-2 py-3">
        <nav aria-label={t('layout.navLabel')}>
          <SidebarGroup className="px-2 py-1">
            <SidebarGroupLabel className="px-2 text-[11px] font-semibold tracking-[0.02em] text-sidebar-foreground/50">
              {t('nav.group.workflow')}
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu className="gap-1.5">
                {workflowNavItems.map((item) => (
                  <SidebarNavItem key={item.path} item={item} pathname={location.pathname} />
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>

          <SidebarSeparator className="my-2 bg-sidebar-border opacity-100" />

          <SidebarGroup className="px-2 py-1">
            <SidebarGroupLabel className="px-2 text-[11px] font-semibold tracking-[0.02em] text-sidebar-foreground/50">
              {t('nav.group.config')}
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu className="gap-1.5">
                {configNavItems.map((item) => (
                  <SidebarNavItem key={item.path} item={item} pathname={location.pathname} />
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </nav>
      </SidebarContent>

      <SidebarFooter className="shrink-0 space-y-2 p-3">
        <SidebarServiceStatus
          health={health}
          checking={checking}
          roundTripMs={roundTripMs}
          onRefresh={refresh}
        />
      </SidebarFooter>
    </Sidebar>
  );
}

function SidebarNavItem({ item, pathname }: { item: NavItem; pathname: string }) {
  const active = isNavActive(item, pathname);

  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        asChild
        isActive={active}
        tooltip={item.label}
        className={cn(
          'min-h-10 rounded-xl border border-transparent px-2.5 py-2 transition-all duration-150',
          active &&
            'border-sidebar-border bg-sidebar-accent font-medium text-sidebar-foreground shadow-[var(--shadow-control)]',
        )}
      >
        <NavLink
          to={item.path}
          end={item.end}
          aria-label={item.sublabel ? `${item.label} - ${item.sublabel}` : item.label}
          data-testid={`nav-${item.path.replace(/\//g, '-').replace(/^-/, '') || 'start'}`}
        >
          <item.icon className="h-[16px] w-[16px] opacity-70" />
          {item.sublabel ? (
            <span className="flex min-w-0 flex-col gap-0.5 leading-snug">
              <span className="truncate text-[13px] font-medium">{item.label}</span>
              <span className="truncate text-[11px] font-normal opacity-45">{item.sublabel}</span>
            </span>
          ) : (
            <span className="truncate text-[13px] font-medium">{item.label}</span>
          )}
        </NavLink>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}

function isNavActive(item: NavItem, pathname: string): boolean {
  if (item.path === '/settings') {
    return pathname === '/settings' || pathname.startsWith('/model-settings');
  }
  if (item.end) return pathname === item.path;
  return pathname === item.path || pathname.startsWith(item.path + '/');
}

const serviceOrder: Array<keyof ServicesHealth['services']> = [
  'paddle_ocr',
  'has_ner',
  'has_image',
  'vlm',
];

function SidebarServiceStatus({
  health,
  checking,
  roundTripMs,
  onRefresh,
}: {
  health: ServicesHealth | null;
  checking: boolean;
  roundTripMs: number | null;
  onRefresh: () => void;
}) {
  const t = useT();
  const services = serviceOrder.map((key) => ({
    key,
    service: health?.services[key] ?? fallbackService(key, checking, t),
  }));
  const statuses = services.map(({ service }) => displayStatus(service));
  const overallTone =
    !health && !checking
      ? 'error'
      : statuses.some((status) => status === 'offline')
        ? 'error'
        : statuses.some((status) => status === 'degraded' || status === 'checking')
          ? 'warning'
          : 'success';
  const statusText = checking
    ? t('health.checking')
    : !health
      ? t('health.backendDown')
      : statuses.some((status) => status === 'offline')
        ? t('health.someOffline')
        : statuses.some((status) => status === 'degraded')
          ? t('health.someDegraded')
          : t('health.allOnline');
  const gpuText = getGpuText(health, t);

  return (
    <section
      className="min-h-[9rem] min-w-0 overflow-hidden rounded-xl border border-sidebar-border bg-sidebar-accent px-3 py-2.5 text-sidebar-foreground shadow-[var(--shadow-sm)]"
      aria-label={t('health.sidebar.title')}
      data-testid="sidebar-service-status"
    >
      <div className="flex items-center gap-2">
        <span
          className={cn('h-2.5 w-2.5 shrink-0 rounded-full', {
            'animate-pulse bg-sidebar-foreground/35': checking,
            'bg-[var(--success-foreground)]': overallTone === 'success',
            'bg-[var(--warning-foreground)]': overallTone === 'warning',
            'bg-[var(--error-foreground)]': overallTone === 'error',
          })}
        />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{t('health.sidebar.title')}</p>
          <p className="truncate text-[11px] font-medium text-sidebar-foreground/60">
            {statusText}
            {roundTripMs != null ? ` · ${roundTripMs} ms` : ''}
          </p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-sidebar-foreground/60 transition hover:bg-sidebar-primary hover:text-sidebar-foreground"
          title={t('health.refreshTitle')}
          aria-label={t('health.refreshTitle')}
          data-testid="health-refresh"
        >
          <RefreshCw className={cn('h-3.5 w-3.5', checking && 'animate-spin')} />
        </button>
      </div>

      <div className="mt-2.5 grid gap-1.5">
        {services.map(({ key, service }) => {
          const status = displayStatus(service);
          const runtime = runtimeBadge(service, t);
          const serviceName = t(`health.service.${key}`);

          return (
            <div
              key={key}
              className="grid min-h-7 min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 overflow-hidden rounded-lg bg-sidebar/45 px-2 py-1"
            >
              <span className="min-w-0 truncate text-[11px] font-medium" title={serviceName}>
                {serviceName}
              </span>
              <span
                className={cn('shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-semibold', {
                  'bg-[var(--success-surface)] text-[var(--success-foreground)]':
                    status === 'online',
                  'bg-[var(--warning-surface)] text-[var(--warning-foreground)]':
                    status === 'checking' || status === 'degraded',
                  'bg-[var(--error-surface)] text-[var(--error-foreground)]': status === 'offline',
                })}
              >
                {runtime ?? t(`health.${status}`)}
              </span>
            </div>
          );
        })}
      </div>

      <div className="mt-2 grid min-h-7 min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-2 overflow-hidden rounded-lg border border-sidebar-border/80 px-2 py-1">
        <span className="shrink-0 text-[11px] font-semibold">{t('health.gpuUsage')}</span>
        <span className="min-w-0 truncate text-right text-[11px] text-sidebar-foreground/70" title={gpuText}>
          {gpuText}
        </span>
      </div>
    </section>
  );
}

function displayStatus(service: ServiceInfo): 'online' | 'offline' | 'checking' | 'degraded' {
  return service.status === 'busy' ? 'online' : service.status;
}

function fallbackService(
  key: keyof ServicesHealth['services'],
  checking: boolean,
  t: (key: string) => string,
): ServiceInfo {
  return { name: t(`health.service.${key}`), status: checking ? 'checking' : 'offline' };
}

function getGpuText(health: ServicesHealth | null, t: (key: string) => string) {
  if (!health) return t('health.gpuNotDetected');
  if (health.gpu_memory) {
    const usedGb = (health.gpu_memory.used_mb / 1024).toFixed(1);
    const totalGb = (health.gpu_memory.total_mb / 1024).toFixed(1);
    return `${usedGb}/${totalGb} GB`;
  }

  const runtimeModes = serviceOrder
    .map((key) => health.services[key]?.detail?.runtime_mode)
    .filter(Boolean);
  const hasCpuFallbackRisk = serviceOrder.some(
    (key) => health.services[key]?.detail?.cpu_fallback_risk,
  );
  if (hasCpuFallbackRisk) return t('health.runtime.cpuRisk');
  if (runtimeModes.includes('gpu')) return t('health.runtime.gpu');
  if (runtimeModes.includes('cpu')) return t('health.runtime.cpu');

  return t('health.gpuNotDetected');
}

function runtimeBadge(service: ServiceInfo, t: (key: string) => string) {
  if (service.detail?.cpu_fallback_risk) return t('health.runtime.cpuRisk');
  if (service.detail?.runtime_mode) return t(`health.runtime.${service.detail.runtime_mode}`);
  return null;
}
