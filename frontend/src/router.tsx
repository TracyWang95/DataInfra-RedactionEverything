import React from 'react';
import { createBrowserRouter, Navigate, useParams } from 'react-router-dom';
import { Layout } from './components/Layout';
import { ErrorBoundary } from './components/ErrorBoundary';

const Playground = React.lazy(() => import('./pages/Playground').then(m => ({ default: m.Playground })));
const Batch = React.lazy(() => import('./pages/Batch').then(m => ({ default: m.Batch })));
const History = React.lazy(() => import('./features/history').then(m => ({ default: m.History })));
const Settings = React.lazy(() => import('./pages/Settings').then(m => ({ default: m.Settings })));
const RedactionListSettings = React.lazy(() => import('./pages/RedactionListSettings').then(m => ({ default: m.RedactionListSettings })));
const TextModelSettings = React.lazy(() => import('./pages/TextModelSettings').then(m => ({ default: m.TextModelSettings })));
const VisionModelSettings = React.lazy(() => import('./pages/VisionModelSettings').then(m => ({ default: m.VisionModelSettings })));
const Jobs = React.lazy(() => import('./features/jobs').then(m => ({ default: m.Jobs })));
const JobDetailPage = React.lazy(() => import('./pages/JobDetail').then(m => ({ default: m.JobDetailPage })));
const BatchHub = React.lazy(() => import('./features/batch/batch-hub').then(m => ({ default: m.BatchHub })));
const PlaygroundImagePopout = React.lazy(() => import('./pages/PlaygroundImagePopout'));

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

// 预加载高频路由（鼠标悬停 sidebar 时已有 chunk，点击即渲染）
const prefetchRoutes = () => {
  import('./pages/Batch');
  import('./pages/History');
  import('./pages/Jobs');
  import('./pages/BatchHub');
};
if (typeof window !== 'undefined') {
  // 空闲时预加载，不阻塞首屏
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

/** 文本 / 图片批量切换路由时强制重挂载，避免步骤、上传队列等状态串线 */
function BatchRoute() {
  const { batchMode } = useParams();
  // 校验路由参数，非法值重定向到批量首页
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
