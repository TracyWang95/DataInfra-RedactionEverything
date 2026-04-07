// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useT } from '@/i18n';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
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
import { Skeleton } from '@/components/ui/skeleton';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  setActivePresetTextId,
  setActivePresetVisionId,
} from '@/services/activePresetBridge';
import { useRedactionPresets } from './hooks/use-redaction-presets';
import { TypeCheckboxGrid, PipelineCheckboxGrid } from './components/type-checkbox-grid';
import { PresetColumn } from './components/preset-column';

const DEFAULT_PRESET_OPTION = '__default__';

export function RedactionList() {
  const t = useT();
  const state = useRedactionPresets();

  if (state.loading) {
    return (
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background">
        <div className="page-shell !max-w-[min(100%,1920px)] !px-3 !py-2 sm:!px-4 sm:!py-3">
          <Card className="overflow-hidden">
            <CardHeader className="pb-3">
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-4 w-80 max-w-full" />
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <Skeleton className="h-20 w-full rounded-xl" />
              <div className="grid gap-2 md:grid-cols-2">
                <Skeleton className="h-16 w-full rounded-xl" />
                <Skeleton className="h-16 w-full rounded-xl" />
              </div>
              <div className="grid gap-2 md:grid-cols-2">
                <Skeleton className="h-[22rem] w-full rounded-xl" />
                <Skeleton className="h-[22rem] w-full rounded-xl" />
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background">
      <div className="page-shell !max-w-[min(100%,1920px)] !px-3 !py-2 sm:!px-4 sm:!py-3">
        {state.loadError && (
          <Alert variant="destructive">
            <AlertDescription>{state.loadError}</AlertDescription>
          </Alert>
        )}

        <Card className="page-surface overflow-hidden">
          <CardHeader className="pb-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <CardTitle className="text-sm">{t('settings.redaction.configTitle')}</CardTitle>
                <CardDescription className="mt-0.5 text-xs">
                  {t('settings.redaction.configDesc')}
                </CardDescription>
              </div>
              <div className="flex flex-wrap gap-1.5">
                <Button size="sm" variant="outline" onClick={() => state.openNew('text')} data-testid="new-text-preset">
                  {t('settings.redaction.newText')}
                </Button>
                <Button size="sm" variant="outline" onClick={() => state.openNew('vision')} data-testid="new-vision-preset">
                  {t('settings.redaction.newVision')}
                </Button>
              </div>
            </div>
          </CardHeader>

          <CardContent className="page-surface-body flex flex-col gap-4 p-6">
            <div className="rounded-lg border bg-muted/30 px-3 py-2 text-xs">
              <p className="mb-1 text-[0.65rem] font-semibold uppercase tracking-wide text-muted-foreground">
                {t('settings.redaction.currentSelection')}
              </p>
              <p>
                <span className="text-muted-foreground">{t('settings.redaction.currentText')}</span>
                <span className="font-medium">{state.summaryTextLabel}</span>
              </p>
              <p className="mt-0.5">
                <span className="text-muted-foreground">{t('settings.redaction.currentVision')}</span>
                <span className="font-medium">{state.summaryVisionLabel}</span>
              </p>
            </div>

            <div className="grid gap-2 md:grid-cols-2">
              <div className="space-y-1">
                <Label className="text-xs">{t('settings.redaction.linkText')}</Label>
                <Select
                  value={state.bridgeText || DEFAULT_PRESET_OPTION}
                  onValueChange={(value) => {
                    const nextValue = value === DEFAULT_PRESET_OPTION ? '' : value;
                    state.setBridgeText(nextValue);
                    setActivePresetTextId(nextValue || null);
                  }}
                >
                  <SelectTrigger className="h-8 rounded-lg text-xs" data-testid="bridge-text-select">
                    <SelectValue placeholder={t('settings.redaction.defaultOption')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      <SelectItem value={DEFAULT_PRESET_OPTION}>{t('settings.redaction.defaultOption')}</SelectItem>
                      {state.textPresets.map((preset) => (
                        <SelectItem key={preset.id} value={preset.id}>
                          {preset.name}
                          {preset.kind === 'full' ? ` (${t('settings.redaction.kind.full')})` : ''}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1">
                <Label className="text-xs">{t('settings.redaction.linkVision')}</Label>
                <Select
                  value={state.bridgeVision || DEFAULT_PRESET_OPTION}
                  onValueChange={(value) => {
                    const nextValue = value === DEFAULT_PRESET_OPTION ? '' : value;
                    state.setBridgeVision(nextValue);
                    setActivePresetVisionId(nextValue || null);
                  }}
                >
                  <SelectTrigger className="h-8 rounded-lg text-xs" data-testid="bridge-vision-select">
                    <SelectValue placeholder={t('settings.redaction.defaultOption')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      <SelectItem value={DEFAULT_PRESET_OPTION}>{t('settings.redaction.defaultOption')}</SelectItem>
                      {state.visionPresets.map((preset) => (
                        <SelectItem key={preset.id} value={preset.id}>
                          {preset.name}
                          {preset.kind === 'full' ? ` (${t('settings.redaction.kind.full')})` : ''}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="grid gap-2 md:grid-cols-2">
              <PresetColumn
                title={t('settings.redaction.textColumn')}
                defaultPreset={state.defaultTextPreset}
                presets={state.textPresets}
                entityTypes={state.effectiveEntityTypes}
                pipelines={state.effectivePipelines}
                expanded={state.expanded}
                setExpanded={state.setExpanded}
                colPrefix="text"
                onEdit={state.openEdit}
                    onDelete={(id) => state.setConfirmState({
                      title: t('common.delete'),
                      message: t('settings.redaction.confirmDelete'),
                      danger: true,
                      onConfirm: () => void state.removePreset(id),
                    })}
              />
              <PresetColumn
                title={t('settings.redaction.visionColumn')}
                defaultPreset={state.defaultVisionPreset}
                presets={state.visionPresets}
                entityTypes={state.effectiveEntityTypes}
                pipelines={state.effectivePipelines}
                expanded={state.expanded}
                setExpanded={state.setExpanded}
                colPrefix="vision"
                onEdit={state.openEdit}
                    onDelete={(id) => state.setConfirmState({
                      title: t('common.delete'),
                      message: t('settings.redaction.confirmDelete'),
                      danger: true,
                      onConfirm: () => void state.removePreset(id),
                    })}
              />
            </div>
          </CardContent>
        </Card>
      </div>

      {state.modalOpen && (
        <Dialog open={state.modalOpen} onOpenChange={state.setModalOpen}>
          <DialogContent className="flex max-h-[90vh] w-[90vw] max-w-3xl flex-col overflow-hidden">
            <DialogHeader>
              <DialogTitle>
                {state.editingPresetId
                  ? t('settings.redaction.editTitle').replace('{kind}', state.presetKindLabel(state.presetForm.kind))
                  : t('settings.redaction.createTitle').replace('{kind}', state.presetKindLabel(state.presetForm.kind))}
              </DialogTitle>
              <DialogDescription>{t('settings.redaction.dialogDesc')}</DialogDescription>
            </DialogHeader>

            <div className="min-h-0 flex-1 overflow-y-auto">
              <div className="space-y-5 py-2">
                <div className="max-w-sm space-y-1.5">
                  <Label>{t('settings.redaction.nameLabel')} *</Label>
                  <Input
                    value={state.presetForm.name}
                    onChange={e => state.setPresetForm(current => ({ ...current, name: e.target.value }))}
                    placeholder={t('settings.redaction.namePlaceholder')}
                    data-testid="preset-name"
                  />
                </div>

                {(state.presetForm.kind === 'text' || state.presetForm.kind === 'full') && (
                  <>
                    <TypeCheckboxGrid
                      title={t('settings.redaction.regexGroup')}
                      types={state.regexTypes}
                      selectedIds={state.presetForm.selectedEntityTypeIds}
                      onToggle={id => state.setPresetForm(current => ({
                        ...current,
                        selectedEntityTypeIds: current.selectedEntityTypeIds.includes(id)
                          ? current.selectedEntityTypeIds.filter(item => item !== id)
                          : [...current.selectedEntityTypeIds, id],
                      }))}
                      variant="regex"
                    />
                    <TypeCheckboxGrid
                      title={t('settings.redaction.semanticGroup')}
                      types={state.semanticTypes}
                      selectedIds={state.presetForm.selectedEntityTypeIds}
                      onToggle={id => state.setPresetForm(current => ({
                        ...current,
                        selectedEntityTypeIds: current.selectedEntityTypeIds.includes(id)
                          ? current.selectedEntityTypeIds.filter(item => item !== id)
                          : [...current.selectedEntityTypeIds, id],
                      }))}
                      variant="semantic"
                    />
                  </>
                )}

                {(state.presetForm.kind === 'vision' || state.presetForm.kind === 'full') &&
                  state.effectivePipelines.filter(pipeline => pipeline.enabled).map(pipeline => (
                    <PipelineCheckboxGrid
                      key={pipeline.mode}
                      pipeline={pipeline}
                      selectedOcr={state.presetForm.ocrHasTypes}
                      selectedImg={state.presetForm.hasImageTypes}
                      onToggle={(mode, id) => state.setPresetForm(current => {
                        if (mode === 'ocr_has') {
                          const next = current.ocrHasTypes.includes(id)
                            ? current.ocrHasTypes.filter(item => item !== id)
                            : [...current.ocrHasTypes, id];
                          return { ...current, ocrHasTypes: next };
                        }

                        const next = current.hasImageTypes.includes(id)
                          ? current.hasImageTypes.filter(item => item !== id)
                          : [...current.hasImageTypes, id];
                        return { ...current, hasImageTypes: next };
                      })}
                    />
                  ))}
              </div>
            </div>

            <DialogFooter className="border-t pt-4">
              <Button variant="outline" onClick={() => state.setModalOpen(false)} data-testid="preset-cancel">
                {t('settings.cancel')}
              </Button>
              <Button disabled={state.saving} onClick={() => void state.saveModal()} data-testid="preset-save">
                {state.saving ? t('settings.redaction.processing') : (state.editingPresetId ? t('settings.save') : t('settings.create'))}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
      {state.confirmState && (
        <ConfirmDialog
          open
          title={state.confirmState.title}
          message={state.confirmState.message}
          danger={state.confirmState.danger}
          onConfirm={() => {
            state.confirmState!.onConfirm();
            state.setConfirmState(null);
          }}
          onCancel={() => state.setConfirmState(null)}
        />
      )}
    </div>
  );
}
