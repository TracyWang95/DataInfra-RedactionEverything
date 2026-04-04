/**
 * Playground upload stage: drop zone + entity type configuration panel.
 */
import { type FC } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';
import { t } from '@/i18n';
import type { usePlayground } from '../hooks/use-playground';

type PlaygroundCtx = ReturnType<typeof usePlayground>;

interface PlaygroundUploadProps {
  ctx: PlaygroundCtx;
}

export const PlaygroundUpload: FC<PlaygroundUploadProps> = ({ ctx }) => {
  const { dropzone, recognition: rec } = ctx;
  const { getRootProps, getInputProps, isDragActive } = dropzone;

  return (
    <div
      className="flex-1 flex flex-col lg:flex-row gap-3 lg:gap-5 p-3 lg:p-5 min-h-0 min-w-0 overflow-hidden"
      data-testid="playground-upload"
    >
      {/* Drop zone */}
      <div className="flex-1 flex items-center justify-center min-h-0 min-w-0">
        <div className="w-full max-w-lg">
          <Card
            {...getRootProps()}
            className={cn(
              'border-2 border-dashed p-10 text-center cursor-pointer transition-all',
              isDragActive ? 'border-primary bg-primary/5' : 'border-muted-foreground/25 hover:border-primary/60',
            )}
            data-testid="playground-dropzone"
          >
            <input {...getInputProps()} />
            <CardContent className="p-0 flex flex-col items-center">
              <div className="w-14 h-14 mx-auto mb-4 rounded-xl bg-primary/10 flex items-center justify-center">
                <svg className="w-7 h-7 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
              </div>
              <p className="text-base font-medium mb-1">{t('playground.dropHere') || '拖拽文件到此处上传'}</p>
              <p className="text-sm text-muted-foreground mb-4">{t('playground.supportedFormats') || '支持 .doc .docx .pdf .jpg .png'}</p>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Type configuration panel */}
      <Card
        className="w-full lg:w-[min(100%,400px)] xl:w-[420px] 2xl:w-[460px] shrink-0 max-h-[min(52vh,480px)] lg:max-h-none lg:self-stretch flex flex-col overflow-hidden"
        data-testid="playground-type-panel"
      >
        <Tabs
          value={rec.typeTab}
          onValueChange={(v) => rec.setTypeTab(v as 'text' | 'vision')}
          className="flex flex-col flex-1 min-h-0"
        >
          {/* Header */}
          <div className="px-3 py-2 border-b space-y-1.5">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold tracking-tight">{t('playground.recognitionTypes') || '识别类型'}</h3>
              <TabsList className="h-7">
                <TabsTrigger value="text" className="text-xs px-2.5 py-1">{t('playground.text') || '文本'}</TabsTrigger>
                <TabsTrigger value="vision" className="text-xs px-2.5 py-1">{t('playground.vision') || '图像'}</TabsTrigger>
              </TabsList>
            </div>
            <PresetSelectors rec={rec} />
          </div>

          {/* Content */}
          <ScrollArea className="flex-1 min-h-0">
            <TabsContent value="text" className="mt-0 p-2 space-y-3">
              <TextTypeGroups rec={rec} />
            </TabsContent>
            <TabsContent value="vision" className="mt-0 p-2 space-y-3">
              <VisionPipelines rec={rec} />
            </TabsContent>
          </ScrollArea>

          {/* Footer summary */}
          <div className="px-3 py-1.5 border-t shrink-0">
            <p className="text-xs text-muted-foreground text-center" data-testid="playground-type-summary">
              {rec.typeTab === 'vision'
                ? `OCR ${rec.selectedOcrHasTypes.length} · HaS ${rec.selectedHasImageTypes.length}`
                : `${rec.selectedTypes.length} / ${rec.entityTypes.length} ${t('playground.selected') || '已选'}`}
            </p>
          </div>
        </Tabs>
      </Card>
    </div>
  );
};

/* --- Sub-components (kept private) --- */

type Rec = ReturnType<typeof usePlayground>['recognition'];

const PresetSelectors: FC<{ rec: Rec }> = ({ rec }) => (
  <div className="flex flex-col gap-2">
    <PresetRow
      label={t('playground.textPresetLabel') || '文本脱敏配置清单'}
      presets={rec.textPresetsPg}
      activeId={rec.playgroundPresetTextId}
      onSelect={rec.selectPlaygroundTextPresetById}
      onSave={rec.saveTextPresetFromPlayground}
      saveLabel={t('playground.saveAsTextPreset') || '另存为文本预设'}
    />
    <PresetRow
      label={t('playground.visionPresetLabel') || '图像脱敏配置清单'}
      presets={rec.visionPresetsPg}
      activeId={rec.playgroundPresetVisionId}
      onSelect={rec.selectPlaygroundVisionPresetById}
      onSave={rec.saveVisionPresetFromPlayground}
      saveLabel={t('playground.saveAsVisionPreset') || '另存为图像预设'}
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
    <div className="flex items-center gap-1.5 min-w-0">
      <select
        className="text-xs flex-1 min-w-0 border rounded-md px-1.5 py-1 bg-background"
        value={activeId ?? ''}
        onChange={e => onSelect(e.target.value)}
        data-testid="playground-preset-select"
      >
        <option value="">{t('playground.defaultPreset') || '默认（系统预设全选）'}</option>
        {presets.map(p => (
          <option key={p.id} value={p.id}>
            {p.name}{p.kind === 'full' ? '（组合）' : ''}
          </option>
        ))}
      </select>
      <Button variant="outline" size="sm" className="text-[10px] h-7 shrink-0" onClick={() => void onSave()}>
        {saveLabel}
      </Button>
    </div>
  </div>
);

const TextTypeGroups: FC<{ rec: Rec }> = ({ rec }) => {
  if (rec.sortedEntityTypes.length === 0) {
    return <p className="text-xs text-muted-foreground text-center py-8">{t('playground.loading') || '加载中...'}</p>;
  }
  return (
    <>
      {rec.playgroundTextGroups.map(group => {
        const ids = group.types.map(tp => tp.id);
        const allOn = ids.length > 0 && ids.every(id => rec.selectedTypes.includes(id));
        const borderColor = group.key === 'regex' ? 'border-blue-500' : group.key === 'llm' ? 'border-green-500' : 'border-violet-300';
        return (
          <div key={group.key} data-testid={`playground-text-group-${group.key}`}>
            <div className="flex items-center justify-between mb-1.5 pb-1 border-b">
              <span className={cn('text-[10px] font-semibold pl-2 border-l-[3px]', borderColor)}>{group.label}</span>
              <Button variant="ghost" size="sm" className="text-[10px] h-5 px-1" onClick={() => rec.setPlaygroundTextTypeGroupSelection(ids, !allOn)}>
                {allOn ? t('playground.clear') || '清空' : t('playground.selectAll') || '全选'}
              </Button>
            </div>
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-1.5">
              {group.types.map(tp => {
                const checked = rec.selectedTypes.includes(tp.id);
                return (
                  <label
                    key={`${group.key}-${tp.id}`}
                    className={cn(
                      'flex items-center gap-1 px-1.5 py-1 text-[10px] leading-tight cursor-pointer rounded-lg border transition-colors min-w-0',
                      checked ? 'border-primary/40 bg-primary/5' : 'border-transparent hover:bg-accent',
                    )}
                    title={tp.description || tp.name}
                  >
                    <Checkbox
                      checked={checked}
                      onCheckedChange={() => {
                        rec.clearPlaygroundTextPresetTracking();
                        rec.setSelectedTypes((prev: string[]) =>
                          checked ? prev.filter(id => id !== tp.id) : [...prev, tp.id],
                        );
                      }}
                      className="h-3 w-3"
                    />
                    <span className="min-w-0 break-words">{tp.name}</span>
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

const VisionPipelines: FC<{ rec: Rec }> = ({ rec }) => {
  if (rec.pipelines.length === 0) {
    return <p className="text-xs text-muted-foreground text-center py-8">{t('playground.loading') || '加载中...'}</p>;
  }
  return (
    <>
      {rec.pipelines.map(pipeline => {
        const isHasImage = pipeline.mode === 'has_image';
        const types = pipeline.types.filter(tp => tp.enabled);
        const selectedSet = isHasImage ? rec.selectedHasImageTypes : rec.selectedOcrHasTypes;
        const allSelected = types.length > 0 && types.every(tp => selectedSet.includes(tp.id));
        const borderColor = isHasImage ? 'border-purple-500' : 'border-green-500';

        return (
          <div key={pipeline.mode} data-testid={`playground-pipeline-${pipeline.mode}`}>
            <div className="flex items-center justify-between mb-1.5 pb-1 border-b">
              <span className={cn('text-[10px] font-semibold pl-2 border-l-[3px]', borderColor)}>
                {isHasImage ? t('playground.imageFeatures') || '图像特征' : t('playground.ocrText') || '图片类文本'}
              </span>
              <Button
                variant="ghost"
                size="sm"
                className="text-[10px] h-5 px-1"
                onClick={() => {
                  rec.clearPlaygroundVisionPresetTracking();
                  const ids = types.map(tp => tp.id);
                  if (allSelected) {
                    isHasImage ? rec.updateHasImageTypes([]) : rec.updateOcrHasTypes([]);
                  } else {
                    isHasImage ? rec.updateHasImageTypes(ids) : rec.updateOcrHasTypes(ids);
                  }
                }}
              >
                {allSelected ? t('playground.clear') || '清空' : t('playground.selectAll') || '全选'}
              </Button>
            </div>
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-1.5">
              {types.map(tp => {
                const checked = selectedSet.includes(tp.id);
                return (
                  <label
                    key={tp.id}
                    className={cn(
                      'flex items-center gap-1 px-1.5 py-1 text-[10px] leading-tight cursor-pointer rounded-lg border transition-colors min-w-0',
                      checked ? 'border-primary/40 bg-primary/5' : 'border-transparent hover:bg-accent',
                    )}
                    title={tp.description || tp.name}
                  >
                    <Checkbox
                      checked={checked}
                      onCheckedChange={() => rec.toggleVisionType(tp.id, pipeline.mode as 'ocr_has' | 'has_image')}
                      className="h-3 w-3"
                    />
                    <span className="min-w-0 break-words">{tp.name}</span>
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
