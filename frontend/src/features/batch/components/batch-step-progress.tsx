// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0


import { cn } from '@/lib/utils';
import { useT } from '@/i18n';
import { type Step } from '../types';

interface BatchStepProgressProps {
  currentStep: Step;
  canGoStep: (s: Step) => boolean;
  /** @deprecated Step indicators are now display-only; navigation is via prev/next buttons only. */
  onStepClick?: (s: Step) => void;
}

export function BatchStepProgress({
  currentStep,
  canGoStep,
}: BatchStepProgressProps) {
  const t = useT();
  const stepOrder: Step[] = [1, 2, 3, 4, 5];

  const labels: Record<Step, string> = {
    1: t('batchWizard.step1'),
    2: t('batchWizard.step2'),
    3: t('batchWizard.step3'),
    4: t('batchWizard.step4'),
    5: t('batchWizard.step5'),
  };

  return (
    <nav
      className={cn(
        'flex flex-wrap items-center gap-1.5 shrink-0',
        currentStep === 4 ? 'mb-0.5' : 'mb-1',
      )}
      aria-label={t('batchWizard.stepsOverview')}
      data-testid="batch-step-progress"
    >
      {stepOrder.map((stepNumber, i) => {
        const isCompleted = canGoStep(stepNumber) && stepNumber < currentStep;
        const isCurrent = currentStep === stepNumber;
        const isUpcoming = !isCurrent && !isCompleted;
        return (
          <div key={stepNumber} className="flex items-center gap-1.5">
            <span
              className={cn(
                'inline-flex items-center rounded-md px-3 py-1.5 text-xs font-medium select-none',
                'transition-colors duration-200',
                isCurrent && 'bg-primary text-primary-foreground shadow-sm',
                isCompleted && 'border border-border/70 bg-background text-foreground',
                isUpcoming && 'bg-muted/40 text-muted-foreground opacity-40',
              )}
              aria-label={`${labels[stepNumber]} (${stepNumber}/${stepOrder.length})`}
              aria-current={isCurrent ? 'step' : undefined}
              data-testid={`batch-step-${stepNumber}`}
            >
              <span className="tabular-nums mr-1">{stepNumber}</span>
              {labels[stepNumber]}
            </span>
            {i < stepOrder.length - 1 && (
              <span className="text-muted-foreground hidden sm:inline" aria-hidden>
                &rarr;
              </span>
            )}
          </div>
        );
      })}
    </nav>
  );
}
