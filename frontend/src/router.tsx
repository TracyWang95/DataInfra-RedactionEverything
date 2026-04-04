import React from 'react';
import { createBrowserRouter, Navigate, useParams } from 'react-router-dom';
import { Layout } from './components/Layout';
import { ErrorBoundary } from './components/ErrorBoundary';

// All pages now load from features/ modules
const Playground = React.lazy(() => import('./features/playground').then(m => ({ default: m.Playground })));
const Batch = React.lazy(() => import('./features/batch').then(m => ({ default: m.Batch })));
const BatchHub = React.lazy(() => import('./features/batch').then(m => ({ default: m.BatchHub })));
const History = React.lazy(() => import('./features/history').then(m => ({ default: m.History })));
const Jobs = React.lazy(() => import('./features/jobs').then(m => ({ default: m.Jobs })));
const JobDetailPage = React.lazy(() => import('./pages/JobDetail').then(m => ({ default: m.JobDetailPage })));
const Settings = React.lazy(() => import('./features/settings').then(m => ({ default: m.Settings })));
const RedactionListSettings = React.lazy(() => import('./features/settings').then(m => ({ default: m.RedactionListSettings })));
const TextModelSettings = React.lazy(() => import('./features/settings').then(m => ({ default: m.TextModelSettings })));
const VisionModelSettings = React.lazy(() => import('./features/settings').then(m => ({ default: m.VisionModelSettings })));
const PlaygroundImagePopout = React.lazy(() => import('./features/playground/components/playground-image-popout').then(m => ({ default: m.PlaygroundImagePopout })));

/** 延迟 150ms 再显示 spinner，已缓存的 chunk 在此期间就能渲染完毕，避免闪烁 */
function DelayedSpinner() {
  const [show, setShow] = React.useState(false);
  React.useEffect(() => {
    const t = setTimeout(() => setShow(true), 150);
    return () => clearTimeout(t);
  }, []);
  if (!show) return null;
  return (
    <div className="flex items-center justify-center h-full animate-fade-in">
      <div className="w-7 h-7 border-2 border-[#e5e5e5] border-t-[#1d1d1f] rounded-full animate-spin" />
    </div>
  );
}
const SuspenseFallback = <DelayedSpinner />;

// 预加载高频路由
const prefetchRoutes = () => {
  import('./features/batch');
  import('./features/history');
  import('./features/jobs');
};
if (typeof window !== 'undefined') {
  if ('requestIdleCallback' in window) {
    (window as any).requestIdleCallback(prefetchRoutes);
  } else {
    setTimeout(prefetchRoutes, 2000);
  }
}

function LazyPage({ children }: { children: React.ReactNode }) {
  return (
    <ErrorBoundary>
      <React.Suspense fallback={SuspenseFallback}>
        {children}
      </React.Suspense>
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
    <div className="flex flex-col items-center justify-center h-full gap-4 text-gray-500">
      <span className="text-5xl font-bold text-gray-300">404</span>
      <p className="text-sm">页面不存在</p>
      <a href="/" className="text-sm text-blue-600 hover:underline">返回首页</a>
    </div>
  );
}
