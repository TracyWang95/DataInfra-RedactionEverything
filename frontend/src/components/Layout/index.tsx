import React, { useState, useEffect, useCallback } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { ToastContainer } from '../Toast';
import { OfflineBanner } from '../OfflineBanner';
import { useDarkMode } from '../../hooks/useDarkMode';
import { OnboardingGuide } from '../OnboardingGuide';
import { useI18n, useT } from '../../i18n';

interface ServiceInfo {
  name: string;
  status: 'online' | 'offline' | 'checking';
}

interface ServicesHealth {
  all_online: boolean;
  /** 后端并行探测各依赖耗时（毫秒） */
  probe_ms?: number;
  /** UTC ISO 时间，服务端探测完成时刻 */
  checked_at?: string;
  /** 本机 nvidia-smi 首块 GPU 显存（MiB）；无驱动/无 GPU 时为 null */
  gpu_memory?: { used_mb: number; total_mb: number } | null;
  services: {
    paddle_ocr: ServiceInfo;
    has_ner: ServiceInfo;
    has_image: ServiceInfo;
  };
}

export const Layout: React.FC = () => {
  const location = useLocation();
  const { dark, toggle: toggleDark } = useDarkMode();
  const { locale, setLocale } = useI18n();
  const t = useT();

  // 服务状态 - 真实轮询
  const [health, setHealth] = useState<ServicesHealth | null>(null);
  const [checking, setChecking] = useState(true);
  /** 浏览器 → 后端 /health/services 整轮耗时（含网络） */
  const [roundTripMs, setRoundTripMs] = useState<number | null>(null);
  
  /** 含 OCR 首次加载；需 ≥ 后端 OCR_HEALTH_PROBE_TIMEOUT（默认 45s） */
  const HEALTH_SERVICES_TIMEOUT_MS = 55000;

  const fetchHealth = useCallback(async (showChecking = false) => {
    if (showChecking) setChecking(true);
    const ac = new AbortController();
    const timer = window.setTimeout(() => ac.abort(), HEALTH_SERVICES_TIMEOUT_MS);
    const t0 = performance.now();
    try {
      const res = await fetch('/health/services', { signal: ac.signal });
      if (res.ok) {
        const data = await res.json();
        setHealth(data);
        setRoundTripMs(Math.round(performance.now() - t0));
      } else {
        setHealth(null);
        setRoundTripMs(null);
      }
    } catch {
      setHealth(null);
      setRoundTripMs(null);
    } finally {
      window.clearTimeout(timer);
      setChecking(false);
    }
  }, []);
  
  // 首次加载 + 每15秒轮询（轮询不闪「检测中」，避免干扰）
  useEffect(() => {
    fetchHealth(false);
    const timer = setInterval(() => fetchHealth(false), 15000);
    return () => clearInterval(timer);
  }, [fetchHealth]);

  const navItems: {
    path: string;
    label: string;
    sublabel?: string;
    icon: React.FC<{ className?: string }>;
    disabled?: boolean;
    /** 为 true 时仅路径完全匹配才算激活（用于 /settings 与 /settings/redaction 区分） */
    end?: boolean;
  }[] = [
    { path: '/', label: t('nav.playground'), icon: PlayIcon },
    {
      path: '/batch',
      label: t('nav.batch'),
      sublabel: t('nav.batch.sub'),
      icon: BatchIcon,
    },
    { path: '/history', label: t('nav.history'), icon: HistoryIcon },
    { path: '/jobs', label: t('nav.jobs'), sublabel: t('nav.jobs.sub'), icon: JobsCenterIcon },
    {
      path: '/settings/redaction',
      label: t('nav.redactionList'),
      sublabel: t('nav.redactionList.sub'),
      icon: ListIcon,
      end: true,
    },
    { path: '/settings', label: t('nav.recognitionSettings'), sublabel: t('nav.recognitionSettings.sub'), icon: RulesIcon, end: true },
  ];

  const modelNavItems = [
    { path: '/model-settings/text', label: t('nav.textModel'), icon: TextModelNavIcon },
    { path: '/model-settings/vision', label: t('nav.visionModel'), icon: ModelIcon },
  ];

  const getBatchHeader = (): { title: string; sub?: string } | null => {
    if (location.pathname === '/batch') {
      return { title: t('page.batch.title'), sub: t('page.batch.sub') };
    }
    if (location.pathname.startsWith('/batch/text')) {
      return { title: t('page.batchText.title'), sub: t('page.batchText.sub') };
    }
    if (location.pathname.startsWith('/batch/image')) {
      return { title: t('page.batchImage.title'), sub: t('page.batchImage.sub') };
    }
    if (location.pathname.startsWith('/batch/smart')) {
      return { title: t('page.batchSmart.title'), sub: t('page.batchSmart.sub') };
    }
    return null;
  };

  /** 与各页面正文去重：标题仅在此展示，子页面不再重复 h2 */
  const getPageHeader = (): { title: string; sub?: string } => {
    const batchH = getBatchHeader();
    if (batchH) return batchH;
    if (location.pathname.startsWith('/settings/redaction')) {
      return { title: t('page.redactionList.title'), sub: t('page.redactionList.sub') };
    }
    if (location.pathname === '/settings') {
      return { title: t('page.recognitionSettings.title'), sub: t('page.recognitionSettings.sub') };
    }
    if (location.pathname.startsWith('/jobs/')) {
      return { title: t('page.jobDetail.title'), sub: t('page.jobDetail.sub') };
    }
    if (location.pathname === '/jobs') {
      return { title: t('page.jobs.title'), sub: t('page.jobs.sub') };
    }
    const map: Record<string, { title: string; sub?: string }> = {
      '/': { title: t('nav.playground') },
      '/history': { title: t('page.history.title'), sub: t('page.history.sub') },
      '/model-settings/text': { title: t('page.textModel.title'), sub: t('page.textModel.sub') },
      '/model-settings/vision': { title: t('page.visionModel.title'), sub: t('page.visionModel.sub') },
    };
    return map[location.pathname] || { title: t('nav.playground') };
  };

  return (
    <div className="app-shell flex h-dvh min-h-0 min-w-0 overflow-hidden bg-[#f5f5f7] dark:bg-gray-900">
      <OfflineBanner />
      {/* Sidebar */}
      <aside className="app-sidebar w-[220px] min-[1280px]:w-[252px] shrink-0 bg-[#fbfbfc] dark:bg-gray-800 border-r border-black/[0.06] dark:border-gray-700 flex flex-col min-h-0 min-w-0">
        {/* Logo */}
        <div className="app-sidebar-brand h-[52px] flex items-center px-4 border-b border-black/[0.06] dark:border-gray-700">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-[#1d1d1f] flex items-center justify-center shadow-sm">
              <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
              </svg>
            </div>
            <div>
              <span className="font-semibold text-sm text-[#1d1d1f] dark:text-gray-100 tracking-[-0.02em] leading-tight block">
                DataInfra-RedactionEverything
              </span>
              <p className="text-caption text-[#737373] dark:text-gray-400">{t('sidebar.subtitle')}</p>
            </div>
          </div>
        </div>
        
        {/* Navigation */}
        <nav className="flex-1 p-2 space-y-0.5 overflow-y-auto">
          {navItems.map(item => (
            item.disabled ? (
              <div
                key={item.path}
                className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium text-[#a3a3a3] cursor-not-allowed"
              >
                <item.icon className="w-[18px] h-[18px]" />
                <span>{item.label}</span>
                <span className="ml-auto text-2xs bg-[#f5f5f5] px-1.5 py-0.5 rounded text-[#737373]">{t('sidebar.devInProgress')}</span>
              </div>
            ) : (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.end ?? item.path === '/'}
                className={({ isActive }) =>
                  `app-nav-link flex items-start gap-2.5 px-3 py-2 rounded-xl text-sm font-medium transition-all duration-200 ${
                    isActive
                      ? 'app-nav-link-active bg-[#1d1d1f] text-white shadow-sm'
                      : 'app-nav-link-idle text-[#6e6e73] hover:bg-white/70 hover:text-[#1d1d1f]'
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    <item.icon className="w-[18px] h-[18px] flex-shrink-0 mt-0.5" />
                    {item.sublabel ? (
                      <span className="flex flex-col gap-0.5 min-w-0 leading-snug">
                        <span>{item.label}</span>
                        <span
                          className={`text-2xs font-normal leading-tight line-clamp-2 ${
                            isActive ? 'text-white/75' : 'text-[#a3a3a3]'
                          }`}
                        >
                          {item.sublabel}
                        </span>
                      </span>
                    ) : (
                      <span>{item.label}</span>
                    )}
                  </>
                )}
              </NavLink>
            )
          ))}

          {/* 模型配置：文本 / 视觉 */}
          <div className="app-model-section mt-2 pt-2 border-t border-black/[0.06]">
            <div className="px-3 py-1.5 text-caption font-semibold text-[#a3a3a3] tracking-wide">{t('nav.modelConfig')}</div>
            {modelNavItems.map(item => (
              <NavLink
                key={item.path}
                to={item.path}
                className={({ isActive }) =>
                  `app-nav-link flex items-center gap-2.5 pl-5 pr-3 py-2 rounded-xl text-sm font-medium transition-all duration-200 ${
                    isActive
                      ? 'app-nav-link-active bg-[#1d1d1f] text-white shadow-sm'
                      : 'app-nav-link-idle text-[#6e6e73] hover:bg-white/70 hover:text-[#1d1d1f]'
                  }`
                }
              >
                <item.icon className="w-[18px] h-[18px] flex-shrink-0" />
                {item.label}
              </NavLink>
            ))}
          </div>
        </nav>
        
        {/* Footer - 服务状态（真实轮询） */}
        <div className="app-sidebar-footer p-3 border-t border-black/[0.06]">
          <div className="app-health-card px-3 py-2.5 rounded-xl bg-white/80 border border-black/[0.06] shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className={`w-[6px] h-[6px] rounded-full ${
                  checking ? 'bg-gray-300 animate-pulse' :
                  health?.all_online ? 'bg-[#22c55e]' : 'bg-amber-400'
                }`}></span>
                <span className="text-caption font-semibold text-[#1d1d1f] tracking-wide">{t('health.title')}</span>
              </div>
              <button
                type="button"
                onClick={() => fetchHealth(true)}
                className="text-2xs text-gray-400 hover:text-gray-600"
                title={t('health.refreshTitle')}
                aria-label={t('health.refreshTitle')}
              >
                <svg className={`w-3 h-3 ${checking ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
              </button>
            </div>
            {health ? (
              <div className="space-y-1.5 text-caption">
                {/* PaddleOCR */}
                <div className="flex justify-between items-center">
                  <span className="text-[#737373] truncate mr-2" title={health.services.paddle_ocr.name}>
                    {health.services.paddle_ocr.name}
                  </span>
                  <span className={`font-medium flex-shrink-0 ${health.services.paddle_ocr.status === 'online' ? 'text-[#22c55e]' : 'text-red-500'}`}>
                    {health.services.paddle_ocr.status === 'online' ? t('health.online') : t('health.offline')}
                  </span>
                </div>
                {/* HaS NER */}
                <div className="flex justify-between items-center">
                  <span className="text-[#737373] truncate mr-2" title={health.services.has_ner.name}>
                    {health.services.has_ner.name}
                  </span>
                  <span className={`font-medium flex-shrink-0 ${health.services.has_ner.status === 'online' ? 'text-[#22c55e]' : 'text-red-500'}`}>
                    {health.services.has_ner.status === 'online' ? t('health.online') : t('health.offline')}
                  </span>
                </div>
                {/* HaS Image (YOLO) */}
                <div className="flex justify-between items-center">
                  <span className="text-[#737373] truncate mr-2" title={health.services.has_image.name}>
                    {health.services.has_image.name}
                  </span>
                  <span className={`font-medium flex-shrink-0 ${health.services.has_image.status === 'online' ? 'text-[#22c55e]' : 'text-red-500'}`}>
                    {health.services.has_image.status === 'online' ? t('health.online') : t('health.offline')}
                  </span>
                </div>
                <div className="text-2xs text-[#a3a3a3] pt-1.5 mt-0.5 border-t border-[#f0f0f0] space-y-0.5 leading-snug pl-0.5">
                  {typeof health.probe_ms === 'number' && (
                    <p className="truncate" title={t('health.backendProbe')}>
                      {t('health.backendProbe')} {health.probe_ms} ms
                    </p>
                  )}
                  {roundTripMs != null && (
                    <p className="truncate" title={t('health.frontendRoundTrip')}>
                      {t('health.frontendRoundTrip')} {roundTripMs} ms
                    </p>
                  )}
                  <p
                    className="truncate"
                    title={t('health.gpuMemory')}
                  >
                    {t('health.gpuMemory')}{' '}
                    {health.gpu_memory != null ? (
                      <>
                        {health.gpu_memory.used_mb} / {health.gpu_memory.total_mb} MiB
                      </>
                    ) : (
                      <span className="text-[#c4c4c4]">{t('health.gpuNotDetected')}</span>
                    )}
                  </p>
                  {health.checked_at && (
                    <p className="text-[#b0b0b0] break-all" title={health.checked_at}>
                      {t('health.probeTime')} {new Date(health.checked_at).toLocaleString()}
                    </p>
                  )}
                </div>
              </div>
            ) : (
              <div className="text-caption text-red-500">
                {checking ? t('health.detecting') : t('health.backendDown')}
              </div>
            )}
          </div>
        </div>
      </aside>
      
      {/* Main Content */}
      <main className="app-main flex-1 flex flex-col min-h-0 min-w-0 overflow-hidden bg-[#f5f5f7] dark:bg-gray-900">
        {/* Header */}
        <header className="app-header h-[52px] shrink-0 bg-white/80 dark:bg-gray-800/80 backdrop-blur-xl border-b border-black/[0.06] dark:border-gray-700 flex items-center justify-between px-4 sm:px-6 min-w-0">
          <div className="min-h-[36px] flex flex-col justify-center">
            {(() => {
              const h = getPageHeader();
              if (h.sub) {
                return (
                  <>
                    <h1 className="text-base font-semibold text-[#1d1d1f] dark:text-gray-100 tracking-[-0.02em] leading-tight">
                      {h.title}
                    </h1>
                    <p className="text-caption text-[#737373] dark:text-gray-400 font-normal mt-0.5 leading-snug">{h.sub}</p>
                  </>
                );
              }
              return <h1 className="text-base font-semibold text-[#1d1d1f] dark:text-gray-100 tracking-[-0.02em]">{h.title}</h1>;
            })()}
          </div>
          <div className="flex items-center gap-4">
            <button
              type="button"
              onClick={() => setLocale(locale === 'zh' ? 'en' : 'zh')}
              className="app-header-control px-2 py-1 text-xs rounded border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-300"
              aria-label="Switch language"
            >
              {locale === 'zh' ? 'EN' : '中'}
            </button>
            <button
              type="button"
              onClick={toggleDark}
              className="app-icon-button p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-400"
              aria-label={dark ? '切换到亮色模式' : '切换到深色模式'}
              title={dark ? '切换到亮色模式' : '切换到深色模式'}
            >
              {dark ? (
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
                </svg>
              ) : (
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                </svg>
              )}
            </button>
            <div className="flex items-center gap-1.5 text-caption">
              {checking ? (
                <>
                  <span className="w-[6px] h-[6px] rounded-full bg-gray-300 animate-pulse"></span>
                  <span className="text-gray-400">{t('health.checking')}</span>
                </>
              ) : health?.all_online ? (
                <>
                  <span className="w-[6px] h-[6px] rounded-full bg-[#22c55e]"></span>
                  <span className="text-[#737373]">{t('health.allOnline')}</span>
                </>
              ) : health ? (
                <>
                  <span className="w-[6px] h-[6px] rounded-full bg-amber-400"></span>
                  <span className="text-amber-600">{t('health.someOffline')}</span>
                </>
              ) : (
                <>
                  <span className="w-[6px] h-[6px] rounded-full bg-red-500"></span>
                  <span className="text-red-500">{t('health.backendDown')}</span>
                </>
              )}
            </div>
          </div>
        </header>
        
        {/* Content：单页内滚动，避免整页出现双滚动条 */}
        <div className="flex-1 min-h-0 min-w-0 overflow-hidden overscroll-contain flex flex-col">
          <Outlet />
        </div>
      </main>

      {/* Toast Container */}
      <ToastContainer />
      <OnboardingGuide />
    </div>
  );
};

// Icons
const PlayIcon: React.FC<{ className?: string }> = ({ className }) => (
  <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/>
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
  </svg>
);

const BatchIcon: React.FC<{ className?: string }> = ({ className }) => (
  <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/>
  </svg>
);

const HistoryIcon: React.FC<{ className?: string }> = ({ className }) => (
  <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
  </svg>
);

const JobsCenterIcon: React.FC<{ className?: string }> = ({ className }) => (
  <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={1.5}
      d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"
    />
  </svg>
);

/** 脱敏清单 / 预设 */
const ListIcon: React.FC<{ className?: string }> = ({ className }) => (
  <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
  </svg>
);

// 识别规则配置图标
const RulesIcon: React.FC<{ className?: string }> = ({ className }) => (
  <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/>
  </svg>
);

// 视觉模型配置图标
const ModelIcon: React.FC<{ className?: string }> = ({ className }) => (
  <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/>
  </svg>
);

const TextModelNavIcon: React.FC<{ className?: string }> = ({ className }) => (
  <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 6h16M4 12h10M4 18h7" />
  </svg>
);

export default Layout;
