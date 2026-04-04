import { useState, useEffect } from 'react';
import { WifiOff } from 'lucide-react';

export function OfflineBanner() {
  const [offline, setOffline] = useState(!navigator.onLine);

  useEffect(() => {
    const goOffline = () => setOffline(true);
    const goOnline = () => setOffline(false);
    window.addEventListener('offline', goOffline);
    window.addEventListener('online', goOnline);
    return () => {
      window.removeEventListener('offline', goOffline);
      window.removeEventListener('online', goOnline);
    };
  }, []);

  if (!offline) return null;

  return (
    <div className="fixed inset-x-0 top-0 z-[9999] animate-slide-down border-b border-amber-500/20 bg-[#1f1710] py-2 text-center text-sm font-medium text-amber-100 shadow-lg">
      <span className="inline-flex items-center gap-2">
        <WifiOff className="h-4 w-4" />
        网络已断开，部分功能暂时不可用
      </span>
    </div>
  );
}
