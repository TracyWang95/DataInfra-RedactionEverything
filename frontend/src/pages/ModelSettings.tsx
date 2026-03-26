/** @deprecated 使用 /model-settings/text 与 /model-settings/vision */
import { Navigate } from 'react-router-dom';

export default function ModelSettingsRedirect() {
  return <Navigate to="/model-settings/text" replace />;
}
