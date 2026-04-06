import { type FC, useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { PaginationRail } from '@/components/PaginationRail';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useServiceHealth } from '@/hooks/use-service-health';
import { getEntityTypeName } from '@/config/entityTypes';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { getSelectionToneClasses, type SelectionTone } from '@/ui/selectionPalette';
import type { usePlayground } from '../hooks/use-playground';

type PlaygroundCtx = ReturnType<typeof usePlayground>;
type RecognitionCtx = PlaygroundCtx['recognition'];
const DEFAULT_PRESET_VALUE = '__default__';

interface PlaygroundUploadProps {
  ctx: PlaygroundCtx;
}

export const PlaygroundUpload: FC<PlaygroundUploadProps> = ({ ctx }) => {
  const t = useT();
  const { health } = useServiceHealth();
  const { dropzone, recognition: rec } = ctx;
  const { getRootProps, getInputProps, isDragActive } = dropzone;
  const backendUnavailable = !health;

  return (
    <div
      className="grid h-full min-h-0 min-w-0 flex-1 grid-cols-1 gap-3 overflow-hidden lg:h-[calc(100vh-7.5rem)] lg:grid-cols-[minmax(0,1.08fr)_minmax(21.5rem,25.5rem)] lg:items-stretch lg:gap-4 xl:h-[calc(100vh-7.75rem)] xl:grid-cols-[minmax(0,1.14fr)_minmax(22.5rem,27rem)] 2xl:h-[calc(100vh-8rem)] 2xl:grid-cols-[minmax(0,1.2fr)_minmax(23.5rem,28.5rem)]"
      data-testid="playground-upload"
    >
      <div className="flex min-h-0 min-w-0 flex-1 items-stretch justify-center">
        <div className="flex h-full w-full max-w-[56rem] flex-col items-center pt-0.5 text-center lg:pt-1">
          <div className="mb-3 flex w-full max-w-3xl flex-col items-center gap-1.5">
            <span className="saas-kicker">{t('playground.upload.kicker')}</span>
            <div className="flex flex-col items-center">
              <h2 className="text-[1.85rem] font-semibold tracking-[-0.045em] text-foreground lg:text-[1.95rem]">
                {t('playground.upload.title')}
              </h2>
              <p className="mt-1.5 max-w-2xl text-sm leading-6 text-muted-foreground">
                {t('playground.upload.desc')}
              </p>
            </div>
          </div>

          <div
            {...getRootProps()}
            className={cn(
              'saas-hero group relative min-h-[18rem] flex-1 w-full cursor-pointer border-2 border-dashed p-10 text-center transition-all duration-300 ease-out lg:px-12',
              isDragActive
                ? 'border-primary bg-primary/[0.04] ring-4 ring-primary/10'
                : 'border-border hover:border-foreground/15 hover:shadow-lg',
            )}
            data-testid="playground-dropzone"
          >
            <input {...getInputProps()} className="sr-only" />
            <div className="flex h-full flex-col items-center justify-center">
              <div
                className={cn(
                  'mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-[20px] bg-foreground text-background transition-transform duration-300 group-hover:scale-110',
                  isDragActive && 'scale-110 animate-pulse',
                )}
              >
                <svg className="h-8 w-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
              </div>
              <p className="mb-1.5 text-lg font-semibold tracking-[-0.02em]">
                {t('playground.dropHere')}
              </p>
              <p className="mb-5 text-sm text-muted-foreground">
                {t('playground.supportedFormats')}
              </p>
              <div className="inline-flex items-center gap-2 rounded-full border border-border/70 bg-card px-4 py-2 text-xs font-medium text-foreground">
                <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                {t('playground.clickToUpload')}
              </div>
            </div>
          </div>
        </div>
      </div>

      <Card
        className="page-surface w-full shrink-0 overflow-hidden border-border/70 bg-card lg:h-full lg:max-h-full lg:self-stretch"
        data-testid="playground-type-panel"
      >
        <Tabs
          value={rec.typeTab}
          onValueChange={(value) => rec.setTypeTab(value as 'text' | 'vision')}
          className="flex h-full min-h-0 flex-col"
        >
          <div className="space-y-2 border-b border-border/70 px-3.5 py-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold tracking-tight text-foreground">
                  {t('playground.recognitionTypes')}
                </h3>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  {t('playground.upload.configDesc')}
                </p>
              </div>
              <TabsList className="h-8 rounded-full border border-border/70 bg-muted/35 p-1">
                <TabsTrigger
                  value="text"
                  className="rounded-full px-3 py-1 text-xs"
                  data-testid="playground-tab-text"
                >
                  {t('playground.text')}
                  <span className="ml-1 tabular-nums text-[10px] text-muted-foreground">
                    {rec.entityTypes.length}
                  </span>
                </TabsTrigger>
                <TabsTrigger
                  value="vision"
                  className="rounded-full px-3 py-1 text-xs"
                  data-testid="playground-tab-vision"
                >
                  {t('playground.vision')}
                  <span className="ml-1 tabular-nums text-[10px] text-muted-foreground">
                    {rec.visionTypes.length}
                  </span>
                </TabsTrigger>
              </TabsList>
            </div>
            <PresetSelectors rec={rec} disabledText={rec.textConfigState !== 'ready'} disabledVision={rec.visionConfigState !== 'ready'} />
            {backendUnavailable && (
              <div
                className="rounded-2xl border border-[var(--warning-border)] bg-[var(--warning-surface)] px-3 py-2 text-xs text-[var(--warning-foreground)]"
                data-testid="playground-offline-hint"
              >
                {t('playground.upload.offlineHint')}
              </div>
            )}
          </div>

          <div className="page-surface-body flex min-h-0 flex-1 flex-col overflow-hidden">
            <TabsContent value="text" className="mt-0 min-h-full flex-col gap-2 p-2 pb-0 data-[state=active]:flex 2xl:p-2.5 2xl:pb-0">
              <div className="rounded-[18px] border border-border/70 bg-muted/20 px-3 py-2">
                <p className="text-sm font-semibold tracking-[-0.02em] text-foreground">
                  {t('playground.text')}
                </p>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  {rec.selectedTypes.length} / {rec.entityTypes.length} {t('playground.selected')}
                </p>
              </div>
              <TextTypeGroups rec={rec} />
            </TabsContent>
            <TabsContent value="vision" className="mt-0 min-h-full flex-col gap-2 p-2 pb-0 data-[state=active]:flex 2xl:p-2.5 2xl:pb-0">
              <div className="rounded-[18px] border border-border/70 bg-muted/20 px-3 py-2">
                <p className="text-sm font-semibold tracking-[-0.02em] text-foreground">
                  {t('playground.vision')}
                </p>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  {t('playground.ocrShort')} {rec.selectedOcrHasTypes.length} / {rec.pipelines.find((pipeline) => pipeline.mode === 'ocr_has')?.types.length ?? 0}
                  <span className="mx-2 text-border">·</span>
                  {t('playground.imageShort')} {rec.selectedHasImageTypes.length} / {rec.pipelines.find((pipeline) => pipeline.mode === 'has_image')?.types.length ?? 0}
                </p>
              </div>
              <VisionPipelines rec={rec} />
            </TabsContent>
          </div>

          <div className="page-surface-footer !bg-transparent !backdrop-blur-none" style={{ padding: '0.125rem 1rem 0.25rem' }}>
            <p className="text-center text-xs leading-none text-muted-foreground" data-testid="playground-type-summary">
              {rec.typeTab === 'vision'
                ? `${t('playground.ocrShort')} ${rec.selectedOcrHasTypes.length} / ${t('playground.imageShort')} ${rec.selectedHasImageTypes.length}`
                : `${rec.selectedTypes.length} / ${rec.entityTypes.length} ${t('playground.selected')}`}
            </p>
          </div>
        </Tabs>
      </Card>
      <PresetSaveDialog rec={rec} />
    </div>
  );
};

const PresetSelectors: FC<{
  rec: RecognitionCtx;
  disabledText: boolean;
  disabledVision: boolean;
}> = ({ rec, disabledText, disabledVision }) => {
  const t = useT();

  return (
    <div className="flex flex-col gap-2.5">
      <PresetRow
        label={t('playground.textPresetLabel')}
        presets={rec.textPresetsPg}
        activeId={rec.playgroundPresetTextId}
        onSelect={rec.selectPlaygroundTextPresetById}
        onSave={rec.openTextPresetDialog}
        saveLabel={t('playground.saveAsTextPreset')}
        disabled={disabledText}
      />
      <PresetRow
        label={t('playground.visionPresetLabel')}
        presets={rec.visionPresetsPg}
        activeId={rec.playgroundPresetVisionId}
        onSelect={rec.selectPlaygroundVisionPresetById}
        onSave={rec.openVisionPresetDialog}
        saveLabel={t('playground.saveAsVisionPreset')}
        disabled={disabledVision}
      />
    </div>
  );
};

const PresetRow: FC<{
  label: string;
  presets: { id: string; name: string; kind?: string }[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onSave: () => void;
  saveLabel: string;
  disabled: boolean;
}> = ({ label, presets, activeId, onSelect, onSave, saveLabel, disabled }) => {
  const t = useT();

  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] font-medium text-muted-foreground">{label}</span>
      <div className="flex min-w-0 items-center gap-2">
        <Select
          value={activeId ?? DEFAULT_PRESET_VALUE}
          onValueChange={(value) => onSelect(value === DEFAULT_PRESET_VALUE ? '' : value)}
          disabled={disabled}
        >
          <SelectTrigger
            className="h-9 min-w-0 flex-1 rounded-xl border-border/70 px-3 text-xs"
            data-testid="playground-preset-select"
          >
            <SelectValue placeholder={t('playground.defaultPreset')} />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value={DEFAULT_PRESET_VALUE}>{t('playground.defaultPreset')}</SelectItem>
              {presets.map((preset) => (
                <SelectItem key={preset.id} value={preset.id}>
                  {preset.name}
                  {preset.kind === 'full' ? ` (${t('playground.fullPreset')})` : ''}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Button
          variant="outline"
          size="sm"
          className="h-9 shrink-0 rounded-xl px-3 text-xs"
          onClick={() => void onSave()}
          disabled={disabled}
        >
          {saveLabel}
        </Button>
      </div>
    </div>
  );
};

const TextTypeGroups: FC<{ rec: RecognitionCtx }> = ({ rec }) => {
  const t = useT();
  const [groupPages, setGroupPages] = useState<Record<string, number>>({});
  const pageSize = 15;

  useEffect(() => {
    setGroupPages((current) => {
      const next = { ...current };
      rec.playgroundTextGroups.forEach((group) => {
        const totalPages = Math.max(1, Math.ceil(group.types.length / pageSize));
        next[group.key] = Math.min(next[group.key] ?? 1, totalPages);
      });
      return next;
    });
  }, [pageSize, rec.playgroundTextGroups]);

  if (rec.textConfigState === 'loading') {
    return <p className="py-10 text-center text-sm text-muted-foreground">{t('playground.loading')}</p>;
  }

  if (rec.textConfigState === 'unavailable') {
    return (
      <ConfigEmptyState
        title={t('playground.textConfigUnavailableTitle')}
        description={t('playground.textConfigUnavailableDesc')}
      />
    );
  }

  if (rec.textConfigState === 'empty' || rec.playgroundTextGroups.length === 0) {
    return (
      <ConfigEmptyState
        title={t('playground.textConfigEmptyTitle')}
        description={t('playground.textConfigEmptyDesc')}
      />
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      {rec.playgroundTextGroups.map((group) => {
        const ids = group.types.map((type) => type.id);
        const allOn = ids.length > 0 && ids.every((id) => rec.selectedTypes.includes(id));
        const toneClasses = getSelectionToneClasses(group.tone);
        const totalPages = Math.max(1, Math.ceil(group.types.length / pageSize));
        const page = groupPages[group.key] ?? 1;
        const visibleTypes = group.types.slice((page - 1) * pageSize, page * pageSize);
        const isFullPage = visibleTypes.length === pageSize;

        return (
          <section
            key={group.key}
            className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-[20px] border border-border/70 bg-[var(--surface-control)] shadow-[var(--shadow-sm)]"
            data-testid={`playground-text-group-${group.key}`}
          >
            <div className={cn('flex items-center justify-between gap-2 border-b px-3 py-2', toneClasses.headerSurface)}>
              <div className="flex min-w-0 items-center gap-2">
                <span className={cn('size-2 rounded-full', toneClasses.dot)} />
                <span className={cn('truncate text-xs font-semibold tracking-[0.02em]', toneClasses.titleText)}>
                  {group.label}
                </span>
                <Badge
                  variant="secondary"
                  className={cn('rounded-full border bg-background/85 px-2 py-0.5 text-[10px] shadow-none', toneClasses.badgeText)}
                >
                  {group.types.length}
                </Badge>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="h-6.5 rounded-full px-2 text-[10px]"
                onClick={() => rec.setPlaygroundTextTypeGroupSelection(ids, !allOn)}
              >
                {allOn ? t('playground.clear') : t('playground.selectAll')}
              </Button>
            </div>
            <div className={cn('grid flex-1 grid-cols-3 content-stretch gap-1.5 p-2', isFullPage && 'auto-rows-fr')}>
              {visibleTypes.map((type) => {
                const checked = rec.selectedTypes.includes(type.id);
                const typeName = resolveTextTypeName(type.id, type.name);
                return (
                  <label
                    key={`${group.key}-${type.id}`}
                    className={cn(
                      'flex min-w-0 cursor-pointer items-center gap-1.5 self-stretch rounded-xl border px-2.5 py-1.5 text-[11px] leading-4 transition-colors',
                      checked
                        ? toneClasses.cardSelectedCompact
                        : 'border-border/70 bg-background hover:border-border hover:bg-accent/35',
                    )}
                    title={type.description || typeName}
                  >
                    <Checkbox
                      checked={checked}
                      onCheckedChange={() => {
                        rec.clearPlaygroundTextPresetTracking();
                        rec.setSelectedTypes((previous: string[]) =>
                          checked ? previous.filter((id) => id !== type.id) : [...previous, type.id],
                        );
                      }}
                      className="h-3.5 w-3.5"
                    />
                    <span className="min-w-0 truncate font-medium">{typeName}</span>
                  </label>
                );
              })}
            </div>
            {group.types.length > 0 && (
              <div className="mt-auto border-t border-border/70 px-2 py-2">
                <PaginationRail
                  page={page}
                  pageSize={pageSize}
                  totalItems={group.types.length}
                  totalPages={totalPages}
                  compact
                  onPageChange={(nextPage) => {
                    setGroupPages((current) => ({
                      ...current,
                      [group.key]: nextPage,
                    }));
                  }}
                />
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
};

const VisionPipelines: FC<{ rec: RecognitionCtx }> = ({ rec }) => {
  const t = useT();
  const [pipelinePages, setPipelinePages] = useState<Record<string, number>>({});
  const pageSize = 15;

  useEffect(() => {
    setPipelinePages((current) => {
      const next = { ...current };
      rec.pipelines.forEach((pipeline) => {
        const totalPages = Math.max(1, Math.ceil(pipeline.types.length / pageSize));
        next[pipeline.mode] = Math.min(next[pipeline.mode] ?? 1, totalPages);
      });
      return next;
    });
  }, [pageSize, rec.pipelines]);

  if (rec.visionConfigState === 'loading') {
    return <p className="py-10 text-center text-sm text-muted-foreground">{t('playground.loading')}</p>;
  }

  if (rec.visionConfigState === 'unavailable') {
    return (
      <ConfigEmptyState
        title={t('playground.visionConfigUnavailableTitle')}
        description={t('playground.visionConfigUnavailableDesc')}
      />
    );
  }

  if (rec.visionConfigState === 'empty' || rec.pipelines.length === 0) {
    return (
      <ConfigEmptyState
        title={t('playground.visionConfigEmptyTitle')}
        description={t('playground.visionConfigEmptyDesc')}
      />
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      {rec.pipelines.map((pipeline) => {
        const isHasImage = pipeline.mode === 'has_image';
        const selectedSet = isHasImage ? rec.selectedHasImageTypes : rec.selectedOcrHasTypes;
        const allSelected = pipeline.types.length > 0 && pipeline.types.every((type) => selectedSet.includes(type.id));
        const tone: SelectionTone = isHasImage ? 'visual' : 'semantic';
        const toneClasses = getSelectionToneClasses(tone);
        const totalPages = Math.max(1, Math.ceil(pipeline.types.length / pageSize));
        const page = pipelinePages[pipeline.mode] ?? 1;
        const visibleTypes = pipeline.types.slice((page - 1) * pageSize, page * pageSize);
        const isFullPage = visibleTypes.length === pageSize;

        return (
          <section
            key={pipeline.mode}
            className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-[20px] border border-border/70 bg-[var(--surface-control)] shadow-[var(--shadow-sm)]"
            data-testid={`playground-pipeline-${pipeline.mode}`}
          >
            <div className={cn('flex items-center justify-between gap-2 border-b px-3 py-2', toneClasses.headerSurface)}>
              <div className="flex min-w-0 items-center gap-2">
                <span className={cn('size-2 rounded-full', toneClasses.dot)} />
                <span className={cn('truncate text-xs font-semibold tracking-[0.02em]', toneClasses.titleText)}>
                  {isHasImage ? t('playground.imageFeatures') : t('playground.ocrText')}
                </span>
                <Badge
                  variant="secondary"
                  className={cn('rounded-full border bg-background/85 px-2 py-0.5 text-[10px] shadow-none', toneClasses.badgeText)}
                >
                  {pipeline.types.length}
                </Badge>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="h-6.5 rounded-full px-2 text-[10px]"
                onClick={() => {
                  rec.clearPlaygroundVisionPresetTracking();
                  const ids = pipeline.types.map((type) => type.id);
                  if (allSelected) {
                    if (isHasImage) {
                      rec.updateHasImageTypes([]);
                    } else {
                      rec.updateOcrHasTypes([]);
                    }
                  } else {
                    if (isHasImage) {
                      rec.updateHasImageTypes(ids);
                    } else {
                      rec.updateOcrHasTypes(ids);
                    }
                  }
                }}
              >
                {allSelected ? t('playground.clear') : t('playground.selectAll')}
              </Button>
            </div>
            <div className={cn('grid flex-1 grid-cols-3 content-stretch gap-1.5 p-2', isFullPage && 'auto-rows-fr')}>
              {visibleTypes.map((type) => {
                const checked = selectedSet.includes(type.id);
                return (
                  <label
                    key={type.id}
                    className={cn(
                      'flex min-w-0 cursor-pointer items-center gap-1.5 self-stretch rounded-xl border px-2.5 py-1.5 text-[11px] leading-4 transition-colors',
                      checked
                        ? toneClasses.cardSelectedCompact
                        : 'border-border/70 bg-background hover:border-border hover:bg-accent/35',
                    )}
                    title={type.description || type.name}
                  >
                    <Checkbox
                      checked={checked}
                      onCheckedChange={() => rec.toggleVisionType(type.id, pipeline.mode as 'ocr_has' | 'has_image')}
                      className="h-3.5 w-3.5"
                    />
                    <span className="min-w-0 truncate font-medium">{type.name}</span>
                  </label>
                );
              })}
            </div>
            {pipeline.types.length > 0 && (
              <div className="mt-auto border-t border-border/70 px-2 py-2">
                <PaginationRail
                  page={page}
                  pageSize={pageSize}
                  totalItems={pipeline.types.length}
                  totalPages={totalPages}
                  compact
                  onPageChange={(nextPage) => {
                    setPipelinePages((current) => ({
                      ...current,
                      [pipeline.mode]: nextPage,
                    }));
                  }}
                />
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
};

function ConfigEmptyState({ title, description }: { title: string; description: string }) {
  return (
    <div
      className="rounded-[22px] border border-dashed border-border/70 bg-muted/20 px-5 py-8 text-center"
      data-testid="playground-config-empty"
    >
      <p className="text-sm font-semibold tracking-[-0.02em] text-foreground">{title}</p>
      <p className="mt-2 text-xs leading-6 text-muted-foreground">{description}</p>
    </div>
  );
}

function resolveTextTypeName(typeId: string, fallbackName?: string) {
  return fallbackName?.trim() || getEntityTypeName(typeId);
}

const PresetSaveDialog: FC<{ rec: RecognitionCtx }> = ({ rec }) => {
  const t = useT();
  const open = rec.presetDialogKind !== null;
  const isText = rec.presetDialogKind === 'text';

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => { if (!nextOpen) rec.closePresetDialog(); }}>
      <DialogContent className="sm:max-w-[28rem]">
        <DialogHeader>
          <DialogTitle>
            {isText ? t('playground.saveAsTextPreset') : t('playground.saveAsVisionPreset')}
          </DialogTitle>
          <DialogDescription>
            {isText ? t('preset.saveText.prompt') : t('preset.saveVision.prompt')}
          </DialogDescription>
        </DialogHeader>
        <Input
          value={rec.presetDialogName}
          onChange={(event) => rec.setPresetDialogName(event.target.value)}
          placeholder={t('settings.redaction.namePlaceholder')}
          autoFocus
        />
        <DialogFooter>
          <Button variant="outline" onClick={rec.closePresetDialog} disabled={rec.presetSaving}>
            {t('common.cancel')}
          </Button>
          <Button
            onClick={() => void (isText ? rec.saveTextPresetFromPlayground() : rec.saveVisionPresetFromPlayground())}
            disabled={rec.presetSaving}
          >
            {rec.presetSaving ? t('settings.redaction.processing') : t('settings.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
