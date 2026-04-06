import { useEffect, useMemo, useState } from 'react';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { PaginationRail } from '@/components/PaginationRail';
import { getSelectionToneClasses, type SelectionTone } from '@/ui/selectionPalette';
import type { EntityTypeConfig } from '../hooks/use-entity-types';

interface EntityTypeListProps {
  types: EntityTypeConfig[];
  onEdit: (type: EntityTypeConfig) => void;
  onDelete: (id: string) => void;
  onAdd: () => void;
  onReset: () => void;
  variant: 'regex' | 'llm';
}

export function EntityTypeList({
  types,
  onEdit,
  onDelete,
  onAdd,
  onReset,
  variant,
}: EntityTypeListProps) {
  const t = useT();
  const isRegex = variant === 'regex';
  const tone: SelectionTone = isRegex ? 'regex' : 'semantic';
  const toneClasses = getSelectionToneClasses(tone);
  const pageSize = 10;
  const [page, setPage] = useState(1);
  const totalPages = Math.max(1, Math.ceil(types.length / pageSize));

  useEffect(() => {
    setPage(1);
  }, [variant]);

  useEffect(() => {
    setPage(current => Math.min(current, totalPages));
  }, [totalPages]);

  const visibleTypes = useMemo(() => {
    const start = (page - 1) * pageSize;
    return types.slice(start, start + pageSize);
  }, [page, pageSize, types]);

  return (
    <div
      className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden"
      data-testid={`entity-type-list-${variant}`}
    >
      <div
        className="page-surface rounded-[24px] border border-border/70 bg-card shadow-[var(--shadow-control)]"
      >
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border/70 bg-muted/20 px-4 py-3.5">
          <div className="flex min-w-0 items-center gap-2">
            <span className={cn('size-2 shrink-0 rounded-full', toneClasses.dot)} />
            <span className="truncate text-sm font-semibold tracking-[-0.02em]">
              {isRegex ? t('settings.regexRules') : t('settings.aiSemantic')}
            </span>
            <Badge
              variant="secondary"
              className={cn('border border-border/70 bg-background text-xs shadow-sm', toneClasses.badgeText)}
            >
              {types.length}
            </Badge>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={onReset}
              data-testid={`reset-${variant}-types`}
            >
              {t('settings.resetTextRules')}
            </Button>
            <Button
              size="sm"
              onClick={onAdd}
              data-testid={`add-${variant}-type`}
            >
              {t('settings.addNew')}
            </Button>
          </div>
        </div>

        <div className="page-surface-body p-3">
          {types.length === 0 ? (
            <div className="flex min-h-[240px] flex-1 items-center justify-center rounded-[20px] border border-dashed border-border/70 bg-muted/15 px-6 text-center">
              <p className="text-sm text-muted-foreground">{t('settings.noTypeConfig')}</p>
            </div>
          ) : (
            <div className="grid w-full auto-rows-max content-start grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
              {visibleTypes.map(type => (
                <article
                  key={type.id}
                  className="flex min-h-[148px] self-start rounded-[20px] border border-border/70 bg-[var(--surface-control)] px-3.5 py-3.5 shadow-[var(--shadow-sm)] transition-colors hover:border-border"
                >
                  <div className="flex min-w-0 flex-1 flex-col gap-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <span className="block truncate text-sm font-semibold leading-tight text-foreground">
                          {type.name}
                        </span>
                      </div>
                      <div className="flex shrink-0 items-center gap-0.5">
                        <Button
                          size="icon"
                          variant="ghost"
                          className="size-6"
                          onClick={() => onEdit(type)}
                          data-testid={`edit-type-${type.id}`}
                        >
                          <PencilIcon />
                        </Button>
                        {type.id.startsWith('custom_') && (
                          <Button
                            size="icon"
                            variant="ghost"
                            className="size-6 text-destructive hover:text-destructive"
                            onClick={() => onDelete(type.id)}
                            data-testid={`delete-type-${type.id}`}
                          >
                            <TrashIcon />
                          </Button>
                        )}
                      </div>
                    </div>

                    <div className="flex flex-1 flex-col gap-2.5">
                      {isRegex ? (
                        <div className="rounded-2xl border border-border/70 bg-muted/25 px-3 py-2.5">
                          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                            {t('settings.regexLabel')}
                          </p>
                          <code className="mt-1 block break-all text-xs leading-5 text-foreground">
                            {type.regex_pattern ?? '-'}
                          </code>
                        </div>
                      ) : (
                        <div className="rounded-2xl border border-border/70 bg-muted/20 px-3 py-2.5">
                          <p className="line-clamp-3 text-xs leading-5 text-muted-foreground">
                            {type.description || t('settings.semanticDescriptionPlaceholder')}
                          </p>
                        </div>
                      )}

                      <div className="mt-auto flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
                        <span className={cn('size-1.5 rounded-full', toneClasses.dot)} />
                        <span>{isRegex ? t('settings.regex') : t('settings.aiSemantic')}</span>
                        {isRegex && type.use_llm && (
                          <span className="rounded-full border border-border/70 bg-muted/20 px-2 py-0.5">
                            {t('settings.aiSemantic')}
                          </span>
                        )}
                        {type.tag_template && (
                          <span className="rounded-full border border-border/70 bg-muted/20 px-2 py-0.5">
                            {type.tag_template}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>

        {types.length > 0 && (
          <div className="page-surface-footer">
            <PaginationRail
              page={page}
              pageSize={pageSize}
              totalItems={types.length}
              totalPages={totalPages}
              onPageChange={setPage}
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
