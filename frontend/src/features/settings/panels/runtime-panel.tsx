// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useEffect, useState } from 'react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useT } from '@/i18n';
import { authFetch } from '@/services/api-client';
import { localizeErrorMessage } from '@/utils/localizeError';
import { PanelHeading, parseJson } from './shared';

interface ConcurrencySettings {
  job_concurrency: number;
  default_job_concurrency: number;
  min_job_concurrency: number;
  max_job_concurrency: number;
}

export function AdminRuntimePanel() {
  const t = useT();
  const [settings, setSettings] = useState<ConcurrencySettings | null>(null);
  const [value, setValue] = useState('3');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await authFetch('/api/v1/auth/concurrency');
        const body = await parseJson<ConcurrencySettings & { detail?: string }>(res);
        if (!res.ok || !body) throw new Error(body?.detail || `HTTP ${res.status}`);
        if (!cancelled) {
          setSettings(body);
          setValue(String(body.job_concurrency));
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(localizeErrorMessage(err, 'system.error.loadSettings'));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const next = Number.parseInt(value, 10);
      const res = await authFetch('/api/v1/auth/concurrency', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_concurrency: next }),
      });
      const body = await parseJson<ConcurrencySettings & { detail?: string }>(res);
      if (!res.ok || !body) throw new Error(body?.detail || `HTTP ${res.status}`);
      setSettings(body);
      setValue(String(body.job_concurrency));
    } catch (err) {
      setError(localizeErrorMessage(err, 'system.error.saveSettings'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="surface-subtle max-w-2xl space-y-4 p-4" data-testid="admin-runtime-panel">
      <PanelHeading title="运行配置" description="控制后台批量任务并发，不需要重启模型服务。" />
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <div className="space-y-2">
        <Label htmlFor="job-concurrency">{t('settings.runtime.jobConcurrency')}</Label>
        <div className="flex max-w-xs items-center gap-2">
          <Input
            id="job-concurrency"
            type="number"
            min={settings?.min_job_concurrency ?? 1}
            max={settings?.max_job_concurrency ?? 16}
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
          <Button type="button" disabled={saving} onClick={() => void save()}>
            {saving ? t('settings.saving') : t('settings.save')}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          {t('settings.runtime.jobConcurrencyHint')
            .replace('{current}', String(settings?.job_concurrency ?? 3))
            .replace('{default}', String(settings?.default_job_concurrency ?? 3))}
        </p>
      </div>
    </section>
  );
}
