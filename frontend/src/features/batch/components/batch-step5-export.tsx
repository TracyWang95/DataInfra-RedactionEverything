/**
 * BatchStep5Export — Step 5: Export redacted files as ZIP.
 * Provides download buttons for original and redacted ZIPs,
 * with file selection and status display.
 */
import { useT } from '@/i18n';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Badge } from '@/components/ui/badge';
import {
  resolveRedactionState,
  REDACTION_STATE_LABEL,
} from '@/utils/redactionState';
import type { Step, BatchRow } from '../hooks/use-batch-wizard';

interface BatchStep5ExportProps {
  rows: BatchRow[];
  selected: Set<string>;
  selectedIds: string[];
  zipLoading: boolean;
  toggle: (id: string) => void;
  goStep: (s: Step) => void;
  downloadZip: (redacted: boolean) => Promise<void>;
}

export function BatchStep5Export({
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
    <Card data-testid="batch-step5-export">
      <CardHeader>
        <CardTitle className="text-sm">{t('batchWizard.step5.title')}</CardTitle>
        <p className="text-xs text-muted-foreground">
          {t('batchWizard.step5.desc')}
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Action buttons */}
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

        {/* File list with checkboxes */}
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
                  {REDACTION_STATE_LABEL[rs]}
                </Badge>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
