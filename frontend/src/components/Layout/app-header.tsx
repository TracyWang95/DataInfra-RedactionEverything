// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useState } from 'react';
import { Globe, KeyRound, LogOut } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import { useI18n, useT } from '@/i18n';
import { useServiceHealth } from '@/hooks/use-service-health';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { SidebarTrigger } from '@/components/ui/sidebar';
import { ChangePasswordDialog } from '@/components/ChangePasswordDialog';
import { useAuth } from '@/features/auth/auth-context';

export function AppHeader() {
  const t = useT();
  const location = useLocation();
  const { locale, setLocale } = useI18n();
  const { health, checking } = useServiceHealth();
  const { status, logout } = useAuth();
  const [changePasswordOpen, setChangePasswordOpen] = useState(false);

  const { title, sub } = getPageHeader(location.pathname, t);
  const hasBusyService = Boolean(
    health && Object.values(health.services).some((service) => service.status === 'busy'),
  );
  const hasDegradedService = Boolean(
    health && Object.values(health.services).some((service) => service.status === 'degraded'),
  );
  const healthLabel = checking
    ? t('health.checking')
    : health?.all_online
      ? t('health.allOnline')
      : health
        ? hasBusyService
          ? t('health.someBusy')
          : hasDegradedService
            ? t('health.someDegraded')
            : t('health.someOffline')
        : t('health.backendDown');

  return (
    <header className="flex h-16 shrink-0 items-center justify-between border-b border-border/70 bg-background/95 px-4 backdrop-blur-2xl sm:px-6">
      <div className="flex min-h-[40px] min-w-0 flex-1 items-center gap-3">
        <SidebarTrigger className="lg:hidden" aria-label={t('layout.toggleSidebar')} />
        <div className="flex min-w-0 flex-col justify-center lg:hidden" aria-label={title}>
          <div className="truncate text-lg font-semibold leading-tight tracking-tight text-foreground">
            {title}
          </div>
          {sub && (
            <p className="mt-1 truncate text-xs leading-snug text-muted-foreground">
              {sub}
            </p>
          )}
        </div>
      </div>

      <nav
        aria-label={t('layout.headerActions')}
        className="flex shrink-0 items-center gap-2 rounded-full border border-border/70 bg-[var(--surface-control)] px-2 py-1.5 shadow-[var(--shadow-control)]"
      >
        <div
          role="status"
          aria-label={healthLabel}
          title={healthLabel}
          className="grid size-8 place-items-center rounded-full"
          data-testid="health-indicator"
        >
          <span
            className={cn('h-2 w-2 rounded-full transition-colors', {
              'animate-pulse bg-muted-foreground/35': checking,
              'bg-[var(--success-foreground)]': !checking && health?.all_online,
              'bg-[var(--warning-foreground)]': !checking && health && !health.all_online,
              'bg-[var(--error-foreground)]': !checking && !health,
            })}
          />
        </div>

        <div className="mx-1 hidden h-4 w-px bg-border/60 sm:block" />

        <Button
          variant="ghost"
          size="sm"
          className="h-8 rounded-full px-2.5 text-xs text-muted-foreground hover:text-foreground"
          onClick={() => setLocale(locale === 'zh' ? 'en' : 'zh')}
          aria-label={t('layout.languageSwitch')}
          data-testid="lang-toggle"
        >
          <Globe className="size-3.5" />
          <span className="hidden sm:inline">
            {locale === 'zh' ? t('layout.switchToEnglish') : t('layout.switchToChinese')}
          </span>
        </Button>

        {status?.auth_enabled && status.authenticated && (
          <>
            <Button
              variant="ghost"
              size="sm"
              className="h-8 rounded-full px-2.5 text-xs text-muted-foreground hover:text-foreground"
              onClick={() => setChangePasswordOpen(true)}
              aria-label={t('auth.changePassword')}
              data-testid="change-password-btn"
            >
              <KeyRound className="size-3.5" />
              <span className="hidden sm:inline">{t('auth.changePassword')}</span>
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-8 rounded-full px-2.5 text-xs text-muted-foreground hover:text-foreground"
              onClick={() => void logout()}
              aria-label={t('auth.logout')}
            >
              <LogOut className="size-3.5" />
              <span className="hidden sm:inline">{t('auth.logout')}</span>
            </Button>
          </>
        )}
      </nav>
      <ChangePasswordDialog
        open={changePasswordOpen}
        onClose={() => setChangePasswordOpen(false)}
      />
    </header>
  );
}

function getPageHeader(
  pathname: string,
  t: (key: string) => string,
): { title: string; sub?: string } {
  if (pathname === '/') return { title: t('page.start.title'), sub: t('page.start.sub') };
  if (pathname === '/batch' || pathname.startsWith('/batch/'))
    return { title: t('page.batch.title'), sub: t('page.batch.sub') };
  if (pathname === '/structured')
    return { title: t('page.structured.title'), sub: t('page.structured.sub') };
  if (pathname === '/structured/files')
    return { title: t('nav.structured.files'), sub: t('nav.structured.files.sub') };
  if (pathname === '/structured/database')
    return { title: t('nav.structured.database'), sub: t('nav.structured.database.sub') };
  if (pathname === '/structured/datasets')
    return { title: t('nav.structured.datasets'), sub: t('nav.structured.datasets.sub') };
  if (pathname === '/structured/delivery')
    return { title: t('nav.structured.delivery'), sub: t('nav.structured.delivery.sub') };
  if (pathname.startsWith('/settings/redaction'))
    return { title: t('page.redactionList.title'), sub: t('page.redactionList.sub') };
  if (pathname === '/settings') return { title: t('page.config.title'), sub: t('page.config.sub') };
  if (pathname.startsWith('/jobs/'))
    return { title: t('page.jobDetail.title'), sub: t('page.jobDetail.sub') };
  if (pathname === '/jobs') return { title: t('page.jobs.title'), sub: t('page.jobs.sub') };

  const map: Record<string, { title: string; sub?: string }> = {
    '/single': { title: t('playground.title'), sub: t('page.playground.sub') },
    '/playground': { title: t('playground.title'), sub: t('page.playground.sub') },
    '/history': { title: t('page.history.title'), sub: t('page.history.sub') },
    '/model-settings/text': { title: t('page.textModel.title'), sub: t('page.textModel.sub') },
    '/model-settings/vision': {
      title: t('page.visionModel.title'),
      sub: t('page.visionModel.sub'),
    },
  };

  return map[pathname] || { title: t('nav.playground') };
}
