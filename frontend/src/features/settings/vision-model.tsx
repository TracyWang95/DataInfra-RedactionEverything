// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useState } from 'react';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
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
import {
  BUILTIN_VISION_IDS,
  DEFAULT_MODEL_FORM,
  type ModelConfig,
  useVisionModelConfig,
} from './hooks/use-model-config';
import { tonePanelClass } from '@/utils/toneClasses';

export function VisionModel() {
  const t = useT();
  const {
    modelConfigs,
    loading,
    builtinLive,
    testingModelId,
    testResult,
    saveModelConfig,
    deleteModelConfig,
    testModelConfig,
    resetModelConfigs,
    liveForBuiltin,
    getProviderLabel,
  } = useVisionModelConfig();

  const [showModal, setShowModal] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<Partial<ModelConfig>>({ ...DEFAULT_MODEL_FORM });
  const [confirmState, setConfirmState] = useState<{
    title: string;
    message: string;
    danger?: boolean;
    onConfirm: () => void;
  } | null>(null);

  const openAdd = () => {
    setEditingId(null);
    setForm({ ...DEFAULT_MODEL_FORM, enabled: true });
    setShowModal(true);
  };

  const openEdit = (config: ModelConfig) => {
    setEditingId(config.id);
    setForm({ ...config });
    setShowModal(true);
  };

  const handleSave = async () => {
    const ok = await saveModelConfig(form, editingId);
    if (!ok) return;

    setShowModal(false);
    setEditingId(null);
    setForm({ ...DEFAULT_MODEL_FORM });
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="h-7 w-7 animate-spin rounded-full border-2 border-muted border-t-foreground" />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-background">
      <div className="page-shell-narrow overflow-auto overscroll-contain">
        <div className="page-stack">
          <Card className="rounded-[24px] border-border/70 bg-muted/30 shadow-[var(--shadow-control)]">
            <CardHeader className="pb-3">
              <CardTitle className="text-base tracking-[-0.03em]">{t('settings.visionModel.infoTitle')}</CardTitle>
              <CardDescription className="mt-2 text-sm leading-relaxed">
                {t('settings.visionModel.infoDesc')}
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-0">
              <div className="flex flex-wrap gap-2 border-t pt-3">
                <Badge variant="outline">{t('settings.visionModel.tag.local')}</Badge>
                <Badge variant="outline">{t('settings.visionModel.tag.openai')}</Badge>
                <Badge variant="outline">{t('settings.visionModel.tag.custom')}</Badge>
              </div>
            </CardContent>
          </Card>

          <Card className="rounded-[24px] border-border/70 shadow-[var(--shadow-control)]">
            <CardHeader className="pb-3">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="space-y-1">
                  <CardTitle className="text-base">{t('settings.visionModel.listTitle')}</CardTitle>
                  <CardDescription className="text-xs">
                    {t('settings.visionModel.listDesc')}
                  </CardDescription>
                </div>
                <Button size="sm" onClick={openAdd} data-testid="add-vision-backend">
                  {t('settings.visionModel.add')}
                </Button>
              </div>
            </CardHeader>

            <CardContent className="p-0">
              <div className="divide-y divide-border/70">
                {modelConfigs.configs.map(config => (
                  <div key={config.id} className="flex items-center gap-4 px-5 py-4">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium">{config.name}</span>
                        <Badge
                          variant={BUILTIN_VISION_IDS.has(config.id) || config.enabled ? 'secondary' : 'outline'}
                          className="text-xs"
                        >
                          {BUILTIN_VISION_IDS.has(config.id) || config.enabled
                            ? t('common.enabled')
                            : t('common.disabled')}
                        </Badge>
                        {BUILTIN_VISION_IDS.has(config.id) && (() => {
                          const live = liveForBuiltin(config.id);
                          return live === 'online'
                            ? (
                              <Badge className={`text-xs ${tonePanelClass.success}`}>
                                {t('common.online')}
                              </Badge>
                            )
                            : live === 'offline'
                              ? (
                                <Badge variant="destructive" className="text-xs">
                                  {t('common.offline')}
                                </Badge>
                              )
                              : builtinLive === null
                                ? (
                                  <Badge variant="outline" className="text-xs">
                                    {t('common.checking')}
                                  </Badge>
                                )
                                : (
                                  <Badge variant="outline" className="text-xs">
                                    {t('common.unknown')}
                                  </Badge>
                                );
                        })()}
                      </div>

                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        <Badge variant="outline" className="text-[10px]">
                          {getProviderLabel(config.provider)}
                        </Badge>
                        <span>|</span>
                        <span className="font-mono">{config.model_name}</span>
                        {config.base_url && (
                          <>
                            <span>|</span>
                            <span className="max-w-[200px] truncate">{config.base_url}</span>
                          </>
                        )}
                      </div>

                      {config.description && (
                        <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">{config.description}</p>
                      )}
                    </div>

                    <div className="flex shrink-0 items-center gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={testingModelId === config.id}
                        onClick={() => void testModelConfig(config.id)}
                        data-testid={`test-model-${config.id}`}
                      >
                        {testingModelId === config.id ? t('common.testing') : t('common.test')}
                      </Button>
                      <Button size="icon" variant="ghost" onClick={() => openEdit(config)} data-testid={`edit-model-${config.id}`}>
                        <PencilIcon />
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        disabled={BUILTIN_VISION_IDS.has(config.id)}
                        className={cn(BUILTIN_VISION_IDS.has(config.id) && 'cursor-not-allowed opacity-20')}
                        onClick={() => setConfirmState({
                          title: t('common.delete'),
                          message: t('settings.visionModel.confirmDelete'),
                          danger: true,
                          onConfirm: () => void deleteModelConfig(config.id),
                        })}
                        data-testid={`delete-model-${config.id}`}
                      >
                        <TrashIcon />
                      </Button>
                    </div>
                  </div>
                ))}

                {modelConfigs.configs.length === 0 && (
                  <p className="px-5 py-6 text-center text-sm text-muted-foreground">
                    {t('settings.visionModel.empty')}
                  </p>
                )}
              </div>

              {testResult && (
                <div
                  className={cn(
                    'mx-5 mb-4 rounded-lg border p-3 text-sm',
                    testResult.success
                      ? tonePanelClass.success
                      : tonePanelClass.danger,
                  )}
                >
                  {testResult.success ? '\u2713 ' : '\u2717 '}
                  {testResult.message}
                </div>
              )}
            </CardContent>
          </Card>

          <div className="flex justify-end">
            <Button
              variant="outline"
              onClick={() => setConfirmState({
                title: t('settings.visionModel.reset'),
                message: t('settings.visionModel.confirmReset'),
                danger: true,
                onConfirm: () => void resetModelConfigs(),
              })}
              data-testid="reset-vision-models"
            >
              {t('settings.visionModel.reset')}
            </Button>
          </div>
        </div>
      </div>

      <Dialog
        open={showModal}
        onOpenChange={nextOpen => {
          if (!nextOpen) {
            setShowModal(false);
            setEditingId(null);
          }
        }}
      >
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {editingId ? t('settings.visionModel.dialog.editTitle') : t('settings.visionModel.dialog.createTitle')}
            </DialogTitle>
            <DialogDescription>{t('settings.visionModel.dialog.desc')}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label>{t('settings.visionModel.nameLabel')} *</Label>
              <Input
                value={form.name ?? ''}
                onChange={e => setForm(current => ({ ...current, name: e.target.value }))}
                placeholder={t('settings.visionModel.namePlaceholder')}
                data-testid="vision-model-name"
              />
            </div>

            <div className="space-y-1.5">
              <Label>{t('settings.visionModel.providerLabel')} *</Label>
              <Select
                value={form.provider ?? 'local'}
                onValueChange={value => setForm(current => ({ ...current, provider: value as ModelConfig['provider'] }))}
              >
                <SelectTrigger data-testid="vision-model-provider">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="local">{t('settings.visionModel.provider.local')}</SelectItem>
                  <SelectItem value="openai">{t('settings.visionModel.provider.openai')}</SelectItem>
                  <SelectItem value="custom">{t('settings.visionModel.provider.custom')}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label>{t('settings.visionModel.modelLabel')} *</Label>
              <Input
                value={form.model_name ?? ''}
                onChange={e => setForm(current => ({ ...current, model_name: e.target.value }))}
                className="font-mono text-sm"
                placeholder={form.provider === 'local' ? 'HaS-Image-YOLO11' : 'gpt-4-vision-preview'}
                data-testid="vision-model-model-name"
              />
            </div>

            {(form.provider === 'local' || form.provider === 'openai' || form.provider === 'custom') && (
              <div className="space-y-1.5">
                <Label>{t('settings.visionModel.baseUrlLabel')}</Label>
                <Input
                  value={form.base_url ?? ''}
                  onChange={e => setForm(current => ({ ...current, base_url: e.target.value }))}
                  className="font-mono text-sm"
                  placeholder={form.provider === 'local' ? 'http://127.0.0.1:8081' : 'https://api.openai.com'}
                  data-testid="vision-model-base-url"
                />
              </div>
            )}

            {(form.provider === 'openai' || form.provider === 'custom') && (
              <div className="space-y-1.5">
                <Label>{t('settings.visionModel.apiKeyLabel')}</Label>
                <Input
                  type="password"
                  value={form.api_key ?? ''}
                  onChange={e => setForm(current => ({ ...current, api_key: e.target.value }))}
                  className="font-mono text-sm"
                  placeholder="sk-..."
                  data-testid="vision-model-api-key"
                />
              </div>
            )}

            <div className="border-t pt-4">
              <h4 className="mb-3 text-sm font-medium">{t('settings.visionModel.advancedTitle')}</h4>
              <div className="grid grid-cols-3 gap-3">
                <div className="space-y-1">
                  <Label className="text-xs">{t('settings.visionModel.temperatureLabel')}</Label>
                  <Input
                    type="number"
                    step={0.1}
                    min={0}
                    max={2}
                    value={form.temperature ?? 0.8}
                    onChange={e => setForm(current => ({ ...current, temperature: parseFloat(e.target.value) }))}
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
                    onChange={e => setForm(current => ({ ...current, top_p: parseFloat(e.target.value) }))}
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
                    onChange={e => setForm(current => ({ ...current, max_tokens: parseInt(e.target.value, 10) }))}
                    data-testid="vision-model-max-tokens"
                  />
                </div>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <Switch
                checked={editingId && BUILTIN_VISION_IDS.has(editingId) ? true : (form.enabled ?? true)}
                disabled={Boolean(editingId && BUILTIN_VISION_IDS.has(editingId))}
                onCheckedChange={checked => setForm(current => ({ ...current, enabled: checked }))}
                data-testid="vision-model-enabled"
              />
              <Label>
                {t('settings.visionModel.enabledLabel')}
                {editingId && BUILTIN_VISION_IDS.has(editingId) && (
                  <span className="text-muted-foreground"> {t('settings.visionModel.enabledBuiltinHint')}</span>
                )}
              </Label>
            </div>

            <div className="space-y-1.5">
              <Label>{t('settings.visionModel.notesLabel')}</Label>
              <Textarea
                value={form.description ?? ''}
                onChange={e => setForm(current => ({ ...current, description: e.target.value }))}
                rows={2}
                placeholder={t('settings.visionModel.notesPlaceholder')}
                data-testid="vision-model-desc"
              />
            </div>
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setShowModal(false);
                setEditingId(null);
              }}
              data-testid="vision-model-cancel"
            >
              {t('settings.cancel')}
            </Button>
            <Button
              disabled={!form.name || !form.model_name}
              onClick={() => void handleSave()}
              data-testid="vision-model-save"
            >
              {editingId ? t('settings.save') : t('settings.create')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {confirmState && (
        <ConfirmDialog
          open
          title={confirmState.title}
          message={confirmState.message}
          danger={confirmState.danger}
          onConfirm={() => {
            confirmState.onConfirm();
            setConfirmState(null);
          }}
          onCancel={() => setConfirmState(null)}
        />
      )}
    </div>
  );
}

function PencilIcon() {
  return (
    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
      />
    </svg>
  );
}
