import { useState } from 'react';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { getSelectionToneClasses, type SelectionTone } from '@/ui/selectionPalette';
import type { PipelineConfig, PipelineTypeConfig } from '../hooks/use-entity-types';

interface PipelineConfigPanelProps {
  pipelines: PipelineConfig[];
  onCreateType: (mode: 'ocr_has' | 'has_image', name: string, desc: string) => Promise<boolean>;
  onUpdateType: (
    mode: string,
    typeId: string,
    update: Partial<PipelineTypeConfig> & { name: string; description?: string },
  ) => Promise<boolean>;
  onDeleteType: (mode: string, typeId: string) => void;
  onReset: () => void;
}

export function PipelineConfigPanel({
  pipelines,
  onCreateType,
  onUpdateType,
  onDeleteType,
  onReset,
}: PipelineConfigPanelProps) {
  const t = useT();
  const [activeSub, setActiveSub] = useState<'ocr_has' | 'has_image'>('ocr_has');
  const [dialogMode, setDialogMode] = useState<'ocr_has' | 'has_image' | null>(null);
  const [editing, setEditing] = useState<{ mode: string; type: PipelineTypeConfig } | null>(null);
  const [form, setForm] = useState({ name: '', description: '' });

  const ocrPipeline = pipelines.find(pipeline => pipeline.mode === 'ocr_has');
  const imagePipeline = pipelines.find(pipeline => pipeline.mode === 'has_image');
  const activePipeline = pipelines.find(pipeline => pipeline.mode === activeSub);
  const ocrLabel = t('settings.pipelineDisplayName.ocr');
  const imageLabel = t('settings.pipelineDisplayName.image');

  const openCreate = (mode: 'ocr_has' | 'has_image') => {
    setEditing(null);
    setForm({ name: '', description: '' });
    setDialogMode(mode);
  };

  const openEdit = (mode: string, type: PipelineTypeConfig) => {
    setEditing({ mode, type: { ...type } });
    setForm({ name: type.name, description: type.description ?? '' });
    setDialogMode(mode as 'ocr_has' | 'has_image');
  };

  const handleSave = async () => {
    if (!dialogMode || !form.name.trim()) return;

    if (editing) {
      await onUpdateType(editing.mode, editing.type.id, {
        name: form.name.trim(),
        description: form.description.trim() || undefined,
        examples: editing.type.examples || [],
        color: editing.type.color || '#6B7280',
        enabled: editing.type.enabled,
        order: editing.type.order,
      });
    } else {
      await onCreateType(dialogMode, form.name, form.description);
    }

    setDialogMode(null);
    setEditing(null);
    setForm({ name: '', description: '' });
  };

  const imageModeActive = activeSub === 'has_image';
  const tone: SelectionTone = imageModeActive ? 'yolo' : 'ner';
  const toneClasses = getSelectionToneClasses(tone);
  const displayName = imageModeActive ? imageLabel : ocrLabel;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden">
      <div className="flex shrink-0 items-center gap-2">
        <div className="flex w-fit gap-1 rounded-md border bg-muted p-0.5">
          <button
            type="button"
            onClick={() => setActiveSub('ocr_has')}
            className={cn(
              'rounded px-2 py-1 text-xs font-medium transition-colors',
              activeSub === 'ocr_has'
                ? 'bg-background text-foreground shadow'
                : 'text-muted-foreground hover:text-foreground',
            )}
            data-testid="pipeline-tab-ocr"
          >
            {ocrLabel}
            <span className="ml-1 text-muted-foreground">({ocrPipeline?.types.length ?? 0})</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveSub('has_image')}
            className={cn(
              'rounded px-2 py-1 text-xs font-medium transition-colors',
              activeSub === 'has_image'
                ? 'bg-background text-foreground shadow'
                : 'text-muted-foreground hover:text-foreground',
            )}
            data-testid="pipeline-tab-image"
          >
            {imageLabel}
            <span className="ml-1 text-muted-foreground">({imagePipeline?.types.length ?? 0})</span>
          </button>
        </div>
      </div>

      {!activePipeline ? (
        <div className="flex min-h-0 flex-1 items-center justify-center rounded-lg border bg-card px-6 py-10 text-center shadow-sm">
          <p className="text-sm text-muted-foreground">
            {t('settings.loadingPipeline')}
          </p>
        </div>
      ) : (
        <div
          className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-[24px] border border-border/70 bg-card shadow-[var(--shadow-control)]"
          data-testid="vision-pipeline-panel"
        >
          <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border/70 bg-muted/20 px-4 py-3">
            <div className="flex min-w-0 items-center gap-2">
              <span className={cn('size-2 shrink-0 rounded-full', toneClasses.dot)} />
              <span className="truncate text-sm font-semibold">{displayName}</span>
              <Badge variant="secondary" className={cn('border border-border/70 bg-background text-xs shadow-sm', toneClasses.badgeText)}>
                {activePipeline.types.length}
              </Badge>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <Button size="sm" variant="outline" onClick={onReset} data-testid="reset-pipelines">
                {t('settings.resetVisionRules')}
              </Button>
              <Button size="sm" onClick={() => openCreate(activeSub)} data-testid="add-pipeline-type">
                {t('settings.addNew')}
              </Button>
            </div>
          </div>

          <div className="flex min-h-0 flex-1 overflow-y-auto p-3">
            {activePipeline.types.length === 0 ? (
              <div className="flex min-h-[240px] flex-1 items-center justify-center rounded-[20px] border border-dashed border-border/70 bg-muted/15 px-6 text-center">
                <p className="text-sm text-muted-foreground">
                  {t('settings.noTypeConfig')}
                </p>
              </div>
            ) : (
              <div className="grid w-full auto-rows-max content-start grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {activePipeline.types.map(type => (
                  <div
                    key={type.id}
                    className="flex min-h-[132px] self-start rounded-[20px] border border-border/70 bg-[var(--surface-control)] px-3 py-3 shadow-[var(--shadow-sm)] transition-colors hover:border-border"
                  >
                    <div className="flex min-w-0 flex-1 flex-col gap-3">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <span className="block truncate text-xs font-semibold leading-tight text-foreground">
                            {type.name}
                          </span>
                          <span className={cn('mt-1 inline-flex max-w-full items-center rounded-full border px-2 py-0.5 text-[10px]', toneClasses.cardSelectedCompact)}>
                            <span className="truncate">{type.id}</span>
                          </span>
                        </div>
                        <div className="flex shrink-0 items-center gap-0.5">
                          <Button
                            size="icon"
                            variant="ghost"
                            className="size-6"
                            onClick={() => openEdit(activePipeline.mode, type)}
                            data-testid={`edit-pipeline-${type.id}`}
                          >
                            <PencilIcon />
                          </Button>
                          <Button
                            size="icon"
                            variant="ghost"
                            className="size-6 text-destructive hover:text-destructive"
                            onClick={() => onDeleteType(activePipeline.mode, type.id)}
                            data-testid={`delete-pipeline-${type.id}`}
                          >
                            <TrashIcon />
                          </Button>
                        </div>
                      </div>
                      <div className="mt-auto space-y-2">
                        {type.description && (
                          <p className="line-clamp-2 text-[11px] leading-5 text-muted-foreground">
                            {type.description}
                          </p>
                        )}
                        <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                          <span className={cn('size-1.5 rounded-full', toneClasses.dot)} />
                          <span>{displayName}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      <Dialog
        open={dialogMode !== null}
        onOpenChange={nextOpen => {
          if (!nextOpen) {
            setDialogMode(null);
            setEditing(null);
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{editing ? t('settings.editType') : t('settings.addType')}</DialogTitle>
            <DialogDescription>
              {dialogMode === 'ocr_has' ? t('settings.pipelineTypeDescOcr') : t('settings.pipelineTypeDescImg')}
            </DialogDescription>
          </DialogHeader>

          <div className="flex flex-col gap-4 py-2">
            <div className="flex flex-col gap-1.5">
              <Label>{t('settings.nameLabel')} *</Label>
              <Input
                value={form.name}
                onChange={event => setForm(current => ({ ...current, name: event.target.value }))}
                placeholder={dialogMode === 'ocr_has'
                  ? t('settings.pipelineNamePlaceholder.ocr')
                  : t('settings.pipelineNamePlaceholder.image')}
                data-testid="pipeline-type-name"
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label>{t('settings.descLabel')}</Label>
              <Textarea
                value={form.description}
                onChange={event => setForm(current => ({ ...current, description: event.target.value }))}
                rows={3}
                data-testid="pipeline-type-desc"
              />
            </div>

            <p className="text-xs text-muted-foreground">{t('settings.saveHint')}</p>
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setDialogMode(null);
                setEditing(null);
              }}
              data-testid="pipeline-type-cancel"
            >
              {t('settings.cancel')}
            </Button>
            <Button disabled={!form.name.trim()} onClick={() => void handleSave()} data-testid="pipeline-type-save">
              {editing ? t('settings.save') : t('settings.create')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
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
