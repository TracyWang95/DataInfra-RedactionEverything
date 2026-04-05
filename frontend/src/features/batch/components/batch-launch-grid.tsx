import { ArrowRight, FileText, Layers3, ScanSearch } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import type { BatchLaunchMode } from '../hooks/use-batch-hub';

type LaunchCard = {
  mode: BatchLaunchMode;
  icon: typeof FileText;
  dotClassName: string;
  title: string;
  description: string;
  tags: [string, string];
  summaryLabel: string;
  summaryValue: string;
};

interface BatchLaunchGridProps {
  jobsUnavailable: boolean;
  liveLabel: string;
  previewLabel: string;
  actionLabel: string;
  onOpenMode: (mode: BatchLaunchMode) => void;
  cards: LaunchCard[];
}

export function BatchLaunchGrid({
  jobsUnavailable,
  liveLabel,
  previewLabel,
  actionLabel,
  onOpenMode,
  cards,
}: BatchLaunchGridProps) {
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      {cards.map((card) => {
        const Icon = card.icon;
        return (
          <button
            key={card.mode}
            type="button"
            className="saas-panel group flex h-full flex-col p-5 text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-foreground/15 sm:p-6"
            onClick={() => onOpenMode(card.mode)}
            data-testid={`batch-launch-${card.mode}`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex size-11 shrink-0 items-center justify-center rounded-[18px] bg-foreground text-background">
                <Icon className="h-5 w-5" />
              </div>
              <Badge variant="secondary" className="rounded-full px-2.5 py-0.5 text-[10px] font-medium">
                {jobsUnavailable ? previewLabel : liveLabel}
              </Badge>
            </div>

            <div className="mt-4 flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <span className={cn('size-2 shrink-0 rounded-full', card.dotClassName)} />
                <h3 className="text-base font-semibold tracking-[-0.02em] text-foreground">{card.title}</h3>
              </div>
              <p className="text-sm leading-6 text-muted-foreground">{card.description}</p>
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              {card.tags.map((tag) => (
                <Badge
                  key={tag}
                  variant="outline"
                  className="rounded-full border-border/80 bg-background/80 px-2.5 py-0.5 text-[11px] font-medium"
                >
                  {tag}
                </Badge>
              ))}
            </div>

            <div className="surface-muted mt-5 flex flex-col gap-1.5 px-4 py-3">
              <span className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
                {card.summaryLabel}
              </span>
              <span className="text-sm font-medium leading-6 text-foreground">{card.summaryValue}</span>
            </div>

            <div className="mt-5 flex items-center justify-between text-sm font-medium text-foreground">
              <span>{actionLabel}</span>
              <ArrowRight className="h-4 w-4 shrink-0 -translate-x-1 text-muted-foreground transition-transform duration-200 group-hover:translate-x-0" />
            </div>
          </button>
        );
      })}
    </div>
  );
}

export const batchLaunchIcons = {
  text: FileText,
  image: ScanSearch,
  smart: Layers3,
} as const;
