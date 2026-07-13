// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { tonePanelClass } from '@/utils/toneClasses';

interface ModelEndpointCardProps {
  title: string;
  description: string;
  endpointUrl: string;
  onEndpointChange: (url: string) => void;
  onTest: () => void;
  onSave: () => void;
  testing: boolean;
  saving: boolean;
  testResult: { success: boolean; message: string } | null;
  liveStatus?: 'online' | 'offline';
  placeholder?: string;
  tags?: string[];
  endpointLabel?: string;
  endpointHint?: string;
}

export function ModelEndpointCard({
  title,
  description,
  endpointUrl,
  onEndpointChange,
  onTest,
  onSave,
  testing,
  saving,
  testResult,
  liveStatus,
  placeholder,
  tags,
  endpointLabel,
  endpointHint,
}: ModelEndpointCardProps) {
  const t = useT();

  return (
    <Card className="overflow-hidden border-border/70 shadow-[var(--shadow-control)]">
      <CardHeader className="px-4 pb-2 pt-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 space-y-1">
            <CardTitle className="text-base">{title}</CardTitle>
            <CardDescription className="max-w-3xl text-xs leading-5">{description}</CardDescription>
            <div className="flex flex-wrap items-center gap-1.5 pt-1">
              <Badge variant="secondary" className="whitespace-nowrap">
                {t('common.enabled')}
              </Badge>
              {liveStatus === 'online' && (
                <Badge
                  className={`whitespace-nowrap ${tonePanelClass.success}`}
                >
                  {t('common.online')}
                </Badge>
              )}
              {liveStatus === 'offline' && (
                <Badge variant="destructive" className="whitespace-nowrap">
                  {t('common.offline')}
                </Badge>
              )}
              {liveStatus === undefined && (
                <Badge variant="outline" className="whitespace-nowrap">
                  {t('common.checking')}
                </Badge>
              )}
              {tags?.map((tag) => (
                <Badge
                  key={tag}
                  variant="outline"
                  className="whitespace-nowrap"
                >
                  {tag}
                </Badge>
              ))}
            </div>
          </div>
          <Button
            size="sm"
            className="h-8 shrink-0 whitespace-nowrap"
            onClick={onSave}
            disabled={saving}
            data-testid="save-endpoint"
          >
            {saving ? t('common.saving') : t('common.saveConfig')}
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-3 px-4 pb-4 pt-0">
        <div className="space-y-1">
          <Label className="text-xs">{endpointLabel ?? t('common.endpointUrl')}</Label>
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center">
            <Input
              value={endpointUrl}
              onChange={(e) => onEndpointChange(e.target.value)}
              placeholder={placeholder ?? 'http://127.0.0.1:8080/v1'}
              className="h-9 min-w-0 flex-1 font-mono text-sm"
              data-testid="endpoint-url"
            />
            <Button
              size="sm"
              variant="outline"
              className="h-9 shrink-0 whitespace-nowrap"
              onClick={onTest}
              disabled={testing}
              data-testid="test-endpoint"
            >
              {testing ? t('common.testing') : t('common.test')}
            </Button>
          </div>
          {endpointHint && <p className="text-xs text-muted-foreground">{endpointHint}</p>}
        </div>

        {testResult && (
          <div
            className={cn(
              'rounded-lg border px-3 py-2 text-xs leading-5',
              testResult.success ? tonePanelClass.success : tonePanelClass.danger,
            )}
          >
            {testResult.success ? '\u2713 ' : '\u2717 '}
            {testResult.message}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
