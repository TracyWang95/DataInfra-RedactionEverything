// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0


import { Globe } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import { useI18n, useT } from '@/i18n';
import { useServiceHealth } from '@/hooks/use-service-health';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { SidebarTrigger } from '@/components/ui/sidebar';

export function AppHeader() {
  const t = useT();
  const location = useLocation();
  const { locale, setLocale } = useI18n();
  const { health, checking } = useServiceHealth();

  const { title, sub } = getPageHeader(location.pathname, t);

  return (
    <header className="flex h-16 shrink-0 items-center justify-between border-b border-border/70 bg-background/95 px-4 backdrop-blur-2xl sm:px-6">
      <div className="flex min-h-[40px] min-w-0 flex-1 items-center gap-3">
        <SidebarTrigger className="md:hidden" aria-label={t('layout.toggleSidebar')} />
        <div className="flex min-w-0 flex-col justify-center">
          <h1 className="truncate text-lg font-semibold leading-tight tracking-[-0.04em] text-foreground">
            {title}
          </h1>
          {sub && (
            <p className="mt-1 truncate text-xs leading-snug text-muted-foreground sm:text-sm">{sub}</p>
          )}
        </div>
      </div>

      <nav aria-label={t('layout.headerActions')} className="flex shrink-0 items-center gap-2 rounded-full border border-border/70 bg-[var(--surface-control)] px-2 py-1.5 shadow-[var(--shadow-control)]">
        <div
          role="status"
          aria-label={
            checking
              ? t('health.checking')
              : health?.all_online
                ? t('health.allOnline')
                : health
                  ? t('health.someOffline')
                  : t('health.backendDown')
          }
          className="flex items-center gap-1.5 rounded-full px-2.5 py-1"
          data-testid="health-indicator"
        >
          <span
            className={cn('h-[6px] w-[6px] rounded-full transition-colors', {
              'animate-pulse bg-muted-foreground/35': checking,
              'bg-[var(--success-foreground)]': !checking && health?.all_online,
              'bg-[var(--warning-foreground)]': !checking && health && !health.all_online,
              'bg-[var(--error-foreground)]': !checking && !health,
            })}
          />
          <span className="hidden text-[11px] text-muted-foreground sm:inline">
            {checking
              ? t('health.checking')
              : health?.all_online
                ? t('health.allOnline')
                : health
                  ? t('health.someOffline')
                  : t('health.backendDown')}
          </span>
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
          <Globe className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">{locale === 'zh' ? 'EN' : 'ZH'}</span>
        </Button>
      </nav>
    </header>
  );
}

function getPageHeader(pathname: string, t: (key: string) => string): { title: string; sub?: string } {
  if (pathname === '/batch') return { title: t('page.batch.title'), sub: t('page.batch.sub') };
  if (pathname.startsWith('/batch/text')) return { title: t('page.batchText.title'), sub: t('page.batchText.sub') };
  if (pathname.startsWith('/batch/image')) return { title: t('page.batchImage.title'), sub: t('page.batchImage.sub') };
  if (pathname.startsWith('/batch/smart')) return { title: t('page.batchSmart.title'), sub: t('page.batchSmart.sub') };
  if (pathname.startsWith('/settings/redaction')) return { title: t('page.redactionList.title'), sub: t('page.redactionList.sub') };
  if (pathname === '/settings') return { title: t('page.recognitionSettings.title'), sub: t('page.recognitionSettings.sub') };
  if (pathname.startsWith('/jobs/')) return { title: t('page.jobDetail.title'), sub: t('page.jobDetail.sub') };
  if (pathname === '/jobs') return { title: t('page.jobs.title'), sub: t('page.jobs.sub') };

  const map: Record<string, { title: string; sub?: string }> = {
    '/': { title: t('nav.playground') },
    '/history': { title: t('page.history.title'), sub: t('page.history.sub') },
    '/model-settings/text': { title: t('page.textModel.title'), sub: t('page.textModel.sub') },
    '/model-settings/vision': { title: t('page.visionModel.title'), sub: t('page.visionModel.sub') },
  };

  return map[pathname] || { title: t('nav.playground') };
}
