// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useMemo, useState } from 'react';
import { authFetch } from '@/services/api-client';
import { useT } from '@/i18n';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  getRegexModalCheck,
} from '../hooks/use-entity-types';

interface EntityTypeForm {
  name: string;
  description: string;
  regex_pattern: string;
  use_llm: boolean;
  tag_template: string;
}

interface EntityTypeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initial?: Partial<EntityTypeForm>;
  onSave: (form: EntityTypeForm) => void;
  mode: 'create' | 'edit';
  saving?: boolean;
}

const buildDefaultForm = (initial?: Partial<EntityTypeForm>): EntityTypeForm => {
  const useLlm = initial?.use_llm ?? true;
  return {
    name: initial?.name ?? '',
    description: initial?.description ?? '',
    regex_pattern: initial?.regex_pattern ?? '',
    use_llm: useLlm,
    tag_template: initial?.tag_template ?? '',
  };
};

export function EntityTypeDialog({
  open,
  onOpenChange,
  initial,
  onSave,
  mode,
  saving = false,
}: EntityTypeDialogProps) {
  const t = useT();
  const [form, setForm] = useState<EntityTypeForm>(buildDefaultForm(initial));
  const [sampleText, setSampleText] = useState('');
  const [serverResult, setServerResult] = useState<{
    valid: boolean;
    matches: { text: string; start: number; end: number }[];
    error: string;
  } | null>(null);
  const [serverTesting, setServerTesting] = useState(false);

  useEffect(() => {
    if (!open) return;
    setForm(buildDefaultForm(initial));
    setSampleText('');
    setServerResult(null);
  }, [initial, open]);

  const resetOnOpen = (nextOpen: boolean) => {
    onOpenChange(nextOpen);
  };

  const regexCheck = useMemo(
    () => getRegexModalCheck(form.regex_pattern, sampleText),
    [form.regex_pattern, sampleText],
  );

  const handleServerTest = async () => {
    if (!form.regex_pattern.trim()) return;

    setServerTesting(true);
    try {
      const res = await authFetch('/api/v1/custom-types/regex-test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pattern: form.regex_pattern, test_text: sampleText }),
      });
      setServerResult(await res.json());
    } catch {
      setServerResult({ valid: false, matches: [], error: t('settings.requestFailed') });
    } finally {
      setServerTesting(false);
    }
  };

  const canSubmit = Boolean(
    form.name.trim() &&
    (form.use_llm ||
      (form.regex_pattern.trim() &&
        regexCheck !== 'invalid_pattern' &&
        regexCheck !== 'matches_empty')),
  );

  const dialogTitle = mode === 'create'
    ? (form.use_llm ? t('settings.addSemanticType') : t('settings.addRegexType'))
    : t('settings.editType');

  const dialogDescription = form.use_llm
    ? t('settings.addSemanticDesc')
    : t('settings.addRegexDesc');

  return (
    <Dialog open={open} onOpenChange={resetOnOpen}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{dialogTitle}</DialogTitle>
          <DialogDescription>{dialogDescription}</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4 py-2">
          <div className="flex flex-col gap-1.5">
            <Label>{t('settings.nameLabel')} *</Label>
            <Input
              value={form.name}
              onChange={e => setForm(current => ({ ...current, name: e.target.value }))}
              placeholder={form.use_llm
                ? t('settings.typeNamePlaceholder.semantic')
                : t('settings.typeNamePlaceholder.regex')}
              data-testid="entity-type-name"
            />
          </div>

          {!form.use_llm && (
            <>
              <div className="flex flex-col gap-1.5">
                <Label>{t('settings.regexLabel')} *</Label>
                <Textarea
                  value={form.regex_pattern}
                  onChange={e => setForm(current => ({ ...current, regex_pattern: e.target.value }))}
                  rows={3}
                  className="font-mono"
                  placeholder={t('settings.regexPlaceholder')}
                  spellCheck={false}
                  data-testid="entity-type-regex"
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label>{t('settings.testMatchLabel')}</Label>
                <Textarea
                  value={sampleText}
                  onChange={e => setSampleText(e.target.value)}
                  rows={3}
                  placeholder={t('settings.testMatchPlaceholder')}
                  data-testid="entity-type-sample"
                />
              </div>

              <div className="rounded-2xl border border-border/70 bg-muted/20 px-3.5 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-xs">
                      {t('settings.regexValidation')}
                    </Badge>
                    {regexCheck === 'empty_pattern' && (
                      <span className="text-sm text-muted-foreground">{t('settings.regexEmpty')}</span>
                    )}
                    {regexCheck === 'invalid_pattern' && (
                      <span className="text-sm font-medium text-destructive">{t('settings.regexInvalid')}</span>
                    )}
                    {regexCheck === 'matches_empty' && (
                      <span className="text-sm font-medium text-[var(--warning-foreground)]">
                        {t('settings.regexMatchesEmpty')}
                      </span>
                    )}
                    {regexCheck === 'no_sample' && (
                      <span className="text-sm text-muted-foreground">{t('settings.regexReady')}</span>
                    )}
                    {regexCheck === 'pass' && (
                      <span className="text-sm font-medium text-[var(--success-foreground)]">
                        {t('settings.regexPass')}
                      </span>
                    )}
                    {regexCheck === 'fail' && (
                      <span className="text-sm font-medium text-destructive">{t('settings.regexFail')}</span>
                    )}
                  </div>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={
                      !form.regex_pattern.trim() ||
                      regexCheck === 'invalid_pattern' ||
                      regexCheck === 'matches_empty' ||
                      serverTesting
                    }
                    onClick={() => void handleServerTest()}
                    data-testid="entity-type-test-regex"
                  >
                    {serverTesting ? t('settings.testing') : t('settings.testRegex')}
                  </Button>
                </div>

                {serverResult && (
                  <div className="mt-3 rounded-xl border border-border/70 bg-background px-3 py-2.5 text-sm">
                    {serverResult.valid ? (
                      <div>
                        <span className="font-medium text-[var(--success-foreground)]">
                          {t('settings.matchCount').replace('{n}', String(serverResult.matches.length))}
                        </span>
                        {serverResult.matches.length > 0 ? (
                          <div className="mt-2 flex flex-wrap gap-1.5">
                            {serverResult.matches.map((match, index) => (
                              <span
                                key={`${match.text}-${index}`}
                                className="inline-block rounded border border-[var(--warning-border)] bg-[var(--warning-surface)] px-1.5 py-0.5 font-mono text-xs text-[var(--warning-foreground)]"
                              >
                                {match.text}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <p className="mt-1 text-xs text-muted-foreground">
                            {t('settings.regexValidNoMatch')}
                          </p>
                        )}
                      </div>
                    ) : (
                      <span className="font-medium text-destructive">{serverResult.error}</span>
                    )}
                  </div>
                )}
              </div>
            </>
          )}

          {form.use_llm && (
            <div className="flex flex-col gap-1.5">
              <Label>{t('settings.descLabel')}</Label>
              <Textarea
                value={form.description}
                onChange={e => setForm(current => ({ ...current, description: e.target.value }))}
                rows={4}
                placeholder={t('settings.semanticDescriptionPlaceholder')}
                data-testid="entity-type-description"
              />
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <Label>{t('settings.tagTemplateLabel')}</Label>
            <Input
              value={form.tag_template}
              onChange={e => setForm(current => ({ ...current, tag_template: e.target.value }))}
              placeholder={t('settings.tagTemplatePlaceholder')}
              data-testid="entity-type-tag-template"
            />
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => resetOnOpen(false)}
            data-testid="entity-type-cancel"
          >
            {t('settings.cancel')}
          </Button>
          <Button
            disabled={!canSubmit || saving}
            onClick={() => onSave(form)}
            data-testid="entity-type-save"
          >
            {saving ? t('settings.saving') : mode === 'create' ? t('settings.create') : t('settings.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
