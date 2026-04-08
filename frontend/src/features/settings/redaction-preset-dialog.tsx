// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useT } from '@/i18n';
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
import { TypeCheckboxGrid, PipelineCheckboxGrid } from './components/type-checkbox-grid';
import type { PresetPayload } from '@/services/presetsApi';
import type { useRedactionPresets } from './hooks/use-redaction-presets';

type RedactionState = ReturnType<typeof useRedactionPresets>;

export interface RedactionPresetDialogProps {
  modalOpen: boolean;
  editingPresetId: string | null;
  presetForm: PresetPayload;
  saving: boolean;
  regexTypes: RedactionState['regexTypes'];
  semanticTypes: RedactionState['semanticTypes'];
  effectivePipelines: RedactionState['effectivePipelines'];
  presetKindLabel: (kind?: PresetPayload['kind']) => string;
  setPresetForm: RedactionState['setPresetForm'];
  setModalOpen: (open: boolean) => void;
  saveModal: () => Promise<void>;
}

export function RedactionPresetDialog({
  modalOpen,
  editingPresetId,
  presetForm,
  saving,
  regexTypes,
  semanticTypes,
  effectivePipelines,
  presetKindLabel,
  setPresetForm,
  setModalOpen,
  saveModal,
}: RedactionPresetDialogProps) {
  const t = useT();

  if (!modalOpen) return null;

  return (
    <Dialog open={modalOpen} onOpenChange={setModalOpen}>
      <DialogContent className="flex max-h-[90vh] w-[90vw] max-w-3xl flex-col overflow-hidden">
        <DialogHeader>
          <DialogTitle>
            {editingPresetId
              ? t('settings.redaction.editTitle').replace('{kind}', presetKindLabel(presetForm.kind))
              : t('settings.redaction.createTitle').replace('{kind}', presetKindLabel(presetForm.kind))}
          </DialogTitle>
          <DialogDescription>{t('settings.redaction.dialogDesc')}</DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="space-y-5 py-2">
            <div className="max-w-sm space-y-1.5">
              <Label>{t('settings.redaction.nameLabel')} *</Label>
              <Input
                value={presetForm.name}
                onChange={e => setPresetForm(current => ({ ...current, name: e.target.value }))}
                placeholder={t('settings.redaction.namePlaceholder')}
                data-testid="preset-name"
              />
            </div>

            {(presetForm.kind === 'text' || presetForm.kind === 'full') && (
              <>
                <TypeCheckboxGrid
                  title={t('settings.redaction.regexGroup')}
                  types={regexTypes}
                  selectedIds={presetForm.selectedEntityTypeIds}
                  onToggle={id => setPresetForm(current => ({
                    ...current,
                    selectedEntityTypeIds: current.selectedEntityTypeIds.includes(id)
                      ? current.selectedEntityTypeIds.filter(item => item !== id)
                      : [...current.selectedEntityTypeIds, id],
                  }))}
                  variant="regex"
                />
                <TypeCheckboxGrid
                  title={t('settings.redaction.semanticGroup')}
                  types={semanticTypes}
                  selectedIds={presetForm.selectedEntityTypeIds}
                  onToggle={id => setPresetForm(current => ({
                    ...current,
                    selectedEntityTypeIds: current.selectedEntityTypeIds.includes(id)
                      ? current.selectedEntityTypeIds.filter(item => item !== id)
                      : [...current.selectedEntityTypeIds, id],
                  }))}
                  variant="semantic"
                />
              </>
            )}

            {(presetForm.kind === 'vision' || presetForm.kind === 'full') &&
              effectivePipelines.filter(pipeline => pipeline.enabled).map(pipeline => (
                <PipelineCheckboxGrid
                  key={pipeline.mode}
                  pipeline={pipeline}
                  selectedOcr={presetForm.ocrHasTypes}
                  selectedImg={presetForm.hasImageTypes}
                  onToggle={(mode, id) => setPresetForm(current => {
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
          <Button variant="outline" onClick={() => setModalOpen(false)} data-testid="preset-cancel">
            {t('settings.cancel')}
          </Button>
          <Button disabled={saving} onClick={() => void saveModal()} data-testid="preset-save">
            {saving ? t('settings.redaction.processing') : (editingPresetId ? t('settings.save') : t('settings.create'))}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
