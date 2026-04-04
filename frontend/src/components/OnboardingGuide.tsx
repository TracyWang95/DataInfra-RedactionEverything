import { useState, useEffect, useCallback } from 'react';
import { useLocation } from 'react-router-dom';
import { Sparkles, Upload, ScanText, ShieldCheck, Layers3 } from 'lucide-react';
import { useT } from '../i18n';
import { Button } from '@/components/ui/button';

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
      setShow(false);
      return;
    }
    try {
      setShow(!localStorage.getItem('onboarding_completed'));
    } catch {
      setShow(false);
    }
  }, [location.pathname]);

  const finish = useCallback(() => {
    try {
      localStorage.setItem('onboarding_completed', 'true');
    } catch {
      // ignore
    }
    setShow(false);
  }, []);

  useEffect(() => {
    if (!show) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') finish();
    };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [show, finish]);

  if (!show) return null;

  const current = steps[step];
  const isLast = step === steps.length - 1;
  const Icon = current.icon;

  return (
    <div
      className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/45 p-4 backdrop-blur-md"
      role="dialog"
      aria-modal="true"
      aria-labelledby="onboarding-title"
    >
      <div className="w-full max-w-lg overflow-hidden rounded-[28px] border border-white/15 bg-popover shadow-[0_48px_120px_-56px_rgba(15,23,42,0.6)]">
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
      </div>
    </div>
  );
}
