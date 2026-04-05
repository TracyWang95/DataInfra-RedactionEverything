import React from 'react';
import { createBrowserRouter, Navigate, useParams } from 'react-router-dom';
import { Layout } from './components/Layout';
import { ErrorBoundary } from './components/ErrorBoundary';
import { t } from './i18n';

const Playground = React.lazy(() => import('./features/playground').then(m => ({ default: m.Playground })));
const Batch = React.lazy(() => import('./features/batch').then(m => ({ default: m.Batch })));
const BatchHub = React.lazy(() => import('./features/batch').then(m => ({ default: m.BatchHub })));
const History = React.lazy(() => import('./features/history').then(m => ({ default: m.History })));
const Jobs = React.lazy(() => import('./features/jobs').then(m => ({ default: m.Jobs })));
const JobDetailPage = React.lazy(() => import('./features/jobs').then(m => ({ default: m.JobDetailPage })));
const Settings = React.lazy(() => import('./features/settings').then(m => ({ default: m.Settings })));
const RedactionListSettings = React.lazy(() => import('./features/settings').then(m => ({ default: m.RedactionListSettings })));
const TextModelSettings = React.lazy(() => import('./features/settings').then(m => ({ default: m.TextModelSettings })));
const VisionModelSettings = React.lazy(() => import('./features/settings').then(m => ({ default: m.VisionModelSettings })));
const PlaygroundImagePopout = React.lazy(() => import('./features/playground/components/playground-image-popout').then(m => ({ default: m.PlaygroundImagePopout })));

function DelayedSpinner() {
  const [show, setShow] = React.useState(false);

  React.useEffect(() => {
    const timer = setTimeout(() => setShow(true), 150);
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

const prefetchRoutes = () => {
  import('./features/batch');
  import('./features/history');
  import('./features/jobs');
};

if (typeof window !== 'undefined') {
  if ('requestIdleCallback' in window) {
    (window as Window & { requestIdleCallback: (callback: () => void) => void }).requestIdleCallback(prefetchRoutes);
  } else {
    setTimeout(prefetchRoutes, 2000);
  }
}

function LazyPage({ children }: { children: React.ReactNode }) {
  return (
    <ErrorBoundary>
      <React.Suspense fallback={SuspenseFallback}>{children}</React.Suspense>
    </ErrorBoundary>
  );
}

const VALID_BATCH_MODES = new Set(['text', 'image', 'smart']);

function BatchRoute() {
  const { batchMode } = useParams();
  if (!batchMode || !VALID_BATCH_MODES.has(batchMode)) {
    return <Navigate to="/batch" replace />;
  }
  return <LazyPage><Batch key={batchMode} /></LazyPage>;
}

export const router = createBrowserRouter([
  { path: '/playground/image-editor', element: <LazyPage><PlaygroundImagePopout /></LazyPage> },
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <LazyPage><Playground /></LazyPage> },
      { path: 'batch', element: <LazyPage><BatchHub /></LazyPage> },
      { path: 'batch/:batchMode', element: <BatchRoute /> },
      { path: 'history', element: <LazyPage><History /></LazyPage> },
      { path: 'jobs', element: <LazyPage><Jobs /></LazyPage> },
      { path: 'jobs/:jobId', element: <LazyPage><JobDetailPage /></LazyPage> },
      { path: 'settings/redaction', element: <LazyPage><RedactionListSettings /></LazyPage> },
      { path: 'settings', element: <LazyPage><Settings /></LazyPage> },
      { path: 'model-settings', element: <Navigate to="/model-settings/text" replace /> },
      { path: 'model-settings/text', element: <LazyPage><TextModelSettings /></LazyPage> },
      { path: 'model-settings/vision', element: <LazyPage><VisionModelSettings /></LazyPage> },
      { path: '*', element: <NotFound /> },
    ],
  },
]);

function NotFound() {
  return (
    <div className="flex h-full min-h-0 items-center justify-center px-6">
      <div className="flex min-h-[320px] w-full max-w-xl flex-col items-center justify-center gap-4 rounded-[28px] border border-border/70 bg-card px-8 py-12 text-center shadow-[0_28px_80px_-44px_rgba(15,23,42,0.24)]">
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
