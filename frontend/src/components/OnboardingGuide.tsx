// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useState, useEffect, useCallback } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { ArrowRight, Layers3, Upload, X } from 'lucide-react';
import { useT } from '../i18n';
import { STORAGE_KEYS } from '@/constants/storage-keys';
import { getStorageItem, setStorageItem } from '@/lib/storage';
import { Button } from '@/components/ui/button';

const ONBOARDING_ROUTES = new Set(['/batch']);

export function OnboardingGuide() {
  const location = useLocation();
  const t = useT();
  const [show, setShow] = useState(false);
  const shouldOfferOnboarding = ONBOARDING_ROUTES.has(location.pathname);
  const isBatchEntry = location.pathname === '/batch';

  useEffect(() => {
    if (
      !shouldOfferOnboarding ||
      getStorageItem<boolean>(STORAGE_KEYS.ONBOARDING_COMPLETED, false)
    ) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- syncing with external system (route + localStorage)
      setShow(false);
      return;
    }
    const timer = window.setTimeout(() => {
      setShow(true);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [shouldOfferOnboarding]);

  const finish = useCallback(() => {
    setStorageItem(STORAGE_KEYS.ONBOARDING_COMPLETED, true);
    setShow(false);
  }, []);

  if (!show || !shouldOfferOnboarding) return null;

  return (
    <aside
      role="complementary"
      aria-labelledby="onboarding-title"
      className="fixed bottom-4 right-4 z-40 w-[calc(100vw-2rem)] max-w-[22rem] rounded-2xl border border-border/80 bg-background/95 p-3 shadow-[var(--shadow-lg)] backdrop-blur md:bottom-5 md:right-5"
    >
      <div className="flex items-start gap-2.5">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-foreground text-background">
          <Upload className="h-3.5 w-3.5" />
        </div>
        <div className="min-w-0 flex-1 space-y-2.5">
          <div className="flex items-start justify-between gap-2">
            <div className="space-y-1">
              <p className="saas-kicker">{t('onboarding.step1.title')}</p>
              <h2 id="onboarding-title" className="text-base font-semibold text-foreground">
                {t('onboarding.step2.title')}
              </h2>
            </div>
            <button
              type="button"
              onClick={finish}
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              aria-label={t('onboarding.skip')}
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <p className="text-sm leading-5 text-muted-foreground">{t('onboarding.step2.desc')}</p>

          <div className="flex items-start gap-2 rounded-xl bg-muted/60 p-2.5 text-sm leading-5 text-muted-foreground">
            <Layers3 className="h-4 w-4 shrink-0 text-foreground" />
            <span>{t('onboarding.step5.desc')}</span>
          </div>

          <div className="flex flex-wrap justify-end gap-2">
            {isBatchEntry && (
              <Button asChild size="sm" onClick={finish}>
                <Link to="/single">
                  {t('start.entry.playground.cta')}
                  <ArrowRight className="h-4 w-4" />
                </Link>
              </Button>
            )}
            {!isBatchEntry && (
              <Button size="sm" onClick={finish}>
                {t('onboarding.start')}
              </Button>
            )}
          </div>
        </div>
      </div>
    </aside>
  );
}
