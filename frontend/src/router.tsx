import { createBrowserRouter, Navigate, useParams } from 'react-router-dom';
import { Layout } from './components/Layout';
import { Playground } from './pages/Playground';
import { Batch } from './pages/Batch';
import { History } from './pages/History';
import { Settings } from './pages/Settings';
import { RedactionListSettings } from './pages/RedactionListSettings';
import { TextModelSettings } from './pages/TextModelSettings';
import { VisionModelSettings } from './pages/VisionModelSettings';
import { Jobs } from './pages/Jobs';
import { JobDetailPage } from './pages/JobDetail';
import { BatchHub } from './pages/BatchHub';

/** 文本 / 图片批量切换路由时强制重挂载，避免步骤、上传队列等状态串线 */
function BatchRoute() {
  const { batchMode } = useParams();
  return <Batch key={batchMode} />;
}

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <Playground /> },
      { path: 'batch', element: <BatchHub /> },
      { path: 'batch/:batchMode', element: <BatchRoute /> },
      { path: 'history', element: <History /> },
      { path: 'jobs', element: <Jobs /> },
      { path: 'jobs/:jobId', element: <JobDetailPage /> },
      { path: 'settings/redaction', element: <RedactionListSettings /> },
      { path: 'settings', element: <Settings /> },
      { path: 'model-settings', element: <Navigate to="/model-settings/text" replace /> },
      { path: 'model-settings/text', element: <TextModelSettings /> },
      { path: 'model-settings/vision', element: <VisionModelSettings /> },
    ],
  },
]);
