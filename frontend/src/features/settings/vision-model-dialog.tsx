// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useT } from '@/i18n';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { BUILTIN_MODEL_IDS, type ModelConfig } from './hooks/use-model-config';

export interface VisionModelDialogProps {
  open: boolean;
  editingId: string | null;
  form: Partial<ModelConfig>;
  onClose: () => void;
  onSave: () => void;
  onUpdateForm: (patch: Partial<ModelConfig>) => void;
}

export function VisionModelDialog({
  open,
  editingId,
  form,
  onClose,
  onSave,
  onUpdateForm,
}: VisionModelDialogProps) {
  const t = useT();
  const builtinLocked = Boolean(editingId && BUILTIN_MODEL_IDS.has(editingId));

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) onClose();
      }}
    >
      <DialogContent className="flex max-h-[min(90vh,780px)] flex-col overflow-hidden sm:max-w-2xl">
        <DialogHeader className="space-y-1">
          <DialogTitle>
            {editingId
              ? t('settings.visionModel.dialog.editTitle')
              : t('settings.visionModel.dialog.createTitle')}
          </DialogTitle>
          <DialogDescription>{t('settings.visionModel.dialog.desc')}</DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto py-1 pr-1">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label className="text-xs">{t('settings.visionModel.nameLabel')} *</Label>
              <Input
                value={form.name ?? ''}
                onChange={(e) => onUpdateForm({ name: e.target.value })}
                placeholder={t('settings.visionModel.namePlaceholder')}
                data-testid="vision-model-name"
              />
            </div>

            <div className="space-y-1">
              <Label className="text-xs">{t('settings.modelConfig.taskLabel')} *</Label>
              <Select
                value={form.task_type ?? 'visual_feature'}
                disabled={builtinLocked}
                onValueChange={(value) =>
                  onUpdateForm({ task_type: value as ModelConfig['task_type'] })
                }
              >
                <SelectTrigger data-testid="vision-model-task">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="text_ner">{t('settings.modelConfig.task.text_ner')}</SelectItem>
                  <SelectItem value="ocr">{t('settings.modelConfig.task.ocr')}</SelectItem>
                  <SelectItem value="visual_feature">
                    {t('settings.modelConfig.task.visual_feature')}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label className="text-xs">{t('settings.visionModel.providerLabel')} *</Label>
              <Select
                value={form.provider ?? 'local'}
                onValueChange={(value) =>
                  onUpdateForm({ provider: value as ModelConfig['provider'] })
                }
              >
                <SelectTrigger data-testid="vision-model-provider">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="local">{t('settings.visionModel.provider.local')}</SelectItem>
                  <SelectItem value="openai">
                    {t('settings.visionModel.provider.openai')}
                  </SelectItem>
                  <SelectItem value="custom">
                    {t('settings.visionModel.provider.custom')}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label className="text-xs">{t('settings.visionModel.modelLabel')} *</Label>
              <Input
                value={form.model_name ?? ''}
                onChange={(e) => onUpdateForm({ model_name: e.target.value })}
                className="font-mono text-sm"
                placeholder={
                  form.provider === 'local' ? 'LocateAnything-3B' : 'gpt-4-vision-preview'
                }
                data-testid="vision-model-model-name"
              />
            </div>

            {(form.provider === 'local' ||
              form.provider === 'openai' ||
              form.provider === 'custom') && (
              <div className="space-y-1">
                <Label className="text-xs">{t('settings.visionModel.baseUrlLabel')}</Label>
                <Input
                  value={form.base_url ?? ''}
                  onChange={(e) => onUpdateForm({ base_url: e.target.value })}
                  className="font-mono text-sm"
                  placeholder={
                    form.provider === 'local' ? 'http://127.0.0.1:8090' : 'https://api.openai.com'
                  }
                  data-testid="vision-model-base-url"
                />
              </div>
            )}
          </div>

          {(form.provider === 'openai' || form.provider === 'custom') && (
            <div className="space-y-1">
              <Label className="text-xs">{t('settings.visionModel.apiKeyLabel')}</Label>
              <Input
                type="password"
                value={form.api_key === '__REDACTED__' ? '' : (form.api_key ?? '')}
                onChange={(e) => onUpdateForm({ api_key: e.target.value })}
                className="font-mono text-sm"
                placeholder={
                  form.api_key === '__REDACTED__' ? '已保存，输入新密钥可替换' : 'sk-...'
                }
                data-testid="vision-model-api-key"
                autoComplete="off"
              />
            </div>
          )}

          <div className="border-t pt-3">
            <h4 className="mb-2 text-sm font-medium">{t('settings.visionModel.advancedTitle')}</h4>
            <div className="grid grid-cols-3 gap-2.5">
              <div className="space-y-1">
                <Label className="text-xs">{t('settings.visionModel.temperatureLabel')}</Label>
                <Input
                  type="number"
                  step={0.1}
                  min={0}
                  max={2}
                  value={form.temperature ?? 0.8}
                  onChange={(e) => onUpdateForm({ temperature: parseFloat(e.target.value) })}
                  data-testid="vision-model-temp"
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">{t('settings.visionModel.topPLabel')}</Label>
                <Input
                  type="number"
                  step={0.1}
                  min={0}
                  max={1}
                  value={form.top_p ?? 0.6}
                  onChange={(e) => onUpdateForm({ top_p: parseFloat(e.target.value) })}
                  data-testid="vision-model-top-p"
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">{t('settings.visionModel.maxTokensLabel')}</Label>
                <Input
                  type="number"
                  step={256}
                  min={1}
                  max={32768}
                  value={form.max_tokens ?? 4096}
                  onChange={(e) => onUpdateForm({ max_tokens: parseInt(e.target.value, 10) })}
                  data-testid="vision-model-max-tokens"
                />
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3 rounded-xl border border-border/70 bg-muted/30 px-3 py-2">
            <Switch
              checked={builtinLocked ? true : (form.enabled ?? true)}
              disabled={builtinLocked}
              onCheckedChange={(checked) => onUpdateForm({ enabled: checked })}
              data-testid="vision-model-enabled"
            />
            <Label className="text-sm leading-5">
              {t('settings.visionModel.enabledLabel')}
              {builtinLocked && (
                <span className="text-muted-foreground">
                  {' '}
                  {t('settings.visionModel.enabledBuiltinHint')}
                </span>
              )}
            </Label>
          </div>

          <div className="space-y-1">
            <Label className="text-xs">{t('settings.visionModel.notesLabel')}</Label>
            <Textarea
              value={form.description ?? ''}
              onChange={(e) => onUpdateForm({ description: e.target.value })}
              rows={2}
              className="min-h-[64px]"
              placeholder={t('settings.visionModel.notesPlaceholder')}
              data-testid="vision-model-desc"
            />
          </div>
        </div>

        <DialogFooter className="border-t pt-3">
          <Button
            variant="outline"
            size="sm"
            className="h-8"
            onClick={onClose}
            data-testid="vision-model-cancel"
          >
            {t('settings.cancel')}
          </Button>
          <Button
            size="sm"
            className="h-8"
            disabled={!form.name || !form.model_name}
            onClick={onSave}
            data-testid="vision-model-save"
          >
            {editingId ? t('settings.save') : t('settings.create')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
