// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type {
  StructuredColumnProfile,
  StructuredConnectionPayload,
  StructuredExportFormat,
  StructuredPolicyAction,
} from '@/services/structuredApi';
import { t } from '@/i18n';

// Built lazily so the labels follow the active locale.
export function getActionOptions(): Array<{ value: StructuredPolicyAction; label: string }> {
  return [
    { value: 'keep', label: t('structured.action.keep') },
    { value: 'mask', label: t('structured.action.mask') },
    { value: 'hash', label: t('structured.action.hash') },
    { value: 'tokenize', label: t('structured.action.tokenize') },
    { value: 'generalize', label: t('structured.action.generalize') },
    { value: 'bucket', label: t('structured.action.bucket') },
    { value: 'suppress', label: t('structured.action.suppress') },
    { value: 'custom', label: t('structured.action.custom') },
  ];
}

export const exportOptions: Array<{ value: StructuredExportFormat; label: string }> = [
  { value: 'csv', label: 'CSV' },
  { value: 'xlsx', label: 'XLSX' },
  { value: 'sqlite', label: 'SQLite' },
  { value: 'sql', label: 'SQL' },
];

export const FIELD_POLICY_PAGE_SIZE = 5;
export const DATABASE_DISCOVERY_PAGE_SIZE = 5;
export const EMPTY_STRUCTURED_COLUMNS: StructuredColumnProfile[] = [];

export const emptyConnection: StructuredConnectionPayload = {
  engine: 'sqlite',
  display_name: '',
  host: '127.0.0.1',
  port: 3306,
  database: '',
  username: '',
  password: '',
  sqlite_path: '',
};
