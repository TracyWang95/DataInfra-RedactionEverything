// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useMemo, useState, type SetStateAction } from 'react';
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
import { Checkbox } from '@/components/ui/checkbox';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

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
  taxonomyLocked?: boolean;
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
    regex_pattern: '',
    use_llm: true,
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
  taxonomyLocked = false,
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
  const rawForm = formState.key === formKey ? formState.value : defaultForm;

  const dataDomainOptions = useMemo(
    () => effectiveTaxonomy.map(({ value, label }) => ({ value, label })),
    [effectiveTaxonomy],
  );

  const domainByValue = useMemo(
    () => new Map(effectiveTaxonomy.map((domain) => [domain.value, domain])),
    [effectiveTaxonomy],
  );

  const genericTargetOptions = useMemo(() => {
    return domainByValue.get(rawForm.data_domain)?.targets ?? effectiveTaxonomy[0].targets;
  }, [domainByValue, effectiveTaxonomy, rawForm.data_domain]);

  const form = useMemo(() => {
    if (genericTargetOptions.some((option) => option.value === rawForm.generic_target)) {
      return rawForm;
    }
    const nextGenericTarget =
      domainByValue.get(rawForm.data_domain)?.default_target ?? genericTargetOptions[0]?.value;
    return nextGenericTarget ? { ...rawForm, generic_target: nextGenericTarget } : rawForm;
  }, [domainByValue, genericTargetOptions, rawForm]);

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
    form.name.trim() && form.data_domain.trim() && form.generic_target.trim(),
  );

  const dialogTitle = mode === 'create' ? '新建自定义识别项' : t('settings.editType');
  const dialogDescription =
    '自定义识别项只使用模型语义识别。L1/L2 用于分类、默认归并和指代消歧，不会作为 NER 标签发送给模型。';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{dialogTitle}</DialogTitle>
          <DialogDescription>{dialogDescription}</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4 py-2">
          <div className="flex flex-col gap-1.5">
            <Label>识别项名称 *</Label>
            <Input
              value={form.name}
              onChange={(event) =>
                setForm((current) => ({ ...current, name: event.target.value }))
              }
              placeholder="例如：文书编号、出生日期、供应商编号"
              data-testid="entity-type-name"
            />
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label>一级分类 *</Label>
              <Select
                value={form.data_domain}
                disabled={taxonomyLocked}
                onValueChange={(value) =>
                  setForm((current) => ({
                    ...current,
                    data_domain: value,
                    generic_target:
                      domainByValue.get(value)?.default_target ??
                      domainByValue.get(value)?.targets[0]?.value ??
                      current.generic_target,
                  }))
                }
              >
                <SelectTrigger data-testid="entity-type-data-domain">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {dataDomainOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex flex-col gap-1.5">
              <Label>二级分类 *</Label>
              <Select
                value={form.generic_target}
                disabled={taxonomyLocked}
                onValueChange={(value) =>
                  setForm((current) => ({ ...current, generic_target: value }))
                }
              >
                <SelectTrigger data-testid="entity-type-generic-target">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {genericTargetOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>描述</Label>
            <Textarea
              value={form.description}
              onChange={(event) =>
                setForm((current) => ({ ...current, description: event.target.value }))
              }
              rows={4}
              placeholder="可选。用于帮助模型理解这个识别项的语义边界。"
              data-testid="entity-type-description"
            />
          </div>

          <label className="flex items-start gap-2 rounded-lg border border-border/70 bg-muted/20 px-3 py-2.5 text-xs">
            <Checkbox
              className="mt-0.5"
              checked={form.coref_enabled}
              disabled={taxonomyLocked}
              onCheckedChange={(next) =>
                setForm((current) => ({ ...current, coref_enabled: Boolean(next) }))
              }
              data-testid="entity-type-coref-enabled"
            />
            <span className="leading-5">
              <span className="block font-medium text-foreground">指代消歧补充</span>
              <span className="block text-muted-foreground">
                默认开启。系统会根据一级/二级分类推导归并范围，例如人员、组织、编号、账户、地址或日期。
              </span>
            </span>
          </label>
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
            onClick={() =>
              onSave({
                ...form,
                regex_pattern: '',
                use_llm: true,
                tag_template: '',
              })
            }
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
