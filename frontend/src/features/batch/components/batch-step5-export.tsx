// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { memo } from 'react';

import { useT } from '@/i18n';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Badge } from '@/components/ui/badge';
import {
  getRedactionStateLabel,
  resolveRedactionState,
} from '@/utils/redactionState';

import type { BatchRow, Step } from '../types';

interface BatchStep5ExportProps {
  rows: BatchRow[];
  selected: Set<string>;
  selectedIds: string[];
  zipLoading: boolean;
  toggle: (id: string) => void;
  goStep: (s: Step) => void;
  downloadZip: (redacted: boolean) => Promise<void>;
}

function BatchStep5ExportInner({
  rows,
  selected,
  selectedIds,
  zipLoading,
  toggle,
  goStep,
  downloadZip,
}: BatchStep5ExportProps) {
  const t = useT();

  return (
    <Card className="flex min-h-0 flex-1 flex-col overflow-hidden" data-testid="batch-step5-export">
      <CardHeader className="shrink-0">
        <CardTitle className="text-sm">{t('batchWizard.step5.title')}</CardTitle>
        <p className="text-xs text-muted-foreground">
          {t('batchWizard.step5.desc')}
        </p>
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto overscroll-contain">
        {}
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            onClick={() => goStep(4)}
            data-testid="step5-back-review"
          >
            {t('batchWizard.step5.backReview')}
          </Button>
          <Button
            onClick={() => void downloadZip(false)}
            disabled={zipLoading || !selectedIds.length}
            data-testid="download-original"
          >
            {zipLoading ? t('batchWizard.step5.downloading') : t('batchWizard.step5.downloadOriginal')}
          </Button>
          <Button
            variant="outline"
            onClick={() => void downloadZip(true)}
            disabled={zipLoading || !selectedIds.length}
            data-testid="download-redacted"
          >
            {zipLoading ? t('batchWizard.step5.downloading') : t('batchWizard.step5.downloadRedacted')}
          </Button>
        </div>

        {}
        <div className="border rounded-lg divide-y max-h-72 overflow-y-auto">
          {rows.map(r => {
            const rs = resolveRedactionState(r.has_output, r.analyzeStatus);
            return (
              <div
                key={r.file_id}
                className="px-4 py-2 flex items-center gap-3 text-sm"
              >
                <Checkbox
                  checked={selected.has(r.file_id)}
                  onCheckedChange={() => toggle(r.file_id)}
                  data-testid={`export-check-${r.file_id}`}
                />
                <span className="flex-1 truncate">{r.original_filename}</span>
                <Badge
                  variant={rs === 'redacted' ? 'default' : rs === 'unredacted' ? 'outline' : 'secondary'}
                  className="text-xs"
                >
                  {getRedactionStateLabel(rs)}
                </Badge>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

export const BatchStep5Export = memo(BatchStep5ExportInner);
