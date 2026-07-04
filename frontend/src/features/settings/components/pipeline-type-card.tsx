// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useT } from '@/i18n';
import { Button } from '@/components/ui/button';
import type { PipelineTypeConfig } from '../hooks/use-entity-types';

interface PipelineTypeCardProps {
  type: PipelineTypeConfig;
  onEdit: () => void;
  onDelete: () => void;
}

export function PipelineTypeCard({ type, onEdit, onDelete }: PipelineTypeCardProps) {
  const t = useT();

  return (
    <article className="flex h-full min-h-0 overflow-hidden rounded-[20px] border border-border/70 bg-[var(--surface-control)] px-3.5 py-3.5 shadow-[var(--shadow-sm)] transition-colors hover:border-border">
      <div className="flex min-w-0 flex-1 flex-col gap-2.5">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <span className="line-clamp-2 text-sm font-semibold leading-5 text-foreground">
              {type.name}
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-0.5">
            <Button
              size="icon"
              variant="ghost"
              className="size-6"
              onClick={onEdit}
              aria-label={t('common.edit')}
              data-testid={`edit-pipeline-${type.id}`}
            >
              <PencilIcon />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              className="size-6 text-destructive hover:text-destructive"
              onClick={onDelete}
              aria-label={t('common.delete')}
              data-testid={`delete-pipeline-${type.id}`}
            >
              <TrashIcon />
            </Button>
          </div>
        </div>

        <div className="min-h-0 flex-1 rounded-xl border border-border/70 bg-muted/25 px-3 py-2.5">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t('settings.cardDescriptionLabel')}
          </p>
          <p className="mt-1 line-clamp-4 text-xs leading-4 text-foreground">
            {type.description || t('settings.semanticDescriptionPlaceholder')}
          </p>
        </div>
      </div>
    </article>
  );
}

function PencilIcon() {
  return (
    <svg className="size-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"
      />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg className="size-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
      />
    </svg>
  );
}
