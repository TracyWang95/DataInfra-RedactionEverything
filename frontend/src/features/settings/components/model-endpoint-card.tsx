// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

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
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-1">
            <CardTitle className="text-base">{title}</CardTitle>
            <CardDescription className="text-xs leading-relaxed">{description}</CardDescription>
          </div>
          <Button size="sm" onClick={onSave} disabled={saving} data-testid="save-endpoint">
            {saving ? t('common.saving') : t('common.saveConfig')}
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">{title}</span>
          <Badge variant="secondary" className="text-xs">
            {t('common.enabled')}
          </Badge>
          {liveStatus === 'online' && (
            <Badge className={`text-xs ${tonePanelClass.success}`}>
              {t('common.online')}
            </Badge>
          )}
          {liveStatus === 'offline' && (
            <Badge variant="destructive" className="text-xs">
              {t('common.offline')}
            </Badge>
          )}
          {liveStatus === undefined && (
            <Badge variant="outline" className="text-xs">
              {t('common.checking')}
            </Badge>
          )}
          {tags?.map(tag => (
            <Badge key={tag} variant="outline" className="text-xs">
              {tag}
            </Badge>
          ))}
        </div>

        <div className="space-y-1.5">
          <Label>{endpointLabel ?? t('common.endpointUrl')}</Label>
          <div className="flex items-center gap-2">
            <Input
              value={endpointUrl}
              onChange={e => onEndpointChange(e.target.value)}
              placeholder={placeholder ?? 'http://127.0.0.1:8080/v1'}
              className="flex-1 font-mono text-sm"
              data-testid="endpoint-url"
            />
            <Button size="sm" variant="outline" onClick={onTest} disabled={testing} data-testid="test-endpoint">
              {testing ? t('common.testing') : t('common.test')}
            </Button>
          </div>
          {endpointHint && <p className="text-xs text-muted-foreground">{endpointHint}</p>}
        </div>

        {testResult && (
          <div
            className={cn(
              'rounded-lg border p-3 text-sm',
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
  );
}
