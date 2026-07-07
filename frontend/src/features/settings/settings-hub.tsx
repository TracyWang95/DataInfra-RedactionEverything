// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useState } from 'react';
import { useT } from '@/i18n';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { InteractionLockOverlay } from '@/components/InteractionLockOverlay';
import { useEntityTypes } from './hooks/use-entity-types';
import { EntityTypeList } from './components/entity-type-list';
import { EntityTypeDialog } from './components/entity-type-dialog';
import { PipelineConfigPanel } from './components/pipeline-config';

export function SettingsHub() {
  const t = useT();
  const panelIntroClass =
    'surface-subtle flex min-h-10 items-center px-4 py-2.5 text-xs leading-5 text-muted-foreground';
  const {
    entityTypes: _entityTypes,
    textTaxonomy,
    pipelines,
    loading,
    pipelinesLoading,
    textRuleTypes,
    loadError,
    importFileRef,
    createType,
    updateType,
    deleteType,
    resetToDefault,
    createPipelineType,
    updatePipelineType,
    deletePipelineType,
    resetPipelines,
    handleExportPresets,
    handleImportPresets,
    fetchEntityTypes,
    fetchPipelines,
  } = useEntityTypes();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [confirmState, setConfirmState] = useState<{
    title: string;
    message: string;
    danger?: boolean;
    onConfirm: () => void | Promise<void>;
  } | null>(null);

  const [editingType, setEditingType] = useState<(typeof _entityTypes)[number] | null>(null);
  const [operationLoading, setOperationLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const runLocked = async (action: () => void | Promise<void>) => {
    if (operationLoading) return;
    setOperationLoading(true);
    try {
      await action();
    } finally {
      setOperationLoading(false);
    }
  };

  const openAdd = () => {
    setEditingType(null);
    setDialogOpen(true);
  };

  const openEdit = (tp: (typeof _entityTypes)[number]) => {
    setEditingType(tp);
    setDialogOpen(true);
  };

  const handleSave = async (form: {
    name: string;
    description: string;
    regex_pattern: string;
    use_llm: boolean;
    tag_template: string;
    data_domain: string;
    generic_target: string;
    coref_enabled: boolean;
  }) => {
    setSaving(true);
    try {
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
        tag_template: form.tag_template,
        data_domain: form.data_domain,
        generic_target: form.generic_target,
        coref_enabled: form.coref_enabled,
      });
      if (ok) setDialogOpen(false);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="h-7 w-7 animate-spin rounded-full border-2 border-muted border-t-foreground" />
      </div>
    );
  }

  return (
    <div className="saas-page flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background">
      <div className="page-shell !max-w-[min(100%,1920px)] !px-3 !py-2 sm:!px-4 sm:!py-3">
        <Tabs defaultValue="text" className="page-stack gap-3 overflow-hidden">
          {loadError && (
            <Alert variant="destructive" data-testid="settings-load-error">
              <AlertDescription className="flex items-center justify-between gap-3">
                <span>{loadError}</span>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 shrink-0"
                  onClick={() => {
                    void fetchEntityTypes();
                    void fetchPipelines();
                  }}
                >
                  {t('common.retry')}
                </Button>
              </AlertDescription>
            </Alert>
          )}

          <div className="flex shrink-0 flex-wrap items-center justify-between gap-3">
            <TabsList
              className="rounded-xl border border-border/70 bg-muted/40 p-1"
              data-testid="settings-tabs"
            >
              <TabsTrigger value="text" className="whitespace-nowrap" data-testid="tab-text">
                {t('settings.textRules')}
              </TabsTrigger>
              <TabsTrigger value="vision" className="whitespace-nowrap" data-testid="tab-vision">
                {t('settings.visionRules')}
              </TabsTrigger>
            </TabsList>
            <div className="control-cluster">
              <Button
                size="sm"
                variant="outline"
                className="whitespace-nowrap"
                onClick={() => void runLocked(handleExportPresets)}
                disabled={operationLoading}
                data-testid="export-presets"
              >
                {t('settings.exportPresets')}
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="whitespace-nowrap"
                onClick={() => importFileRef.current?.click()}
                disabled={operationLoading}
                data-testid="import-presets"
              >
                {t('settings.importPresets')}
              </Button>
              <input
                ref={importFileRef}
                type="file"
                accept=".json"
                onChange={(event) => void runLocked(() => handleImportPresets(event))}
                className="hidden"
              />
            </div>
          </div>

          <TabsContent
            value="text"
            className="mt-0 flex min-h-0 flex-1 flex-col gap-3 overflow-hidden"
          >
            <div className={panelIntroClass} data-testid="settings-text-intro">
              {t('settings.textPipelineIntro')}
            </div>
            <div className="flex min-h-0 flex-1 overflow-hidden">
              <EntityTypeList
                types={textRuleTypes}
                variant="llm"
                onAdd={openAdd}
                onEdit={openEdit}
                onDelete={(id) =>
                  setConfirmState({
                    title: t('common.delete'),
                    message: t('settings.confirmDeleteType'),
                    danger: true,
                    onConfirm: () => deleteType(id),
                  })
                }
                onReset={() =>
                  setConfirmState({
                    title: t('settings.resetTextRules'),
                    message: t('settings.confirmReset'),
                    danger: true,
                    onConfirm: () => resetToDefault(),
                  })
                }
              />
            </div>
          </TabsContent>

          <TabsContent
            value="vision"
            className="mt-0 flex min-h-0 flex-1 flex-col gap-3 overflow-hidden"
          >
            <div className={panelIntroClass} data-testid="settings-vision-intro">
              {t('settings.pipelineDisplayName.ocr')} / {t('settings.pipelineDisplayName.image')}
            </div>
            <PipelineConfigPanel
              loading={pipelinesLoading}
              pipelines={pipelines}
              onCreateType={createPipelineType}
              onUpdateType={updatePipelineType}
              onDeleteType={(mode, id) =>
                setConfirmState({
                  title: t('common.delete'),
                  message: t('settings.confirmDeleteType'),
                  danger: true,
                  onConfirm: () => deletePipelineType(mode, id),
                })
              }
              onReset={() =>
                setConfirmState({
                  title: t('settings.resetVisionRules'),
                  message: t('settings.confirmResetPipelines'),
                  danger: true,
                  onConfirm: () => resetPipelines(),
                })
              }
            />
          </TabsContent>
        </Tabs>
      </div>

      <EntityTypeDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        mode={editingType ? 'edit' : 'create'}
        saving={saving}
        initial={
          editingType
            ? {
                name: editingType.name,
                description: editingType.description ?? '',
                regex_pattern: editingType.regex_pattern ?? '',
                use_llm: !!editingType.use_llm,
                tag_template: editingType.tag_template ?? '',
                data_domain: editingType.data_domain ?? 'custom_extension',
                generic_target: editingType.generic_target ?? 'GEN_DOCUMENT_RECORD',
                coref_enabled: Boolean(editingType.coref_enabled),
              }
            : { use_llm: true, coref_enabled: true }
        }
        taxonomy={textTaxonomy}
        onSave={(form) => void handleSave(form)}
      />
      {confirmState && (
        <ConfirmDialog
          open
          title={confirmState.title}
          message={confirmState.message}
          danger={confirmState.danger}
          onConfirm={() =>
            void runLocked(async () => {
              setConfirmState(null);
              await confirmState.onConfirm();
            })
          }
          onCancel={() => setConfirmState(null)}
        />
      )}
      <InteractionLockOverlay active={operationLoading || saving} />
    </div>
  );
}
