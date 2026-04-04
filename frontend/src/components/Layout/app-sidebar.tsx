/**
 * Application sidebar — premium dark sidebar inspired by Linear / Raycast.
 * Contains navigation links, model config section, data safety badge, and health panel.
 */
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
      {/* Brand header */}
      <SidebarHeader className="h-[64px] flex-row items-center gap-3 border-b border-white/[0.08] px-4">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl bg-white text-[#0f172a] shadow-[0_14px_34px_-18px_rgba(255,255,255,0.6)]">
          <ShieldCheck className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <span className="block text-[13px] font-semibold leading-tight tracking-[-0.02em] text-white">
            Redaction Console
          </span>
          <p className="text-[10px] text-white/45">{t('sidebar.subtitle')}</p>
        </div>
      </SidebarHeader>

      {/* Main navigation */}
      <SidebarContent className="px-2 py-2">
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu className="space-y-0.5">
              {navItems.map((item) => {
                const active = isNavActive(item, location.pathname);
                return (
                  <SidebarMenuItem key={item.path}>
                    <SidebarMenuButton
                      asChild
                      isActive={active}
                      tooltip={item.label}
                      className={cn(
                        'rounded-xl border border-transparent transition-all duration-150',
                        active && 'border-white/[0.08] bg-white/[0.08] font-medium shadow-[0_16px_34px_-24px_rgba(0,0,0,0.65)]',
                      )}
                    >
                      <NavLink
                        to={item.path}
                        end={item.end}
                        data-testid={`nav-${item.path.replace(/\//g, '-').replace(/^-/, '')}`}
                      >
                        <item.icon className="h-[16px] w-[16px] opacity-70" />
                        {item.sublabel ? (
                          <span className="flex flex-col gap-0.5 leading-snug">
                            <span className="text-[13px]">{item.label}</span>
                            <span className="line-clamp-1 text-[10px] font-normal opacity-40">
                              {item.sublabel}
                            </span>
                          </span>
                        ) : (
                          <span className="text-[13px]">{item.label}</span>
                        )}
                      </NavLink>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarSeparator className="opacity-[0.08]" />

        {/* Model config section */}
        <SidebarGroup>
          <SidebarGroupLabel className="px-2 text-[10px] font-medium uppercase tracking-[0.08em] opacity-40">
            {t('nav.modelConfig')}
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu className="space-y-0.5">
              {modelNavItems.map((item) => {
                const active = isNavActive(item, location.pathname);
                return (
                  <SidebarMenuItem key={item.path}>
                    <SidebarMenuButton
                      asChild
                      isActive={active}
                      tooltip={item.label}
                      className={cn(
                        'rounded-xl border border-transparent transition-all duration-150',
                        active && 'border-white/[0.08] bg-white/[0.08] font-medium shadow-[0_16px_34px_-24px_rgba(0,0,0,0.65)]',
                      )}
                    >
                      <NavLink
                        to={item.path}
                        data-testid={`nav-${item.path.replace(/\//g, '-').replace(/^-/, '')}`}
                      >
                        <item.icon className="h-[16px] w-[16px] opacity-70" />
                        <span className="text-[13px]">{item.label}</span>
                      </NavLink>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      {/* Data safety badge + health panel */}
      <SidebarFooter className="p-3 space-y-2">
        <div className={cn(
          'flex items-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.04] px-2.5 py-2',
        )}>
          <Lock className="h-3.5 w-3.5 shrink-0 text-white/80" />
          <span className="text-[10px] font-medium leading-tight text-white/72">
            {t('safety.badge.short')}
          </span>
        </div>
        <HealthPanel health={health} checking={checking} roundTripMs={roundTripMs} onRefresh={refresh} />
      </SidebarFooter>
    </Sidebar>
  );
}

/** Determine if a nav item should be marked active based on the current path */
function isNavActive(item: NavItem, pathname: string): boolean {
  if (item.end) return pathname === item.path;
  return pathname === item.path || pathname.startsWith(item.path + '/');
}
