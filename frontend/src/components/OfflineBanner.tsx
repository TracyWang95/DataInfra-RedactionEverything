// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useState } from 'react';
import { WifiOff } from 'lucide-react';
import { useT } from '@/i18n';

export function OfflineBanner() {
  const t = useT();
  const [offline, setOffline] = useState(() =>
    typeof navigator !== 'undefined' ? !navigator.onLine : false,
  );

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
    <div className="pointer-events-none fixed inset-x-0 top-3 z-[9999] flex justify-center px-4">
      <div className="pointer-events-auto inline-flex max-w-full items-center gap-2 rounded-full border border-[var(--warning-border)] bg-[var(--warning-surface)] px-4 py-2 text-sm font-medium text-[var(--warning-foreground)] shadow-[var(--shadow-control)] backdrop-blur-xl">
        <WifiOff className="h-4 w-4 shrink-0" />
        <span className="truncate">{t('offline.banner')}</span>
      </div>
    </div>
  );
}
