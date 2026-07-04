// Copyright 2026 DataInfra-RedactionEverything Contributors

import React from 'react';
import { createBrowserRouter, Navigate, useLocation, useParams } from 'react-router-dom';
import { Button } from './components/ui/button';
import { Layout } from './components/Layout';
import { ErrorBoundary } from './components/ErrorBoundary';
import { useT } from './i18n';
import { SUSPENSE_SPINNER_DELAY_MS, ROUTE_PREFETCH_DELAY_MS } from './constants/timing';
import {
  isRegisterAuthSearch,
  resolveAuthNext,
} from './features/auth/auth-routing';
import { useAuth } from './features/auth/auth-context';

const AuthPage = React.lazy(() =>
  import('./features/auth/auth-page').then((m) => ({ default: m.AuthPage })),
);
const Playground = React.lazy(() =>
  import('./features/playground').then((m) => ({ default: m.Playground })),
);
const StartPage = React.lazy(() =>
  import('./features/home').then((m) => ({ default: m.StartPage })),
);
const Batch = React.lazy(() => import('./features/batch').then((m) => ({ default: m.Batch })));
const BatchHub = React.lazy(() =>
  import('./features/batch').then((m) => ({ default: m.BatchHub })),
);
const History = React.lazy(() =>
  import('./features/history').then((m) => ({ default: m.History })),
);
const Jobs = React.lazy(() => import('./features/jobs').then((m) => ({ default: m.Jobs })));
const JobDetailPage = React.lazy(() =>
  import('./features/jobs').then((m) => ({ default: m.JobDetailPage })),
);
const Structured = React.lazy(() =>
  import('./features/structured/pages/overview').then((m) => ({ default: m.Structured })),
);
const StructuredFiles = React.lazy(() =>
  import('./features/structured/pages/files').then((m) => ({ default: m.StructuredFiles })),
);
const StructuredDatabase = React.lazy(() =>
  import('./features/structured/pages/database').then((m) => ({ default: m.StructuredDatabase })),
);
const StructuredDatasets = React.lazy(() =>
  import('./features/structured/pages/datasets').then((m) => ({ default: m.StructuredDatasets })),
);
const StructuredDelivery = React.lazy(() =>
  import('./features/structured/pages/delivery').then((m) => ({ default: m.StructuredDelivery })),
);
const Settings = React.lazy(() =>
  import('./features/settings').then((m) => ({ default: m.Settings })),
);
const RedactionListSettings = React.lazy(() =>
  import('./features/settings').then((m) => ({ default: m.RedactionListSettings })),
);
const SystemSettings = React.lazy(() =>
  import('./features/settings').then((m) => ({ default: m.SystemSettings })),
);
const TextModelSettings = React.lazy(() =>
  import('./features/settings').then((m) => ({ default: m.TextModelSettings })),
);
const VisionModelSettings = React.lazy(() =>
  import('./features/settings').then((m) => ({ default: m.VisionModelSettings })),
);
const PlaygroundImagePopout = React.lazy(() =>
  import('./features/playground/components/playground-image-popout').then((m) => ({
    default: m.PlaygroundImagePopout,
  })),
);

function DelayedSpinner() {
  const [show, setShow] = React.useState(false);

  React.useEffect(() => {
    const timer = setTimeout(() => setShow(true), SUSPENSE_SPINNER_DELAY_MS);
    return () => clearTimeout(timer);
  }, []);

  if (!show) return null;

  return (
    <div className="flex h-full items-center justify-center animate-fade-in">
      <div className="h-7 w-7 animate-spin rounded-full border-2 border-border border-t-foreground" />
    </div>
  );
}

const SuspenseFallback = <DelayedSpinner />;

function FullPageSpinner() {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-background">
      <DelayedSpinner />
    </div>
  );
}

function AuthStatusErrorPage() {
  const t = useT();
  const { error, refresh } = useAuth();

  return (
    <div className="flex min-h-dvh items-center justify-center bg-background px-6">
      <div className="w-full max-w-md rounded-3xl border border-border/70 bg-card p-6 shadow-[var(--shadow-md)]">
        <h1 className="text-lg font-semibold tracking-tight text-foreground">
          {t('networkFallback.networkTitle')}
        </h1>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          {error || t('networkFallback.networkDesc')}
        </p>
        <Button className="mt-5" onClick={() => void refresh()}>
          {t('common.retry')}
        </Button>
      </div>
    </div>
  );
}

const prefetchRoutes = () => {
  const routes = [
    () => import('./features/playground'),
    () => import('./features/home'),
    () => import('./features/batch'),
    () => import('./features/structured'),
    () => import('./features/history'),
    () => import('./features/jobs'),
  ];

  void Promise.allSettled(routes.map((route) => route()));
};

if (typeof window !== 'undefined') {
  if ('requestIdleCallback' in window) {
    (
      window as Window & {
        requestIdleCallback: (
          callback: () => void,
          options?: { timeout?: number },
        ) => number;
      }
    ).requestIdleCallback(prefetchRoutes, { timeout: 1200 });
  } else {
    setTimeout(prefetchRoutes, Math.min(ROUTE_PREFETCH_DELAY_MS, 400));
  }
}

function LazyPage({ children }: { children: React.ReactNode }) {
  return (
    <ErrorBoundary>
      <React.Suspense fallback={SuspenseFallback}>{children}</React.Suspense>
    </ErrorBoundary>
  );
}

function getNextLocation(pathname: string, search: string, hash: string): string {
  return `${pathname}${search}${hash}`;
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const { loading, status } = useAuth();

  if (loading) return <FullPageSpinner />;
  if (!status) return <AuthStatusErrorPage />;

  if (status.auth_enabled && !status.authenticated) {
    const next = encodeURIComponent(
      getNextLocation(location.pathname, location.search, location.hash),
    );
    return <Navigate to={`/auth?next=${next}`} replace />;
  }

  return <>{children}</>;
}

function AuthRoute() {
  const location = useLocation();
  const { loading, status } = useAuth();
  const next = resolveAuthNext(location.search);
  const isRegisterRoute = isRegisterAuthSearch(location.search);

  if (loading) return <FullPageSpinner />;
  if (!status) return <AuthStatusErrorPage />;
  if (!status.auth_enabled || status.authenticated) {
    const shouldUseHome = status.authenticated && isRegisterRoute;
    return <Navigate to={shouldUseHome ? '/' : next} replace />;
  }

  return (
    <ErrorBoundary>
      <React.Suspense fallback={<FullPageSpinner />}>
        <AuthPage />
      </React.Suspense>
    </ErrorBoundary>
  );
}

function BatchRoute() {
  const { batchMode } = useParams();
  if (batchMode !== 'smart') {
    return <Navigate to="/batch" replace />;
  }
  return (
    <LazyPage>
      <Batch key={batchMode} />
    </LazyPage>
  );
}

function StructuredPoliciesCompatRoute() {
  const location = useLocation();
  return <Navigate to={`/structured/datasets${location.search}${location.hash}`} replace />;
}

export const router = createBrowserRouter([
  {
    path: '/setup',
    element: <Navigate to="/auth" replace />,
  },
  {
    path: '/auth',
    element: <AuthRoute />,
  },
  {
    path: '/playground/image-editor',
    element: (
      <RequireAuth>
        <LazyPage>
          <PlaygroundImagePopout />
        </LazyPage>
      </RequireAuth>
    ),
  },
  {
    path: '/',
    element: (
      <RequireAuth>
        <Layout />
      </RequireAuth>
    ),
    children: [
      {
        index: true,
        element: (
          <LazyPage>
            <StartPage />
          </LazyPage>
        ),
      },
      {
        path: 'single',
        element: (
          <LazyPage>
            <Playground />
          </LazyPage>
        ),
      },
      {
        path: 'playground',
        element: (
          <LazyPage>
            <Playground />
          </LazyPage>
        ),
      },
      {
        path: 'batch',
        element: (
          <LazyPage>
            <BatchHub />
          </LazyPage>
        ),
      },
      { path: 'batch/:batchMode', element: <BatchRoute /> },
      {
        path: 'structured',
        element: (
          <LazyPage>
            <Structured />
          </LazyPage>
        ),
      },
      {
        path: 'structured/files',
        element: (
          <LazyPage>
            <StructuredFiles />
          </LazyPage>
        ),
      },
      {
        path: 'structured/database',
        element: (
          <LazyPage>
            <StructuredDatabase />
          </LazyPage>
        ),
      },
      {
        path: 'structured/datasets',
        element: (
          <LazyPage>
            <StructuredDatasets />
          </LazyPage>
        ),
      },
      {
        path: 'structured/policies',
        element: <StructuredPoliciesCompatRoute />,
      },
      {
        path: 'structured/delivery',
        element: (
          <LazyPage>
            <StructuredDelivery />
          </LazyPage>
        ),
      },
      {
        path: 'history',
        element: (
          <LazyPage>
            <History />
          </LazyPage>
        ),
      },
      {
        path: 'jobs',
        element: (
          <LazyPage>
            <Jobs />
          </LazyPage>
        ),
      },
      {
        path: 'jobs/:jobId',
        element: (
          <LazyPage>
            <JobDetailPage />
          </LazyPage>
        ),
      },
      {
        path: 'settings/system',
        element: (
          <LazyPage>
            <SystemSettings />
          </LazyPage>
        ),
      },
      {
        path: 'settings/redaction',
        element: (
          <LazyPage>
            <RedactionListSettings />
          </LazyPage>
        ),
      },
      {
        path: 'settings',
        element: (
          <LazyPage>
            <Settings />
          </LazyPage>
        ),
      },
      { path: 'model-settings', element: <Navigate to="/model-settings/text" replace /> },
      {
        path: 'model-settings/text',
        element: (
          <LazyPage>
            <TextModelSettings />
          </LazyPage>
        ),
      },
      {
        path: 'model-settings/vision',
        element: (
          <LazyPage>
            <VisionModelSettings />
          </LazyPage>
        ),
      },
      { path: '*', element: <NotFound /> },
    ],
  },
]);

function NotFound() {
  const t = useT();
  return (
    <div className="flex h-full min-h-0 items-center justify-center px-6">
      <div className="flex min-h-[320px] w-full max-w-xl flex-col items-center justify-center gap-4 rounded-[28px] border border-border/70 bg-card px-8 py-12 text-center shadow-[var(--shadow-floating)]">
        <span className="text-6xl font-semibold tracking-[-0.06em] text-foreground/15">404</span>
        <div className="space-y-2">
          <p className="text-lg font-semibold text-foreground">{t('notFound.title')}</p>
          <p className="text-sm text-muted-foreground">{t('notFound.desc')}</p>
        </div>
        <a
          href="/"
          className="inline-flex h-10 items-center rounded-full border border-border bg-background px-4 text-sm font-medium text-foreground transition-colors hover:bg-accent"
        >
          {t('notFound.backHome')}
        </a>
      </div>
    </div>
  );
}
