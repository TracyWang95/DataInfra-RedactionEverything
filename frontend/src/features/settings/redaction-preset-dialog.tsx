// Copyright 2026 DataInfra-RedactionEverything Contributors

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
import type { PresetKind } from '@/services/presetsApi';
import type { useRedactionPresets } from './hooks/use-redaction-presets';

type RedactionState = ReturnType<typeof useRedactionPresets>;

export interface RedactionPresetDialogProps {
  modalOpen: boolean;
  editingPresetId: string | null;
  presetForm: RedactionState['presetForm'];
  saving: boolean;
  regexTypes: RedactionState['regexTypes'];
  semanticTypes: RedactionState['semanticTypes'];
  effectivePipelines: RedactionState['effectivePipelines'];
  presetKindLabel: (kind?: PresetKind) => string;
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

  const selectTextIds = (ids: string[]) => {
    setPresetForm((current) => ({
      ...current,
      selectedEntityTypeIds: [...new Set([...current.selectedEntityTypeIds, ...ids])],
    }));
  };

  const clearTextIds = (ids: string[]) => {
    const drop = new Set(ids);
    setPresetForm((current) => ({
      ...current,
      selectedEntityTypeIds: current.selectedEntityTypeIds.filter((id) => !drop.has(id)),
    }));
  };

  const setPipelineIds = (mode: string, ids: string[]) => {
    setPresetForm((current) => {
      if (mode === 'ocr_has') return { ...current, ocrHasTypes: ids };
      return { ...current, visualFeatureTypes: ids };
    });
  };

  return (
    <Dialog open={modalOpen} onOpenChange={setModalOpen}>
      <DialogContent className="flex max-h-[calc(100dvh-3rem)] w-[calc(100vw-2rem)] max-w-7xl flex-col gap-3 overflow-hidden p-5 sm:p-6">
        <DialogHeader className="pr-10">
          <DialogTitle>
            {editingPresetId
              ? t('settings.redaction.editTitle').replace(
                  '{kind}',
                  presetKindLabel(presetForm.kind),
                )
              : t('settings.redaction.createTitle').replace(
                  '{kind}',
                  presetKindLabel(presetForm.kind),
                )}
          </DialogTitle>
          <DialogDescription>{t('settings.redaction.dialogDesc')}</DialogDescription>
        </DialogHeader>

        <form
          className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden"
          onSubmit={(event) => {
            event.preventDefault();
            if (saving) return;
            void saveModal();
          }}
        >
        <div className="min-h-0 flex-1 overflow-y-auto pr-1">
          <div className="space-y-4 py-1">
            <div className="max-w-sm space-y-1.5">
              <Label>{t('settings.redaction.nameLabel')} *</Label>
              <Input
                value={presetForm.name}
                onChange={(e) => setPresetForm((current) => ({ ...current, name: e.target.value }))}
                placeholder={t('settings.redaction.namePlaceholder')}
                data-testid="preset-name"
              />
            </div>

            {(presetForm.kind === 'text' || presetForm.kind === 'full') && (
              <>
                <TypeCheckboxGrid
                  title={t('settings.redaction.semanticGroup')}
                  types={semanticTypes}
                  selectedIds={presetForm.selectedEntityTypeIds}
                  onToggle={(id) =>
                    setPresetForm((current) => ({
                      ...current,
                      selectedEntityTypeIds: current.selectedEntityTypeIds.includes(id)
                        ? current.selectedEntityTypeIds.filter((item) => item !== id)
                        : [...current.selectedEntityTypeIds, id],
                    }))
                  }
                  onSelectAll={selectTextIds}
                  onClear={clearTextIds}
                  variant="semantic"
                />
                <TypeCheckboxGrid
                  title={t('settings.redaction.regexGroup')}
                  types={regexTypes}
                  selectedIds={presetForm.selectedEntityTypeIds}
                  onToggle={(id) =>
                    setPresetForm((current) => ({
                      ...current,
                      selectedEntityTypeIds: current.selectedEntityTypeIds.includes(id)
                        ? current.selectedEntityTypeIds.filter((item) => item !== id)
                        : [...current.selectedEntityTypeIds, id],
                    }))
                  }
                  onSelectAll={selectTextIds}
                  onClear={clearTextIds}
                  variant="regex"
                />
              </>
            )}

            {(presetForm.kind === 'vision' || presetForm.kind === 'full') &&
              effectivePipelines
                .filter((pipeline) => pipeline.enabled)
                .map((pipeline) => (
                  <PipelineCheckboxGrid
                    key={pipeline.mode}
                    pipeline={pipeline}
                    selectedOcr={presetForm.ocrHasTypes}
                    selectedImg={presetForm.visualFeatureTypes}
                    onToggle={(mode, id) =>
                      setPresetForm((current) => {
                        if (mode === 'ocr_has') {
                          const next = current.ocrHasTypes.includes(id)
                            ? current.ocrHasTypes.filter((item) => item !== id)
                            : [...current.ocrHasTypes, id];
                          return { ...current, ocrHasTypes: next };
                        }
                        const next = current.visualFeatureTypes.includes(id)
                          ? current.visualFeatureTypes.filter((item) => item !== id)
                          : [...current.visualFeatureTypes, id];
                        return { ...current, visualFeatureTypes: next };
                      })
                    }
                    onSelectAll={setPipelineIds}
                    onClear={(mode) => setPipelineIds(mode, [])}
                  />
                ))}
          </div>
        </div>

        <DialogFooter className="border-t pt-3">
          <Button
            type="button"
            variant="outline"
            onClick={() => setModalOpen(false)}
            data-testid="preset-cancel"
          >
            {t('settings.cancel')}
          </Button>
          <Button type="submit" disabled={saving} data-testid="preset-save">
            {saving
              ? t('settings.redaction.processing')
              : editingPresetId
                ? t('settings.save')
                : t('settings.create')}
          </Button>
        </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
