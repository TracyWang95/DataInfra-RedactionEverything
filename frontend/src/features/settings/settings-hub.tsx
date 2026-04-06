
import { useState } from 'react';
import { useT } from '@/i18n';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { useEntityTypes } from './hooks/use-entity-types';
import { EntityTypeList } from './components/entity-type-list';
import { EntityTypeDialog } from './components/entity-type-dialog';
import { PipelineConfigPanel } from './components/pipeline-config';

export function SettingsHub() {
  const t = useT();
  const panelIntroClass = 'surface-subtle px-4 py-3 text-sm text-muted-foreground';
  const {
    entityTypes: _entityTypes, pipelines, loading, pipelinesLoading, regexTypes, llmTypes, previewMode,
    importFileRef, createType, updateType, deleteType, resetToDefault,
    createPipelineType, updatePipelineType, deletePipelineType, resetPipelines,
    handleExportPresets, handleImportPresets,
  } = useEntityTypes();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogUseLlm, setDialogUseLlm] = useState(true);
  const [confirmState, setConfirmState] = useState<{
    title: string;
    message: string;
    danger?: boolean;
    onConfirm: () => void;
  } | null>(null);

  const [editingType, setEditingType] = useState<typeof _entityTypes[number] | null>(null);

  const openAdd = (useLlm: boolean) => {
    setEditingType(null);
    setDialogUseLlm(useLlm);
    setDialogOpen(true);
  };

  const openEdit = (tp: typeof _entityTypes[number]) => {
    setEditingType(tp);
    setDialogUseLlm(!!tp.use_llm);
    setDialogOpen(true);
  };

  const handleSave = async (form: {
    name: string; description: string;
    regex_pattern: string; use_llm: boolean; tag_template: string;
  }) => {
    if (editingType) {
      const ok = await updateType(editingType.id, form);
      if (ok) {
        setDialogOpen(false);
        setEditingType(null);
      }
      return;
    }
    const ok = await createType({
      name: form.name,
      description: form.description,
      regex_pattern: form.regex_pattern,
      use_llm: form.use_llm,
    });
    if (ok) setDialogOpen(false);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="w-7 h-7 border-2 border-muted border-t-foreground rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="saas-page flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background">
      <div className="page-shell">
        <Tabs defaultValue="text" className="page-stack overflow-hidden gap-3">
          {previewMode && (
            <Alert>
              <AlertDescription>{t('settings.redaction.previewBanner')}</AlertDescription>
            </Alert>
          )}

          <div className="flex shrink-0 flex-wrap items-center justify-between gap-3">
            <TabsList className="rounded-xl border border-border/70 bg-muted/40 p-1" data-testid="settings-tabs">
              <TabsTrigger value="text" data-testid="tab-text">{t('settings.textRules')}</TabsTrigger>
              <TabsTrigger value="vision" data-testid="tab-vision">{t('settings.visionRules')}</TabsTrigger>
            </TabsList>
            <div className="control-cluster">
              <Button size="sm" variant="outline" onClick={() => void handleExportPresets()} data-testid="export-presets">
                {t('settings.exportPresets')}
              </Button>
              <Button size="sm" variant="outline" onClick={() => importFileRef.current?.click()} data-testid="import-presets">
                {t('settings.importPresets')}
              </Button>
              <input
                ref={importFileRef}
                type="file"
                accept=".json"
                onChange={handleImportPresets}
                className="hidden"
              />
            </div>
          </div>

          {}
          <TabsContent value="text" className="mt-0 flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
            <div className={panelIntroClass} data-testid="settings-text-intro">
              {t('settings.regex')} + {t('settings.aiSemantic')} | {t('settings.dualRules')}
            </div>
            <Tabs defaultValue="regex" className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden">
              <div className="shrink-0 flex items-center gap-2">
                <TabsList className="rounded-xl border border-border/70 bg-muted/40 p-1">
                  <TabsTrigger value="regex" data-testid="subtab-regex">
                    {t('settings.regex')}
                    <span className="ml-1 text-muted-foreground">({regexTypes.length})</span>
                  </TabsTrigger>
                  <TabsTrigger value="llm" data-testid="subtab-llm">
                    {t('settings.semantic')}
                    <span className="ml-1 text-muted-foreground">({llmTypes.length})</span>
                  </TabsTrigger>
                </TabsList>
              </div>
              <TabsContent value="regex" className="mt-0 flex min-h-0 flex-1 overflow-hidden">
                <EntityTypeList
                  types={regexTypes}
                  variant="regex"
                  onAdd={() => openAdd(false)}
                  onEdit={openEdit}
                  onDelete={id => setConfirmState({
                    title: t('common.delete'),
                    message: t('settings.confirmDeleteType'),
                    danger: true,
                    onConfirm: () => void deleteType(id),
                  })}
                  onReset={() => setConfirmState({
                    title: t('settings.resetTextRules'),
                    message: t('settings.confirmReset'),
                    danger: true,
                    onConfirm: () => void resetToDefault(),
                  })}
                />
              </TabsContent>
              <TabsContent value="llm" className="mt-0 flex min-h-0 flex-1 overflow-hidden">
                <EntityTypeList
                  types={llmTypes}
                  variant="llm"
                  onAdd={() => openAdd(true)}
                  onEdit={openEdit}
                  onDelete={id => setConfirmState({
                    title: t('common.delete'),
                    message: t('settings.confirmDeleteType'),
                    danger: true,
                    onConfirm: () => void deleteType(id),
                  })}
                  onReset={() => setConfirmState({
                    title: t('settings.resetTextRules'),
                    message: t('settings.confirmReset'),
                    danger: true,
                    onConfirm: () => void resetToDefault(),
                  })}
                />
              </TabsContent>
            </Tabs>
          </TabsContent>

          {}
          <TabsContent value="vision" className="mt-0 flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
            <div className={panelIntroClass} data-testid="settings-vision-intro">
              {t('settings.pipelineDisplayName.ocr')} + {t('settings.pipelineDisplayName.image')} | {t('settings.twoMergedOutput')}
            </div>
            <PipelineConfigPanel
              loading={pipelinesLoading}
              pipelines={pipelines}
              onCreateType={createPipelineType}
              onUpdateType={updatePipelineType}
              onDeleteType={(mode, id) => setConfirmState({
                title: t('common.delete'),
                message: t('settings.confirmDeleteType'),
                danger: true,
                onConfirm: () => void deletePipelineType(mode, id),
              })}
              onReset={() => setConfirmState({
                title: t('settings.resetVisionRules'),
                message: t('settings.confirmResetPipelines'),
                danger: true,
                onConfirm: () => void resetPipelines(),
              })}
            />
          </TabsContent>
        </Tabs>
      </div>

      {}
      <EntityTypeDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        mode={editingType ? 'edit' : 'create'}
        initial={editingType ? {
          name: editingType.name,
          description: editingType.description ?? '',
          regex_pattern: editingType.regex_pattern ?? '',
          use_llm: !!editingType.use_llm,
          tag_template: editingType.tag_template ?? '',
        } : { use_llm: dialogUseLlm }}
        onSave={form => void handleSave(form)}
      />
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
