/**
 * Playground upload stage: drop zone plus recognition configuration.
 */
import { type FC } from 'react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';
import { t } from '@/i18n';
import type { usePlayground } from '../hooks/use-playground';

type PlaygroundCtx = ReturnType<typeof usePlayground>;
type RecognitionCtx = PlaygroundCtx['recognition'];

interface PlaygroundUploadProps {
  ctx: PlaygroundCtx;
}

function tr(key: string, fallback: string) {
  const value = t(key);
  return value === key ? fallback : value;
}

export const PlaygroundUpload: FC<PlaygroundUploadProps> = ({ ctx }) => {
  const { dropzone, recognition: rec } = ctx;
  const { getRootProps, getInputProps, isDragActive } = dropzone;

  return (
    <div
      className="flex min-h-0 min-w-0 flex-1 flex-col gap-4 overflow-hidden p-3 lg:flex-row lg:gap-5 lg:p-5"
      data-testid="playground-upload"
    >
      <div className="flex min-h-0 min-w-0 flex-1 items-center justify-center">
        <div className="w-full max-w-xl">
          <div className="mb-4 space-y-2">
            <span className="saas-kicker">Workspace Intake</span>
            <div>
              <h2 className="text-2xl font-semibold tracking-[-0.04em] text-foreground">
                Upload one file and start reviewing immediately
              </h2>
              <p className="mt-2 text-sm leading-7 text-muted-foreground">
                Keep the first step simple: drop a document in, choose what to detect, then review before export.
              </p>
            </div>
          </div>

          <div
            {...getRootProps()}
            className={cn(
              'saas-hero group relative cursor-pointer border-2 border-dashed p-12 text-center transition-all duration-300 ease-out',
              isDragActive
                ? 'border-primary bg-primary/[0.04] shadow-[0_0_0_4px_rgba(16,163,127,0.08)]'
                : 'border-border hover:border-foreground/15 hover:shadow-lg',
            )}
            data-testid="playground-dropzone"
          >
            <input {...getInputProps()} />
            <div className="flex flex-col items-center">
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
                {tr('playground.dropHere', 'Drop a file here to upload')}
              </p>
              <p className="mb-5 text-sm text-muted-foreground">
                {tr('playground.supportedFormats', 'Supports .doc, .docx, .pdf, .jpg, and .png')}
              </p>
              <div className="inline-flex items-center gap-2 rounded-full border border-border/70 bg-card px-4 py-2 text-xs font-medium text-foreground">
                <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                {tr('playground.clickToUpload', 'Or click to choose a file')}
              </div>
            </div>
          </div>
        </div>
      </div>

      <Card
        className="w-full shrink-0 overflow-hidden lg:w-[min(100%,400px)] lg:self-stretch xl:w-[420px] 2xl:w-[460px]"
        data-testid="playground-type-panel"
      >
        <Tabs value={rec.typeTab} onValueChange={(value) => rec.setTypeTab(value as 'text' | 'vision')} className="flex min-h-0 flex-1 flex-col">
          <div className="space-y-1.5 border-b px-3 py-2">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold tracking-tight">
                {tr('playground.recognitionTypes', 'Recognition Types')}
              </h3>
              <TabsList className="h-7">
                <TabsTrigger value="text" className="px-2.5 py-1 text-xs">
                  {tr('playground.text', 'Text')}
                </TabsTrigger>
                <TabsTrigger value="vision" className="px-2.5 py-1 text-xs">
                  {tr('playground.vision', 'Vision')}
                </TabsTrigger>
              </TabsList>
            </div>
            <PresetSelectors rec={rec} />
          </div>

          <ScrollArea className="flex-1 min-h-0">
            <TabsContent value="text" className="mt-0 space-y-3 p-2">
              <TextTypeGroups rec={rec} />
            </TabsContent>
            <TabsContent value="vision" className="mt-0 space-y-3 p-2">
              <VisionPipelines rec={rec} />
            </TabsContent>
          </ScrollArea>

          <div className="shrink-0 border-t px-3 py-1.5">
            <p className="text-center text-xs text-muted-foreground" data-testid="playground-type-summary">
              {rec.typeTab === 'vision'
                ? `OCR ${rec.selectedOcrHasTypes.length} / HaS ${rec.selectedHasImageTypes.length}`
                : `${rec.selectedTypes.length} / ${rec.entityTypes.length} ${tr('playground.selected', 'selected')}`}
            </p>
          </div>
        </Tabs>
      </Card>
    </div>
  );
};

const PresetSelectors: FC<{ rec: RecognitionCtx }> = ({ rec }) => (
  <div className="flex flex-col gap-2">
    <PresetRow
      label={tr('playground.textPresetLabel', 'Text preset')}
      presets={rec.textPresetsPg}
      activeId={rec.playgroundPresetTextId}
      onSelect={rec.selectPlaygroundTextPresetById}
      onSave={rec.saveTextPresetFromPlayground}
      saveLabel={tr('playground.saveAsTextPreset', 'Save Text Preset')}
    />
    <PresetRow
      label={tr('playground.visionPresetLabel', 'Vision preset')}
      presets={rec.visionPresetsPg}
      activeId={rec.playgroundPresetVisionId}
      onSelect={rec.selectPlaygroundVisionPresetById}
      onSave={rec.saveVisionPresetFromPlayground}
      saveLabel={tr('playground.saveAsVisionPreset', 'Save Vision Preset')}
    />
  </div>
);

const PresetRow: FC<{
  label: string;
  presets: { id: string; name: string; kind?: string }[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onSave: () => void;
  saveLabel: string;
}> = ({ label, presets, activeId, onSelect, onSave, saveLabel }) => (
  <div className="flex flex-col gap-0.5">
    <span className="text-[10px] text-muted-foreground">{label}</span>
    <div className="flex min-w-0 items-center gap-1.5">
      <select
        className="min-w-0 flex-1 rounded-md border bg-background px-1.5 py-1 text-xs"
        value={activeId ?? ''}
        onChange={(event) => onSelect(event.target.value)}
        data-testid="playground-preset-select"
      >
        <option value="">{tr('playground.defaultPreset', 'Default Preset')}</option>
        {presets.map((preset) => (
          <option key={preset.id} value={preset.id}>
            {preset.name}{preset.kind === 'full' ? ' (Full)' : ''}
          </option>
        ))}
      </select>
      <Button variant="outline" size="sm" className="h-7 shrink-0 text-[10px]" onClick={() => void onSave()}>
        {saveLabel}
      </Button>
    </div>
  </div>
);

const TextTypeGroups: FC<{ rec: RecognitionCtx }> = ({ rec }) => {
  if (rec.sortedEntityTypes.length === 0) {
    return <p className="py-8 text-center text-xs text-muted-foreground">{tr('playground.loading', 'Loading...')}</p>;
  }

  return (
    <>
      {rec.playgroundTextGroups.map((group) => {
        const ids = group.types.map((type) => type.id);
        const allOn = ids.length > 0 && ids.every((id) => rec.selectedTypes.includes(id));
        const borderColor = group.key === 'regex' ? 'border-blue-500' : group.key === 'llm' ? 'border-green-500' : 'border-violet-300';

        return (
          <div key={group.key} data-testid={`playground-text-group-${group.key}`}>
            <div className="mb-1.5 flex items-center justify-between border-b pb-1">
              <span className={cn('border-l-[3px] pl-2 text-[10px] font-semibold', borderColor)}>
                {group.label}
              </span>
              <Button variant="ghost" size="sm" className="h-5 px-1 text-[10px]" onClick={() => rec.setPlaygroundTextTypeGroupSelection(ids, !allOn)}>
                {allOn ? tr('playground.clear', 'Clear') : tr('playground.selectAll', 'Select All')}
              </Button>
            </div>
            <div className="grid grid-cols-2 gap-1.5 lg:grid-cols-3">
              {group.types.map((type) => {
                const checked = rec.selectedTypes.includes(type.id);
                return (
                  <label
                    key={`${group.key}-${type.id}`}
                    className={cn(
                      'min-w-0 cursor-pointer rounded-lg border px-1.5 py-1 text-[10px] leading-tight transition-colors',
                      'flex items-center gap-1',
                      checked ? 'border-primary/40 bg-primary/5' : 'border-transparent hover:bg-accent',
                    )}
                    title={type.description || type.name}
                  >
                    <Checkbox
                      checked={checked}
                      onCheckedChange={() => {
                        rec.clearPlaygroundTextPresetTracking();
                        rec.setSelectedTypes((previous: string[]) => (checked ? previous.filter((id) => id !== type.id) : [...previous, type.id]));
                      }}
                      className="h-3 w-3"
                    />
                    <span className="min-w-0 break-words">{type.name}</span>
                  </label>
                );
              })}
            </div>
          </div>
        );
      })}
    </>
  );
};

const VisionPipelines: FC<{ rec: RecognitionCtx }> = ({ rec }) => {
  if (rec.pipelines.length === 0) {
    return <p className="py-8 text-center text-xs text-muted-foreground">{tr('playground.loading', 'Loading...')}</p>;
  }

  return (
    <>
      {rec.pipelines.map((pipeline) => {
        const isHasImage = pipeline.mode === 'has_image';
        const types = pipeline.types.filter((type) => type.enabled);
        const selectedSet = isHasImage ? rec.selectedHasImageTypes : rec.selectedOcrHasTypes;
        const allSelected = types.length > 0 && types.every((type) => selectedSet.includes(type.id));
        const borderColor = isHasImage ? 'border-purple-500' : 'border-green-500';

        return (
          <div key={pipeline.mode} data-testid={`playground-pipeline-${pipeline.mode}`}>
            <div className="mb-1.5 flex items-center justify-between border-b pb-1">
              <span className={cn('border-l-[3px] pl-2 text-[10px] font-semibold', borderColor)}>
                {isHasImage ? tr('playground.imageFeatures', 'Image Features') : tr('playground.ocrText', 'OCR Text')}
              </span>
              <Button
                variant="ghost"
                size="sm"
                className="h-5 px-1 text-[10px]"
                onClick={() => {
                  rec.clearPlaygroundVisionPresetTracking();
                  const ids = types.map((type) => type.id);
                  if (allSelected) {
                    isHasImage ? rec.updateHasImageTypes([]) : rec.updateOcrHasTypes([]);
                  } else {
                    isHasImage ? rec.updateHasImageTypes(ids) : rec.updateOcrHasTypes(ids);
                  }
                }}
              >
                {allSelected ? tr('playground.clear', 'Clear') : tr('playground.selectAll', 'Select All')}
              </Button>
            </div>
            <div className="grid grid-cols-2 gap-1.5 lg:grid-cols-3">
              {types.map((type) => {
                const checked = selectedSet.includes(type.id);
                return (
                  <label
                    key={type.id}
                    className={cn(
                      'min-w-0 cursor-pointer rounded-lg border px-1.5 py-1 text-[10px] leading-tight transition-colors',
                      'flex items-center gap-1',
                      checked ? 'border-primary/40 bg-primary/5' : 'border-transparent hover:bg-accent',
                    )}
                    title={type.description || type.name}
                  >
                    <Checkbox
                      checked={checked}
                      onCheckedChange={() => rec.toggleVisionType(type.id, pipeline.mode as 'ocr_has' | 'has_image')}
                      className="h-3 w-3"
                    />
                    <span className="min-w-0 break-words">{type.name}</span>
                  </label>
                );
              })}
            </div>
          </div>
        );
      })}
    </>
  );
};
