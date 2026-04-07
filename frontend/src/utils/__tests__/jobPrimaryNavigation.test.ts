// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from 'vitest';
import {
  buildBatchWorkbenchUrl,
  parseWizardFurthestFromUnknown,
  inferWizardFloorFromBatchConfig,
  effectiveWizardFurthestStep,
  resolveJobPrimaryNavigation,
} from '../jobPrimaryNavigation';

describe('parseWizardFurthestFromUnknown', () => {
  it('returns null for null/undefined/boolean', () => {
    expect(parseWizardFurthestFromUnknown(null)).toBeNull();
    expect(parseWizardFurthestFromUnknown(undefined)).toBeNull();
    expect(parseWizardFurthestFromUnknown(true)).toBeNull();
  });

  it('parses valid numbers 1-5', () => {
    expect(parseWizardFurthestFromUnknown(1)).toBe(1);
    expect(parseWizardFurthestFromUnknown(3)).toBe(3);
    expect(parseWizardFurthestFromUnknown(5)).toBe(5);
  });

  it('truncates float to integer', () => {
    expect(parseWizardFurthestFromUnknown(2.9)).toBe(2);
  });

  it('rejects out-of-range numbers', () => {
    expect(parseWizardFurthestFromUnknown(0)).toBeNull();
    expect(parseWizardFurthestFromUnknown(6)).toBeNull();
    expect(parseWizardFurthestFromUnknown(-1)).toBeNull();
  });

  it('parses valid string numbers', () => {
    expect(parseWizardFurthestFromUnknown('3')).toBe(3);
    expect(parseWizardFurthestFromUnknown(' 5 ')).toBe(5);
  });

  it('rejects empty or non-numeric strings', () => {
    expect(parseWizardFurthestFromUnknown('')).toBeNull();
    expect(parseWizardFurthestFromUnknown('abc')).toBeNull();
  });

  it('rejects Infinity and NaN', () => {
    expect(parseWizardFurthestFromUnknown(Infinity)).toBeNull();
    expect(parseWizardFurthestFromUnknown(NaN)).toBeNull();
  });
});

describe('buildBatchWorkbenchUrl', () => {
  it('builds URL for text_batch with step and jobId', () => {
    const url = buildBatchWorkbenchUrl('job-1', 'text_batch', 2);
    expect(url).toContain('/batch/text?');
    expect(url).toContain('jobId=job-1');
    expect(url).toContain('step=2');
  });

  it('includes itemId when provided', () => {
    const url = buildBatchWorkbenchUrl('job-1', 'image_batch', 4, 'item-42');
    expect(url).toContain('itemId=item-42');
    expect(url).toContain('/batch/image?');
  });

  it('respects batch_wizard_mode from jobConfig', () => {
    const url = buildBatchWorkbenchUrl('j', 'text_batch', 1, undefined, {
      batch_wizard_mode: 'smart',
    });
    expect(url).toContain('/batch/smart?');
  });

  it('defaults smart_batch to /batch/smart', () => {
    const url = buildBatchWorkbenchUrl('j', 'smart_batch', 1);
    expect(url).toContain('/batch/smart?');
  });
});

describe('inferWizardFloorFromBatchConfig', () => {
  it('returns null for null config', () => {
    expect(inferWizardFloorFromBatchConfig(null, 'text_batch')).toBeNull();
  });

  it('returns 2 for text_batch with entity_type_ids', () => {
    expect(
      inferWizardFloorFromBatchConfig({ entity_type_ids: ['PERSON'] }, 'text_batch'),
    ).toBe(2);
  });

  it('returns null for text_batch with empty entity_type_ids', () => {
    expect(
      inferWizardFloorFromBatchConfig({ entity_type_ids: [] }, 'text_batch'),
    ).toBeNull();
  });

  it('returns 2 for image_batch with ocr_has_types', () => {
    expect(
      inferWizardFloorFromBatchConfig({ ocr_has_types: ['ID'] }, 'image_batch'),
    ).toBe(2);
  });

  it('returns 2 for smart_batch with entity_type_ids', () => {
    expect(
      inferWizardFloorFromBatchConfig({ entity_type_ids: ['ORG'] }, 'smart_batch'),
    ).toBe(2);
  });
});

describe('effectiveWizardFurthestStep', () => {
  it('returns null when no hints or config', () => {
    expect(
      effectiveWizardFurthestStep({ jobType: 'text_batch' }),
    ).toBeNull();
  });

  it('returns the maximum of all candidates', () => {
    expect(
      effectiveWizardFurthestStep({
        jobType: 'text_batch',
        jobConfig: { wizard_furthest_step: 3, entity_type_ids: ['X'] },
        navHints: { item_count: 0, wizard_furthest_step: 2 },
      }),
    ).toBe(3);
  });
});

describe('resolveJobPrimaryNavigation', () => {
  const base = {
    jobId: 'j1',
    jobType: 'text_batch' as const,
    items: [] as { id: string; status: string }[],
  };

  it('returns link to step 1 for empty draft', () => {
    const nav = resolveJobPrimaryNavigation({ ...base, status: 'draft' });
    expect(nav.kind).toBe('link');
    if (nav.kind === 'link') {
      expect(nav.to).toContain('step=1');
    }
  });

  it('returns progress link for processing status', () => {
    const nav = resolveJobPrimaryNavigation({ ...base, status: 'processing' });
    expect(nav.kind).toBe('link');
    if (nav.kind === 'link') {
      expect(nav.to).toContain('step=3');
      expect(nav.label).toBe('查看进度');
    }
  });

  it('returns review link for awaiting_review status', () => {
    const nav = resolveJobPrimaryNavigation({
      ...base,
      status: 'awaiting_review',
      items: [{ id: 'i1', status: 'awaiting_review' }],
    });
    expect(nav.kind).toBe('link');
    if (nav.kind === 'link') {
      expect(nav.to).toContain('step=4');
      expect(nav.to).toContain('itemId=i1');
    }
  });

  it('returns download link for completed status', () => {
    const nav = resolveJobPrimaryNavigation({ ...base, status: 'completed' });
    expect(nav.kind).toBe('link');
    if (nav.kind === 'link') {
      expect(nav.to).toContain('/history');
    }
  });

  it('returns none for failed on job_detail page', () => {
    const nav = resolveJobPrimaryNavigation({
      ...base,
      status: 'failed',
      currentPage: 'job_detail',
    });
    expect(nav.kind).toBe('none');
  });

  it('returns link for failed on other pages', () => {
    const nav = resolveJobPrimaryNavigation({
      ...base,
      status: 'failed',
      currentPage: 'other',
    });
    expect(nav.kind).toBe('link');
  });
});
