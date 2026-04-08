// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useState, useEffect, useCallback } from 'react';
import { useLocation } from 'react-router-dom';
import { Sparkles, Upload, ScanText, ShieldCheck, Layers3 } from 'lucide-react';
import { useT } from '../i18n';
import { STORAGE_KEYS } from '@/constants/storage-keys';
import { getStorageItem, setStorageItem } from '@/lib/storage';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';

type Step = {
  title: string;
  description: string;
  icon: typeof Sparkles;
};

export function OnboardingGuide() {
  const location = useLocation();
  const t = useT();
  const [show, setShow] = useState(false);
  const [step, setStep] = useState(0);

  const steps: Step[] = [
    { title: t('onboarding.step1.title'), description: t('onboarding.step1.desc'), icon: Sparkles },
    { title: t('onboarding.step2.title'), description: t('onboarding.step2.desc'), icon: Upload },
    { title: t('onboarding.step3.title'), description: t('onboarding.step3.desc'), icon: ScanText },
    { title: t('onboarding.step4.title'), description: t('onboarding.step4.desc'), icon: ShieldCheck },
    { title: t('onboarding.step5.title'), description: t('onboarding.step5.desc'), icon: Layers3 },
  ];

  useEffect(() => {
    if (location.pathname !== '/') {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- syncing with external system (route + localStorage)
      setShow(false);
      return;
    }
    setShow(!getStorageItem<boolean>(STORAGE_KEYS.ONBOARDING_COMPLETED, false));
  }, [location.pathname]);

  const finish = useCallback(() => {
    setStorageItem(STORAGE_KEYS.ONBOARDING_COMPLETED, true);
    setShow(false);
  }, []);

  const current = steps[step];
  const isLast = step === steps.length - 1;
  const Icon = current.icon;

  return (
    <Dialog open={show} onOpenChange={(nextOpen) => { if (!nextOpen) finish(); }}>
      <DialogContent
        className="w-full max-w-lg overflow-hidden rounded-[28px] p-0 [&>button]:hidden"
        aria-labelledby="onboarding-title"
      >
        <DialogTitle className="sr-only">{current.title}</DialogTitle>
        <DialogDescription className="sr-only">{current.description}</DialogDescription>
        <div className="h-1.5 bg-muted">
          <div
            className="h-full bg-gradient-to-r from-primary to-accent-500 transition-all duration-500 ease-out"
            style={{ width: `${((step + 1) / steps.length) * 100}%` }}
          />
        </div>

        <div className="space-y-6 p-7">
          <div className="flex items-center justify-between">
            <span className="saas-kicker">
              {step + 1} / {steps.length}
            </span>
            <button
              type="button"
              onClick={finish}
              className="text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              {t('onboarding.skip')}
            </button>
          </div>

          <div className="flex items-start gap-4">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[18px] bg-foreground text-background">
              <Icon className="h-5 w-5" />
            </div>
            <div className="space-y-3">
              <h2 id="onboarding-title" className="text-xl font-semibold tracking-[-0.03em] text-foreground">
                {current.title}
              </h2>
              <p className="text-sm leading-7 text-muted-foreground">
                {current.description}
              </p>
            </div>
          </div>

          <div className="flex items-center justify-between">
            <div className="flex gap-1.5">
              {steps.map((_, index) => (
                <span
                  key={index}
                  className={`h-1.5 rounded-full transition-all ${index === step ? 'w-8 bg-foreground' : 'w-1.5 bg-border'}`}
                />
              ))}
            </div>

            <div className="flex gap-2">
              {step > 0 && (
                <Button variant="outline" onClick={() => setStep((s) => s - 1)}>
                  {t('onboarding.prev')}
                </Button>
              )}
              <Button onClick={isLast ? finish : () => setStep((s) => s + 1)}>
                {isLast ? t('onboarding.start') : t('onboarding.next')}
              </Button>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
