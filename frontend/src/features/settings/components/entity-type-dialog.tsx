// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useCallback, useId, useMemo, useState, type SetStateAction } from 'react';
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
import { Button } from '@/components/ui/button';

interface EntityTypeForm {
  name: string;
  description: string;
  regex_pattern: string;
  use_llm: boolean;
  tag_template: string;
  data_domain: string;
  generic_target: string;
  coref_enabled: boolean;
}

interface EntityTypeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initial?: Partial<EntityTypeForm>;
  taxonomy: TextTaxonomyDomain[];
  onSave: (form: EntityTypeForm) => void;
  mode: 'create' | 'edit';
  saving?: boolean;
}

interface TaxonomyTargetOption {
  value: string;
  label: string;
}

interface TextTaxonomyDomain {
  value: string;
  label: string;
  default_target: string;
  targets: TaxonomyTargetOption[];
}

const EMPTY_TAXONOMY: TextTaxonomyDomain[] = [
  {
    value: 'custom_extension',
    label: '其他文本',
    default_target: 'GEN_DOCUMENT_RECORD',
    targets: [{ value: 'GEN_DOCUMENT_RECORD', label: '其他文本记录' }],
  },
];

function getEffectiveTaxonomy(taxonomy: TextTaxonomyDomain[]) {
  return taxonomy.length ? taxonomy : EMPTY_TAXONOMY;
}

function buildDefaultForm(
  initial: Partial<EntityTypeForm> | undefined,
  taxonomy: TextTaxonomyDomain[],
): EntityTypeForm {
  const domains = getEffectiveTaxonomy(taxonomy);
  const domainByValue = new Map(domains.map((domain) => [domain.value, domain]));
  const dataDomain = initial?.data_domain && domainByValue.has(initial.data_domain)
    ? initial.data_domain
    : domains[0].value;
  const domain = domainByValue.get(dataDomain) ?? domains[0];
  const allowedTargets = domain.targets;
  const initialTarget = initial?.generic_target ?? '';
  const genericTarget = allowedTargets.some((option) => option.value === initialTarget)
    ? initialTarget
    : domain.default_target;
  return {
    name: initial?.name ?? '',
    description: initial?.description ?? '',
    regex_pattern: initial?.regex_pattern ?? '',
    use_llm: initial?.use_llm ?? true,
    tag_template: initial?.tag_template ?? '',
    data_domain: dataDomain,
    generic_target: genericTarget,
    coref_enabled: initial?.coref_enabled ?? true,
  };
}

export function EntityTypeDialog({
  open,
  onOpenChange,
  initial,
  taxonomy,
  onSave,
  mode,
  saving = false,
}: EntityTypeDialogProps) {
  const t = useT();
  const effectiveTaxonomy = useMemo(() => getEffectiveTaxonomy(taxonomy), [taxonomy]);
  const defaultForm = useMemo(
    () => buildDefaultForm(initial, effectiveTaxonomy),
    [effectiveTaxonomy, initial],
  );
  const formKey = useMemo(
    () =>
      [
        open ? 'open' : 'closed',
        mode,
        initial?.name ?? '',
        initial?.data_domain ?? '',
        initial?.generic_target ?? '',
        effectiveTaxonomy
          .map(
            (domain) =>
              `${domain.value}:${domain.default_target}:${domain.targets
                .map((target) => target.value)
                .join(',')}`,
          )
          .join('|'),
      ].join('::'),
    [effectiveTaxonomy, initial, mode, open],
  );
  const [formState, setFormState] = useState<{ key: string; value: EntityTypeForm }>(() => ({
    key: formKey,
    value: defaultForm,
  }));
  const form = formState.key === formKey ? formState.value : defaultForm;

  const nameInputId = useId();
  const regexInputId = useId();
  const descriptionInputId = useId();

  const setForm = useCallback(
    (next: SetStateAction<EntityTypeForm>) => {
      setFormState((current) => {
        const base = current.key === formKey ? current.value : defaultForm;
        const value = typeof next === 'function' ? next(base) : next;
        return { key: formKey, value };
      });
    },
    [defaultForm, formKey],
  );

  const canSubmit = Boolean(
    form.name.trim() && (form.use_llm || form.regex_pattern.trim()),
  );

  const dialogTitle = mode === 'create' ? t('settings.entityDialog.createTitle') : t('settings.editType');
  const dialogDescription = t('settings.entityDialog.desc');

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{dialogTitle}</DialogTitle>
          <DialogDescription>{dialogDescription}</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4 py-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={nameInputId}>{t('settings.entityDialog.nameLabel')}</Label>
            <Input
              id={nameInputId}
              value={form.name}
              onChange={(event) =>
                setForm((current) => ({ ...current, name: event.target.value }))
              }
              placeholder={t('settings.entityDialog.namePlaceholder')}
              data-testid="entity-type-name"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>{t('settings.entityDialog.kindLabel')}</Label>
            <div className="flex gap-2">
              <Button
                type="button"
                size="sm"
                variant={form.use_llm ? 'default' : 'outline'}
                onClick={() => setForm((current) => ({ ...current, use_llm: true, regex_pattern: '' }))}
                data-testid="entity-type-kind-semantic"
              >
                {t('settings.entityDialog.kindSemantic')}
              </Button>
              <Button
                type="button"
                size="sm"
                variant={!form.use_llm ? 'default' : 'outline'}
                onClick={() => setForm((current) => ({ ...current, use_llm: false }))}
                data-testid="entity-type-kind-regex"
              >
                {t('settings.entityDialog.kindRegex')}
              </Button>
            </div>
          </div>

          {!form.use_llm && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={regexInputId}>{t('settings.entityDialog.regexLabel')}</Label>
              <Input
                id={regexInputId}
                value={form.regex_pattern}
                onChange={(event) =>
                  setForm((current) => ({ ...current, regex_pattern: event.target.value }))
                }
                placeholder={t('settings.entityDialog.regexPlaceholder')}
                data-testid="entity-type-regex"
              />
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <Label htmlFor={descriptionInputId}>{t('settings.entityDialog.descriptionLabel')}</Label>
            <Textarea
              id={descriptionInputId}
              value={form.description}
              onChange={(event) =>
                setForm((current) => ({ ...current, description: event.target.value }))
              }
              rows={4}
              placeholder={t('settings.entityDialog.descriptionPlaceholder')}
              data-testid="entity-type-description"
            />
          </div>

        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            data-testid="entity-type-cancel"
          >
            {t('settings.cancel')}
          </Button>
          <Button
            disabled={!canSubmit || saving}
            onClick={() => onSave(form)}
            data-testid="entity-type-save"
          >
            {saving
              ? t('settings.saving')
              : mode === 'create'
                ? t('settings.create')
                : t('settings.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
