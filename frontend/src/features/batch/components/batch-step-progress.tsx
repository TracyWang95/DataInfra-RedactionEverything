/**
 * BatchStepProgress — 5-step progress indicator for the batch wizard.
 * Displays current/completed/pending states with ShadCN styling.
 */
import { cn } from '@/lib/utils';
import { useT } from '@/i18n';
import { Button } from '@/components/ui/button';
import { type Step, STEPS } from '../hooks/use-batch-wizard';

interface BatchStepProgressProps {
  currentStep: Step;
  canGoStep: (s: Step) => boolean;
  onStepClick: (s: Step) => void;
}

export function BatchStepProgress({
  currentStep,
  canGoStep,
  onStepClick,
}: BatchStepProgressProps) {
  const t = useT();

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
        currentStep === 4 ? 'mb-1' : 'mb-1.5',
      )}
      aria-label={t('batchWizard.stepsOverview')}
      data-testid="batch-step-progress"
    >
      {STEPS.map((s, i) => {
        const reachable = canGoStep(s.n);
        const isCurrent = currentStep === s.n;
        return (
          <div key={s.n} className="flex items-center gap-1.5">
            <Button
              variant={isCurrent ? 'default' : reachable ? 'outline' : 'ghost'}
              size="sm"
              disabled={!reachable && !isCurrent}
              onClick={() => reachable && onStepClick(s.n)}
              className={cn(
                'text-xs font-medium transition-all duration-200',
                isCurrent && 'shadow-sm',
                !reachable && !isCurrent && 'opacity-40 cursor-not-allowed',
              )}
              data-testid={`batch-step-${s.n}`}
            >
              <span className="tabular-nums mr-1">{s.n}</span>
              {labels[s.n]}
            </Button>
            {i < STEPS.length - 1 && (
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
