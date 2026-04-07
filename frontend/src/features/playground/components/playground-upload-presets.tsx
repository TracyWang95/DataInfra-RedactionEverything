// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type { FC } from 'react';
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
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useT } from '@/i18n';
import type { usePlayground } from '../hooks/use-playground';

type RecognitionCtx = ReturnType<typeof usePlayground>['recognition'];
const DEFAULT_PRESET_VALUE = '__default__';

export const PresetSelectors: FC<{
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

export const PresetSaveDialog: FC<{ rec: RecognitionCtx }> = ({ rec }) => {
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
