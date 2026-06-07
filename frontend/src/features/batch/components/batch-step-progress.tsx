// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { cn } from '@/lib/utils';
import { useT } from '@/i18n';
import { type Step } from '../types';

interface BatchStepProgressProps {
  currentStep: Step;
  canGoStep: (s: Step) => boolean;
  goStep: (s: Step) => void;
}

export function BatchStepProgress({ currentStep, canGoStep, goStep }: BatchStepProgressProps) {
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
        'flex shrink-0 flex-nowrap items-center gap-1 overflow-x-auto pb-1',
        currentStep === 4 ? 'mb-0.5' : 'mb-1',
      )}
      aria-label={t('batchWizard.stepsOverview')}
      data-testid="batch-step-progress"
    >
      {stepOrder.map((stepNumber, i) => {
        const canVisit = canGoStep(stepNumber);
        const isCompleted = canVisit && stepNumber < currentStep;
        const isCurrent = currentStep === stepNumber;
        const isLocked = !canVisit;
        const isIdle = canVisit && !isCurrent && !isCompleted;
        const title = isLocked ? t('batchWizard.stepLocked') : labels[stepNumber];
        return (
          <div key={stepNumber} className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              className={cn(
                'inline-flex h-7 items-center rounded-md px-2.5 text-xs font-medium whitespace-nowrap select-none',
                'transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
                isCurrent && 'bg-primary text-primary-foreground shadow-sm',
                isCompleted &&
                  'border border-border/70 bg-background text-foreground hover:border-primary/50 hover:text-primary',
                isIdle &&
                  'border border-border/70 bg-background text-foreground hover:border-primary/50 hover:text-primary',
                isLocked && 'cursor-not-allowed bg-muted/40 text-muted-foreground opacity-40',
              )}
              aria-label={`${labels[stepNumber]} (${stepNumber}/${stepOrder.length})${isLocked ? ` - ${t('batchWizard.stepLocked')}` : ''}`}
              aria-current={isCurrent ? 'step' : undefined}
              disabled={isCurrent || isLocked}
              title={title}
              onClick={() => goStep(stepNumber)}
              data-testid={`batch-step-${stepNumber}`}
            >
              <span className="tabular-nums mr-1">{stepNumber}</span>
              {labels[stepNumber]}
            </button>
            {i < stepOrder.length - 1 && (
              <span className="hidden text-[11px] text-muted-foreground sm:inline" aria-hidden>
                &rarr;
              </span>
            )}
          </div>
        );
      })}
    </nav>
  );
}
