// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type {
  StructuredColumnPolicy,
  StructuredColumnProfile,
  StructuredPolicyAction,
} from '@/services/structuredApi';
import { displayValue } from './dataset-utils';

export interface FieldReviewProgress {
  reviewedPages: number;
  totalPages: number;
  currentPage: number;
  currentPageReviewed: boolean;
  allReviewed: boolean;
}

export function orderColumnsForPolicyReview(columns: StructuredColumnProfile[]): StructuredColumnProfile[] {
  const riskWeight: Record<StructuredColumnProfile['risk_level'], number> = {
    critical: 4,
    high: 3,
    medium: 2,
    low: 1,
  };
  return columns
    .map((column, index) => ({ column, index }))
    .sort((left, right) => {
      const leftRisk = riskWeight[left.column.risk_level] ?? 0;
      const rightRisk = riskWeight[right.column.risk_level] ?? 0;
      if (leftRisk !== rightRisk) return rightRisk - leftRisk;

      const leftRedacts = left.column.recommended_policy !== 'keep';
      const rightRedacts = right.column.recommended_policy !== 'keep';
      if (leftRedacts !== rightRedacts) return leftRedacts ? -1 : 1;

      const leftSemantic = (left.column.reasons ?? []).some((reason) => String(reason).includes('semantic'));
      const rightSemantic = (right.column.reasons ?? []).some((reason) => String(reason).includes('semantic'));
      if (leftSemantic !== rightSemantic) return leftSemantic ? -1 : 1;

      if (left.column.confidence !== right.column.confidence) {
        return right.column.confidence - left.column.confidence;
      }
      return left.index - right.index;
    })
    .map(({ column }) => column);
}

export function matchesPolicyColumnQuery(column: StructuredColumnProfile, normalizedQuery: string): boolean {
  if (!normalizedQuery) return true;
  return [
    column.name,
    column.entity_type,
    column.risk_level,
    column.data_type,
    column.recommended_policy,
    ...(column.reasons ?? []),
    ...column.sample_values.map(displayValue),
  ].some((value) => String(value).toLowerCase().includes(normalizedQuery));
}

export function profileToPolicy(column: StructuredColumnProfile): StructuredColumnPolicy {
  return {
    column: column.name,
    action: column.recommended_policy,
    entity_type: column.entity_type,
    enabled: column.recommended_policy !== 'keep',
    params: {},
  };
}

export function isPolicyAdjusted(column: StructuredColumnProfile, current: StructuredColumnPolicy): boolean {
  const recommended = profileToPolicy(column);
  return current.action !== recommended.action || Boolean(current.enabled) !== Boolean(recommended.enabled);
}

export function defaultEnabledPolicyAction(
  column: StructuredColumnProfile,
  current?: StructuredColumnPolicy,
): StructuredPolicyAction {
  if (current?.action && current.action !== 'keep') return current.action;
  if (column.recommended_policy && column.recommended_policy !== 'keep') return column.recommended_policy;
  return 'mask';
}

export function updatePolicy(
  policy: StructuredColumnPolicy[],
  column: StructuredColumnProfile,
  patch: Partial<StructuredColumnPolicy>,
): StructuredColumnPolicy[] {
  const current = policy.find((item) => item.column === column.name) ?? profileToPolicy(column);
  const nextItem = { ...current, ...patch };
  const exists = policy.some((item) => item.column === column.name);
  if (!exists) return [...policy, nextItem];
  return policy.map((item) => (item.column === column.name ? nextItem : item));
}
