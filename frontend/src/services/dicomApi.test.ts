import { describe, expect, it } from 'vitest';
import { __dicomContractAdapters } from './dicomApi';

describe('DICOM API contract adapters', () => {
  it('preserves relative paths for folder uploads and DICOMDIR references', () => {
    const file = {
      name: '6154',
      webkitRelativePath: 'DICOMDIR_SET/77654033/CR1/6154',
    } as File;
    expect(__dicomContractAdapters.dicomUploadName(file)).toBe('DICOMDIR_SET/77654033/CR1/6154');
    expect(
      __dicomContractAdapters.dicomUploadName({
        name: 'single.dcm',
        webkitRelativePath: '',
      } as File),
    ).toBe('single.dcm');
  });

  it('maps backend hierarchy identifiers to the workbench model', () => {
    const study = __dicomContractAdapters.normalizeStudy({
      id: 'study-1',
      subject_key: 'SUBJ-001',
      modalities: ['CT'],
      status: 'review_required',
      preflight_version: 2,
      risk_count: 1,
      series: [
        {
          id: 'series-1',
          modality: 'CT',
          instance_count: 1,
          instances: [{ id: 'instance-1', frame_count: 2, previewable: true }],
        },
      ],
    });

    expect(study.study_id).toBe('study-1');
    expect(study.patient_pseudonym).toBe('SUBJ-001');
    expect(study.preflight_version).toBe(2);
    expect(study.risk_summary.high).toBe(1);
    expect(study.series?.[0].series_id).toBe('series-1');
    expect(study.series?.[0].instances?.[0].instance_id).toBe('instance-1');
  });

  it('normalizes risk summaries and instance metadata', () => {
    const summary = __dicomContractAdapters.normalizeRiskSummary({
      open: 3,
      blocking: 2,
      by_severity: { critical: 1, high: 1, medium: 1, low: 0 },
    });
    expect(summary).toEqual({
      critical: 1,
      high: 1,
      medium: 1,
      low: 0,
      unresolved: 3,
      blocking: 2,
    });

    const entries = __dicomContractAdapters.normalizeMetadata({
      instances: [
        {
          id: 'instance-1',
          metadata: {
            '0010,0010': { keyword: 'PatientName', vr: 'PN', value: 'REDACTED' },
          },
        },
      ],
    });
    expect(entries[0]).toMatchObject({
      tag: '0010,0010',
      keyword: 'PatientName',
      original_value: 'REDACTED',
      source: 'instance:instance-1',
    });
  });

  it('normalizes the paginated top-level metadata contract', () => {
    const entries = __dicomContractAdapters.normalizeMetadata({
      entries: [
        {
          tag: '0010,0010',
          keyword: 'PatientName',
          vr: 'PN',
          original_value: 'SYNTHETIC^PATIENT',
          output_value: '',
          action: 'Z',
          risk_level: 'high',
          source: 'dataset',
        },
      ],
      total: 1,
      offset: 0,
      limit: 200,
    });

    expect(entries).toEqual([
      expect.objectContaining({
        tag: '0010,0010',
        keyword: 'PatientName',
        original_value: 'SYNTHETIC^PATIENT',
        output_value: undefined,
        action: 'Z',
        risk_level: 'high',
        source: 'dataset',
      }),
    ]);
  });

  it('normalizes job ids and structured error messages', () => {
    const job = __dicomContractAdapters.normalizeJob({
      id: 'job-1',
      study_id: 'study-1',
      status: 'failed',
      error: { error_code: 'DICOM_FAILED', message: 'decode failed' },
    });
    expect(job.job_id).toBe('job-1');
    expect(job.error).toBe('decode failed');
  });

  it('preserves every profile advertised by the capabilities contract', () => {
    const values = [
      'basic',
      'research_strict',
      'longitudinal',
      'longitudinal_research',
      'internal_pseudonymized',
      'ai_training',
    ];
    for (const value of values) {
      const study = __dicomContractAdapters.normalizeStudy({
        id: value,
        profile: value,
        modalities: [],
      });
      expect(study.profile).toBe(value);
    }
  });
});
