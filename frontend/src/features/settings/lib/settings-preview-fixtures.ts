// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type { RecognitionPreset } from '@/services/presetsApi';

export type PreviewEntityType = {
  id: string;
  name: string;
  color: string;
  regex_pattern?: string | null;
  use_llm?: boolean;
  enabled: boolean;
  order?: number;
  description?: string;
};

export type PreviewPipelineType = {
  id: string;
  name: string;
  color: string;
  enabled: boolean;
  order: number;
  description?: string;
};

export type PreviewPipeline = {
  mode: 'ocr_has' | 'has_image';
  name: string;
  description: string;
  enabled: boolean;
  types: PreviewPipelineType[];
};

type Translate = (key: string) => string;

export function buildPreviewEntityTypes(t: Translate): PreviewEntityType[] {
  const baseTypes: PreviewEntityType[] = [
    {
      id: 'person_name',
      name: t('settings.preview.personName'),
      color: '#0f766e',
      regex_pattern: '[\\u4e00-\\u9fa5]{2,4}',
      enabled: true,
      order: 1,
    },
    {
      id: 'id_card',
      name: t('settings.preview.idCard'),
      color: '#0f766e',
      regex_pattern: '\\b\\d{17}[\\dXx]\\b',
      enabled: true,
      order: 2,
    },
    {
      id: 'bank_card',
      name: t('settings.preview.bankCard'),
      color: '#0f766e',
      regex_pattern: '\\b\\d{12,19}\\b',
      enabled: true,
      order: 3,
    },
    {
      id: 'company_name',
      name: t('settings.preview.companyName'),
      color: '#2563eb',
      use_llm: true,
      enabled: true,
      order: 4,
    },
    {
      id: 'project_name',
      name: t('settings.preview.projectName'),
      color: '#2563eb',
      use_llm: true,
      enabled: true,
      order: 5,
    },
    {
      id: 'address',
      name: t('settings.preview.address'),
      color: '#2563eb',
      use_llm: true,
      enabled: true,
      order: 6,
    },
    {
      id: 'phone_number',
      name: t('entity.PHONE'),
      color: '#0f766e',
      regex_pattern: '\\b1[3-9]\\d{9}\\b',
      enabled: true,
      order: 7,
    },
    {
      id: 'email_address',
      name: t('entity.EMAIL'),
      color: '#0f766e',
      regex_pattern: '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}',
      enabled: true,
      order: 8,
    },
    {
      id: 'case_number',
      name: t('entity.CASE_NUMBER'),
      color: '#0f766e',
      regex_pattern: '[（(]?20\\d{2}[）)]?[A-Za-z\\u4e00-\\u9fa5]{1,6}\\d{2,6}号',
      enabled: true,
      order: 9,
    },
    {
      id: 'contract_date',
      name: t('entity.DATE'),
      color: '#2563eb',
      use_llm: true,
      enabled: true,
      order: 10,
    },
    {
      id: 'contract_amount',
      name: t('entity.AMOUNT'),
      color: '#2563eb',
      use_llm: true,
      enabled: true,
      order: 11,
    },
    {
      id: 'organization_name',
      name: t('entity.ORG'),
      color: '#2563eb',
      use_llm: true,
      enabled: true,
      order: 12,
    },
    {
      id: 'passport_number',
      name: t('settings.preview.passportNumber'),
      color: '#0f766e',
      regex_pattern: '[A-Z0-9]{8,17}',
      enabled: true,
      order: 13,
    },
    {
      id: 'vehicle_plate',
      name: t('settings.preview.vehiclePlate'),
      color: '#0f766e',
      regex_pattern: '[\\u4e00-\\u9fa5][A-Z][A-Z0-9]{5,6}',
      enabled: true,
      order: 14,
    },
    {
      id: 'court_name',
      name: t('settings.preview.courtName'),
      color: '#2563eb',
      use_llm: true,
      enabled: true,
      order: 15,
    },
    {
      id: 'department_name',
      name: t('settings.preview.departmentName'),
      color: '#2563eb',
      use_llm: true,
      enabled: true,
      order: 16,
    },
    {
      id: 'credit_code',
      name: t('settings.preview.creditCode'),
      color: '#0f766e',
      regex_pattern: '[0-9A-Z]{18}',
      enabled: true,
      order: 17,
    },
    {
      id: 'social_security',
      name: t('settings.preview.socialSecurity'),
      color: '#0f766e',
      regex_pattern: '\\b\\d{10,18}\\b',
      enabled: true,
      order: 18,
    },
    {
      id: 'beneficiary_name',
      name: t('settings.preview.beneficiaryName'),
      color: '#2563eb',
      use_llm: true,
      enabled: true,
      order: 19,
    },
    {
      id: 'project_location',
      name: t('settings.preview.projectLocation'),
      color: '#2563eb',
      use_llm: true,
      enabled: true,
      order: 20,
    },
  ];

  return Array.from({ length: 100 }, (_, index) => {
    const template = baseTypes[index % baseTypes.length];
    const cycle = Math.floor(index / baseTypes.length);
    const suffix = cycle === 0 ? '' : ` ${String(cycle + 1).padStart(2, '0')}`;

    return {
      ...template,
      id: cycle === 0 ? template.id : `${template.id}_${cycle + 1}`,
      name: `${template.name}${suffix}`,
      order: index + 1,
    };
  });
}

export function buildPreviewPipelines(t: Translate): PreviewPipeline[] {
  const ocrBaseTypes: PreviewPipelineType[] = [
    {
      id: 'seal_text',
      name: t('settings.preview.sealText'),
      color: '#2563eb',
      enabled: true,
      order: 1,
    },
    {
      id: 'handwritten_name',
      name: t('settings.preview.handwrittenName'),
      color: '#2563eb',
      enabled: true,
      order: 2,
    },
    {
      id: 'margin_note',
      name: t('settings.preview.marginNote'),
      color: '#2563eb',
      enabled: true,
      order: 3,
    },
    {
      id: 'receipt_text',
      name: t('settings.preview.receiptText'),
      color: '#2563eb',
      enabled: true,
      order: 4,
    },
    {
      id: 'tabular_text',
      name: t('settings.preview.tabularText'),
      color: '#2563eb',
      enabled: true,
      order: 5,
    },
  ];
  const imageBaseTypes: PreviewPipelineType[] = [
    {
      id: 'signature_region',
      name: t('settings.preview.signatureRegion'),
      color: '#dc2626',
      enabled: true,
      order: 1,
    },
    {
      id: 'portrait_face',
      name: t('settings.preview.portraitFace'),
      color: '#dc2626',
      enabled: true,
      order: 2,
    },
    {
      id: 'stamp_region',
      name: t('settings.preview.stampRegion'),
      color: '#dc2626',
      enabled: true,
      order: 3,
    },
    {
      id: 'watermark_region',
      name: t('settings.preview.watermarkRegion'),
      color: '#dc2626',
      enabled: true,
      order: 4,
    },
    {
      id: 'id_portrait',
      name: t('settings.preview.idPortrait'),
      color: '#dc2626',
      enabled: true,
      order: 5,
    },
    {
      id: 'qr_region',
      name: t('settings.preview.qrRegion'),
      color: '#dc2626',
      enabled: true,
      order: 6,
    },
  ];
  const buildRepeatedTypes = (baseTypes: PreviewPipelineType[], total: number) =>
    Array.from({ length: total }, (_, index) => {
      const template = baseTypes[index % baseTypes.length];
      const cycle = Math.floor(index / baseTypes.length);
      const suffix = cycle === 0 ? '' : ` ${String(cycle + 1).padStart(2, '0')}`;

      return {
        ...template,
        id: cycle === 0 ? template.id : `${template.id}_${cycle + 1}`,
        name: `${template.name}${suffix}`,
        order: index + 1,
      };
    });

  return [
    {
      mode: 'ocr_has',
      name: t('settings.pipelineDisplayName.ocr'),
      description: t('settings.pipelineDescription.ocr'),
      enabled: true,
      types: buildRepeatedTypes(ocrBaseTypes, 24),
    },
    {
      mode: 'has_image',
      name: t('settings.pipelineDisplayName.image'),
      description: t('settings.pipelineDescription.image'),
      enabled: true,
      types: buildRepeatedTypes(imageBaseTypes, 24),
    },
  ];
}

export function buildPreviewPresets(t: Translate): RecognitionPreset[] {
  const now = new Date().toISOString();

  return [
    {
      id: 'preview-contract-text',
      name: t('settings.preview.preset.contract'),
      kind: 'text',
      selectedEntityTypeIds: ['person_name', 'id_card', 'company_name', 'address'],
      ocrHasTypes: [],
      hasImageTypes: [],
      replacementMode: 'structured',
      created_at: now,
      updated_at: now,
    },
    {
      id: 'preview-scan-vision',
      name: t('settings.preview.preset.scan'),
      kind: 'vision',
      selectedEntityTypeIds: [],
      ocrHasTypes: ['seal_text', 'handwritten_name'],
      hasImageTypes: ['signature_region', 'portrait_face', 'stamp_region'],
      replacementMode: 'structured',
      created_at: now,
      updated_at: now,
    },
    {
      id: 'preview-mixed-full',
      name: t('settings.preview.preset.mixed'),
      kind: 'full',
      selectedEntityTypeIds: ['person_name', 'project_name', 'company_name'],
      ocrHasTypes: ['seal_text'],
      hasImageTypes: ['signature_region', 'stamp_region'],
      replacementMode: 'structured',
      created_at: now,
      updated_at: now,
    },
    {
      id: 'preview-litigation-full',
      name: t('settings.preview.preset.litigation'),
      kind: 'full',
      selectedEntityTypeIds: ['person_name', 'case_number', 'company_name', 'address'],
      ocrHasTypes: ['seal_text', 'margin_note'],
      hasImageTypes: ['signature_region', 'watermark_region'],
      replacementMode: 'structured',
      created_at: now,
      updated_at: now,
    },
    {
      id: 'preview-finance-text',
      name: t('settings.preview.preset.finance'),
      kind: 'text',
      selectedEntityTypeIds: ['person_name', 'bank_card', 'contract_amount', 'email_address'],
      ocrHasTypes: [],
      hasImageTypes: [],
      replacementMode: 'structured',
      created_at: now,
      updated_at: now,
    },
  ];
}
