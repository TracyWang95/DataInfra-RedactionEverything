// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useState } from 'react';
import { useT } from '@/i18n';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { useNerBackend } from './hooks/use-model-config';
import { ModelEndpointCard } from './components/model-endpoint-card';

export function TextModel() {
  const t = useT();
  const [confirmResetOpen, setConfirmResetOpen] = useState(false);
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
      <div className="page-shell-narrow overflow-auto overscroll-contain">
        <div className="page-stack">
          <Card className="rounded-[24px] border-border/70 bg-muted/30 shadow-[var(--shadow-control)]">
            <CardHeader className="pb-3">
              <CardTitle className="text-base tracking-[-0.03em]">{t('settings.textModel.infoTitle')}</CardTitle>
              <CardDescription className="mt-2 text-sm leading-relaxed">
                {t('settings.textModel.infoDesc')}
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-0">
              <div className="flex flex-wrap gap-2 border-t pt-3">
                <Badge variant="outline">{t('settings.textModel.tag.openai')}</Badge>
                <Badge variant="outline">{t('settings.textModel.tag.local')}</Badge>
                <Badge variant="outline">{t('settings.textModel.tag.server')}</Badge>
              </div>
            </CardContent>
          </Card>

          <ModelEndpointCard
            title={t('settings.textModel.cardTitle')}
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
            tags={[
              t('settings.textModel.tag.openai'),
              t('settings.textModel.tag.builtin'),
            ]}
            endpointLabel={t('settings.textModel.endpointLabel')}
            endpointHint={t('settings.textModel.endpointHint')}
          />

          <div className="flex justify-end">
            <Button variant="outline" onClick={() => setConfirmResetOpen(true)} data-testid="reset-ner-default">
              {t('settings.textModel.reset')}
            </Button>
          </div>
        </div>
      </div>
      <ConfirmDialog
        open={confirmResetOpen}
        title={t('settings.textModel.reset')}
        message={t('settings.textModel.confirmClearOverride')}
        danger
        onConfirm={() => {
          setConfirmResetOpen(false);
          void clearNerOverride();
        }}
        onCancel={() => setConfirmResetOpen(false)}
      />
    </div>
  );
}
