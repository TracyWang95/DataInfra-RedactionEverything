// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useState } from 'react';
import { useT } from '@/i18n';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { InteractionLockOverlay } from '@/components/InteractionLockOverlay';
import { useNerBackend } from './hooks/use-model-config';
import { ModelEndpointCard } from './components/model-endpoint-card';

export function TextModel() {
  const t = useT();
  const [confirmResetOpen, setConfirmResetOpen] = useState(false);
  const [resetting, setResetting] = useState(false);
  const {
    llamacppBaseUrl,
    setLlamacppBaseUrl,
    nerLoading,
    nerSaving,
    testing,
    testResult,
    nerLive,
    saveNerBackend,
    testConnection,
    clearNerOverride,
  } = useNerBackend();

  if (nerLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="h-7 w-7 animate-spin rounded-full border-2 border-muted border-t-foreground" />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-background">
      <div className="page-shell !max-w-[min(100%,1920px)] !px-3 !py-2 sm:!px-4 sm:!py-3">
        <div className="page-stack gap-3">
          <section className="surface-subtle flex shrink-0 flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <h1 className="text-2xl font-semibold tracking-tight text-foreground">{t('nav.textModel')}</h1>
              <p className="mt-0.5 max-w-5xl text-xs leading-5 text-muted-foreground">
                {t('settings.textModel.infoDesc')}
              </p>
            </div>
            <div className="flex shrink-0 flex-col items-start gap-2 sm:items-end">
              <div className="flex flex-wrap justify-end gap-1.5">
                <Badge variant="outline" className="whitespace-nowrap">
                  {t('settings.textModel.tag.openai')}
                </Badge>
                <Badge variant="outline" className="whitespace-nowrap">
                  {t('settings.textModel.tag.local')}
                </Badge>
                <Badge variant="outline" className="whitespace-nowrap">
                  {t('settings.textModel.tag.server')}
                </Badge>
              </div>
              <Button
                variant="outline"
                size="sm"
                className="h-8 whitespace-nowrap"
                onClick={() => setConfirmResetOpen(true)}
                data-testid="reset-ner-default"
              >
                {t('settings.textModel.reset')}
              </Button>
            </div>
          </section>

          <ModelEndpointCard
            title={t('nav.textModel')}
            description={t('settings.textModel.cardDescription')}
            endpointUrl={llamacppBaseUrl}
            onEndpointChange={setLlamacppBaseUrl}
            onTest={() => void testConnection()}
            onSave={() => void saveNerBackend()}
            testing={testing}
            saving={nerSaving}
            testResult={testResult}
            liveStatus={nerLive}
            placeholder="http://127.0.0.1:8080/v1"
            tags={[t('settings.textModel.tag.openai'), t('settings.textModel.tag.builtin')]}
            endpointLabel={t('settings.textModel.endpointLabel')}
            endpointHint={t('settings.textModel.endpointHint')}
          />
        </div>
      </div>
      <ConfirmDialog
        open={confirmResetOpen}
        title={t('settings.textModel.reset')}
        message={t('settings.textModel.confirmClearOverride')}
        danger
        onConfirm={() => {
          void (async () => {
            setConfirmResetOpen(false);
            setResetting(true);
            try {
              await clearNerOverride();
            } finally {
              setResetting(false);
            }
          })();
        }}
        onCancel={() => setConfirmResetOpen(false)}
      />
      <InteractionLockOverlay active={nerSaving || testing || resetting} />
    </div>
  );
}
