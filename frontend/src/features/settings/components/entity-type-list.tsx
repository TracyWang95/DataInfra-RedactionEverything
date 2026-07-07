// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useEffect, useMemo, useState } from 'react';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { PaginationRail } from '@/components/PaginationRail';
import { getSelectionToneClasses, type SelectionTone } from '@/ui/selectionPalette';
import { getEntityTypeName } from '@/config/entityTypes';
import type { EntityTypeConfig } from '../hooks/use-entity-types';

const RECOGNITION_PAGE_SIZE = 9;

interface EntityTypeListProps {
  types: EntityTypeConfig[];
  onEdit: (type: EntityTypeConfig) => void;
  onDelete: (id: string) => void;
  onAdd: () => void;
  onReset: () => void;
  variant: 'regex' | 'llm';
  compact?: boolean;
}

export function EntityTypeList({
  types,
  onEdit,
  onDelete,
  onAdd,
  onReset,
  variant,
  compact = false,
}: EntityTypeListProps) {
  const t = useT();
  const isRegex = variant === 'regex';
  const tone: SelectionTone = isRegex ? 'regex' : 'semantic';
  const toneClasses = getSelectionToneClasses(tone);
  const panelTitle = isRegex ? t('settings.customFallbackRules') : t('settings.hasTextRules');
  const addLabel = t('settings.addNew');
  const [page, setPage] = useState(1);
  const totalPages = Math.max(1, Math.ceil(types.length / RECOGNITION_PAGE_SIZE));

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- resetting pagination when variant changes
    setPage(1);
  }, [variant]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- clamping page to valid range when total changes
    setPage((current) => Math.min(current, totalPages));
  }, [totalPages]);

  const visibleTypes = useMemo(() => {
    const start = (page - 1) * RECOGNITION_PAGE_SIZE;
    return types.slice(start, start + RECOGNITION_PAGE_SIZE);
  }, [page, types]);

  return (
    <div
      className={cn(
        'flex min-h-0 w-full flex-col gap-2.5 overflow-hidden',
        compact ? 'shrink-0' : 'flex-1',
      )}
      data-testid={`entity-type-list-${variant}`}
    >
      <div className="page-surface w-full rounded-[20px] border border-border/70 bg-card shadow-[var(--shadow-control)]">
        <div className="grid shrink-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-border/70 bg-muted/20 px-4 py-2.5">
          <div className="flex min-w-0 items-center gap-2">
            <span className={cn('size-2 shrink-0 rounded-full', toneClasses.dot)} />
            <span className="truncate text-sm font-semibold tracking-normal">{panelTitle}</span>
            <Badge
              variant="secondary"
              className={cn(
                'border border-border/70 bg-background text-xs shadow-sm',
                toneClasses.badgeText,
              )}
            >
              {types.length}
            </Badge>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              className="h-8 whitespace-nowrap"
              onClick={onReset}
              data-testid={`reset-${variant}-types`}
            >
              {t('settings.resetTextRules')}
            </Button>
            <Button
              size="sm"
              className="h-8 whitespace-nowrap"
              onClick={onAdd}
              data-testid={`add-${variant}-type`}
            >
              {addLabel}
            </Button>
          </div>
        </div>

        <div className={cn('page-surface-body flex overflow-hidden', compact ? 'p-2.5' : 'p-3')}>
          {types.length === 0 ? (
            <div
              className={cn(
                'flex flex-1 items-center justify-center rounded-[20px] border border-dashed border-border/70 bg-muted/15 px-6 text-center',
                compact ? 'min-h-[64px]' : 'min-h-[240px]',
              )}
            >
              <p className="text-sm leading-6 text-muted-foreground">
                {isRegex ? t('settings.redaction.regexEmptyInline') : t('settings.noTypeConfig')}
              </p>
            </div>
          ) : (
            <div
              className={cn(
                'grid w-full gap-3',
                compact
                  ? 'grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 xl:grid-rows-3'
                  : 'h-full min-h-0 flex-1 grid-cols-1 grid-rows-3 sm:grid-cols-2 xl:grid-cols-3',
              )}
            >
              {visibleTypes.map((type) => {
                const systemManaged = !type.id.startsWith('custom_');
                return (
                  <article
                    key={type.id}
                    className={cn(
                      'flex overflow-hidden rounded-[20px] border border-border/70 bg-[var(--surface-control)] px-3.5 py-3.5 shadow-[var(--shadow-sm)] transition-colors hover:border-border',
                      compact ? 'h-[112px]' : 'h-full min-h-0',
                    )}
                  >
                  <div className="flex min-w-0 flex-1 flex-col gap-2.5">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <span className="line-clamp-2 text-sm font-semibold leading-5 text-foreground">
                          {systemManaged ? getEntityTypeName(type.id) : type.name}
                        </span>
                        {systemManaged && (
                          <span className="mt-1 inline-flex rounded-md border border-border/70 bg-muted/40 px-1.5 py-0.5 text-xs text-muted-foreground">
                            {t('settings.entityList.systemManaged')}
                          </span>
                        )}
                      </div>
                      <div className="flex shrink-0 items-center gap-0.5">
                        <Button
                          size="icon"
                          variant="ghost"
                          className="size-6"
                          disabled={systemManaged}
                          onClick={() => onEdit(type)}
                          aria-label={t('common.edit')}
                          data-testid={`edit-type-${type.id}`}
                        >
                          <PencilIcon />
                        </Button>
                        <Button
                          size="icon"
                          variant="ghost"
                          className="size-6 text-destructive hover:text-destructive"
                          disabled={systemManaged}
                          onClick={() => onDelete(type.id)}
                          aria-label={t('common.delete')}
                          data-testid={`delete-type-${type.id}`}
                        >
                          <TrashIcon />
                        </Button>
                      </div>
                    </div>

                    <div className="min-h-0 flex-1 rounded-xl border border-border/70 bg-muted/25 px-3 py-2.5">
                      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        {isRegex ? t('settings.matchExpression') : t('settings.cardDescriptionLabel')}
                      </p>
                      {isRegex ? (
                        <code className="mt-1 block line-clamp-3 break-all text-xs leading-4 text-foreground">
                          {type.regex_pattern ?? '-'}
                        </code>
                      ) : (
                        <p className="mt-1 line-clamp-4 text-xs leading-4 text-foreground">
                          {type.description || t('settings.semanticDescriptionPlaceholder')}
                        </p>
                      )}
                    </div>
                  </div>
                  </article>
                );
              })}
            </div>
          )}
        </div>

        {types.length > 0 && (
          <div className="page-surface-footer">
            <PaginationRail
              page={page}
              pageSize={RECOGNITION_PAGE_SIZE}
              totalItems={types.length}
              totalPages={totalPages}
              onPageChange={setPage}
              compact
            />
          </div>
        )}
      </div>
    </div>
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
