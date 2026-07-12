// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';

import { hasSemanticReason } from './policy-utils';

describe('hasSemanticReason', () => {
  it('matches the exact backend semantic reason enums', () => {
    expect(hasSemanticReason(['semantic_model'])).toBe(true);
    expect(hasSemanticReason(['column_name', 'semantic_model_value'])).toBe(true);
  });

  it('does not substring-sniff other reason strings', () => {
    expect(hasSemanticReason(['semantic'])).toBe(false);
    expect(hasSemanticReason(['non_semantic_model_rule'])).toBe(false);
    expect(hasSemanticReason([])).toBe(false);
    expect(hasSemanticReason(undefined)).toBe(false);
  });
});
