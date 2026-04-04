/**
 * Application header bar with page title, language toggle, theme switch, and health state.
 */
import { Globe, Moon, Sun } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import { useI18n, useT } from '@/i18n';
import { useDarkMode } from '@/hooks/useDarkMode';
import { useServiceHealth } from '@/hooks/use-service-health';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { SidebarTrigger } from '@/components/ui/sidebar';

export function AppHeader() {
  const t = useT();
  const location = useLocation();
  const { dark, toggle: toggleDark } = useDarkMode();
  const { locale, setLocale } = useI18n();
  const { health, checking } = useServiceHealth();

  const { title, sub } = getPageHeader(location.pathname, t);

  return (
    <header className="flex h-[60px] shrink-0 items-center justify-between border-b border-border/60 bg-[rgba(251,251,248,0.7)] px-4 backdrop-blur-2xl sm:px-6 dark:bg-[rgba(17,17,16,0.72)]">
      <div className="flex min-h-[36px] min-w-0 flex-1 items-center gap-3">
        <SidebarTrigger className="md:hidden" />
        <div className="flex min-w-0 flex-col justify-center">
          <h1 className="text-[15px] font-semibold leading-tight tracking-[-0.03em] text-foreground">
            {title}
          </h1>
          {sub && (
            <p className="mt-0.5 text-[11px] leading-snug text-muted-foreground">{sub}</p>
          )}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2 rounded-full border border-border/70 bg-card px-2 py-1 shadow-[0_18px_38px_-28px_rgba(15,23,42,0.22)]">
        <div
          className="flex items-center gap-1.5 rounded-full px-2.5 py-1"
          data-testid="health-indicator"
        >
          <span
            className={cn('h-[6px] w-[6px] rounded-full transition-colors', {
              'animate-pulse bg-slate-300 dark:bg-slate-600': checking,
              'bg-emerald-500': !checking && health?.all_online,
              'bg-amber-400': !checking && health && !health.all_online,
              'bg-red-500': !checking && !health,
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
          aria-label="Switch language"
          data-testid="lang-toggle"
        >
          <Globe className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">{locale === 'zh' ? 'EN' : '\u4E2D'}</span>
        </Button>

        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 rounded-full text-muted-foreground hover:text-foreground"
          onClick={toggleDark}
          aria-label={dark ? t('layout.darkMode.toLight') : t('layout.darkMode.toDark')}
          data-testid="dark-mode-toggle"
        >
          {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>
      </div>
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
