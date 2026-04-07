// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0


import { NavLink, useLocation } from 'react-router-dom';
import { Lock, ShieldCheck } from 'lucide-react';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { useServiceHealth } from '@/hooks/use-service-health';
import { HealthPanel } from '@/components/shared/health-panel';
import {
  PlayIcon,
  BatchIcon,
  HistoryIcon,
  JobsCenterIcon,
  ListIcon,
  RulesIcon,
  ModelIcon,
  TextModelNavIcon,
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
  const { health, checking, roundTripMs, refresh } = useServiceHealth();

  const navItems: NavItem[] = [
    { path: '/', label: t('nav.playground'), icon: PlayIcon, end: true },
    { path: '/batch', label: t('nav.batch'), sublabel: t('nav.batch.sub'), icon: BatchIcon },
    { path: '/history', label: t('nav.history'), icon: HistoryIcon },
    { path: '/jobs', label: t('nav.jobs'), sublabel: t('nav.jobs.sub'), icon: JobsCenterIcon },
    { path: '/settings/redaction', label: t('nav.redactionList'), sublabel: t('nav.redactionList.sub'), icon: ListIcon, end: true },
    { path: '/settings', label: t('nav.recognitionSettings'), sublabel: t('nav.recognitionSettings.sub'), icon: RulesIcon, end: true },
  ];

  const modelNavItems: NavItem[] = [
    { path: '/model-settings/text', label: t('nav.textModel'), icon: TextModelNavIcon },
    { path: '/model-settings/vision', label: t('nav.visionModel'), icon: ModelIcon },
  ];

  return (
    <Sidebar collapsible="offcanvas" variant="inset">
      <SidebarHeader className="h-16 flex-row items-center gap-3 border-b border-sidebar-border px-4">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-2xl border border-sidebar-border bg-sidebar-accent text-sidebar-foreground shadow-[var(--shadow-sm)]">
          <ShieldCheck className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <span className="block truncate text-sm font-semibold leading-tight tracking-[-0.03em] text-sidebar-foreground">
            {t('sidebar.productName')}
          </span>
          <p className="mt-0.5 truncate text-xs text-sidebar-foreground/55">{t('sidebar.subtitle')}</p>
        </div>
      </SidebarHeader>

      <SidebarContent className="px-2 py-2">
        <nav aria-label={t('layout.navLabel')}>
        <SidebarGroup className="px-2 py-1">
          <SidebarGroupContent>
            <SidebarMenu className="gap-1">
              {navItems.map((item) => {
                const active = isNavActive(item, location.pathname);
                return (
                  <SidebarMenuItem key={item.path}>
                    <SidebarMenuButton
                      asChild
                      isActive={active}
                      tooltip={item.label}
                      className={cn(
                        'min-h-11 rounded-xl border border-transparent px-2.5 py-2 transition-all duration-150',
                        active && 'border-sidebar-border bg-sidebar-accent font-medium text-sidebar-foreground shadow-[var(--shadow-control)]',
                      )}
                    >
                      <NavLink
                        to={item.path}
                        end={item.end}
                        aria-label={item.sublabel ? `${item.label} — ${item.sublabel}` : item.label}
                        data-testid={`nav-${item.path.replace(/\//g, '-').replace(/^-/, '')}`}
                      >
                        <item.icon className="h-[16px] w-[16px] opacity-70" />
                        {item.sublabel ? (
                          <span className="flex flex-col gap-0.5 leading-snug">
                            <span className="text-sm">{item.label}</span>
                            <span className="line-clamp-1 text-xs font-normal opacity-45">
                              {item.sublabel}
                            </span>
                          </span>
                        ) : (
                          <span className="text-sm">{item.label}</span>
                        )}
                      </NavLink>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarSeparator className="bg-sidebar-border opacity-100" />

        <SidebarGroup className="px-2 py-1">
          <SidebarGroupLabel className="px-2 text-[11px] font-medium uppercase tracking-[0.08em] text-sidebar-foreground/50">
            {t('nav.modelConfig')}
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu className="gap-1">
              {modelNavItems.map((item) => {
                const active = isNavActive(item, location.pathname);
                return (
                  <SidebarMenuItem key={item.path}>
                    <SidebarMenuButton
                      asChild
                      isActive={active}
                      tooltip={item.label}
                      className={cn(
                        'min-h-11 rounded-xl border border-transparent px-2.5 py-2 transition-all duration-150',
                        active && 'border-sidebar-border bg-sidebar-accent font-medium text-sidebar-foreground shadow-[var(--shadow-control)]',
                      )}
                    >
                      <NavLink
                        to={item.path}
                        aria-label={item.label}
                        data-testid={`nav-${item.path.replace(/\//g, '-').replace(/^-/, '')}`}
                      >
                        <item.icon className="h-[16px] w-[16px] opacity-70" />
                        <span className="text-sm">{item.label}</span>
                      </NavLink>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </nav>
      </SidebarContent>

      <SidebarFooter className="space-y-2 p-3">
        <div className="flex items-center gap-2 rounded-xl border border-sidebar-border bg-sidebar-accent px-3 py-2.5">
          <Lock className="h-3.5 w-3.5 shrink-0 text-sidebar-foreground/75" />
          <span className="text-xs font-medium leading-tight text-sidebar-foreground/80">
            {t('safety.badge.short')}
          </span>
        </div>
        <HealthPanel health={health} checking={checking} roundTripMs={roundTripMs} onRefresh={refresh} />
      </SidebarFooter>
    </Sidebar>
  );
}

function isNavActive(item: NavItem, pathname: string): boolean {
  if (item.end) return pathname === item.path;
  return pathname === item.path || pathname.startsWith(item.path + '/');
}
