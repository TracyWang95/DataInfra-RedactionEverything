// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

export type JobTypeForNav = 'text_batch' | 'image_batch' | 'smart_batch';

export type PrimaryNavAction =
  | { kind: 'link'; label: string; to: string }
  | { kind: 'none'; reason?: string };

type BatchRouteMode = 'text' | 'image' | 'smart';

export type JobNavHints = {
  item_count: number;
  first_awaiting_review_item_id?: string | null;
  wizard_furthest_step?: number | null;
  batch_step1_configured?: boolean | null;
  redacted_count?: number | null;
  awaiting_review_count?: number | null;
};

function resolveBatchRouteMode(
  jobType: JobTypeForNav,
  jobConfig?: Record<string, unknown> | null,
): BatchRouteMode {
  const wizardMode = jobConfig?.batch_wizard_mode;
  if (wizardMode === 'text' || wizardMode === 'image' || wizardMode === 'smart') {
    return wizardMode;
  }
  if (jobType === 'text_batch') return 'text';
  if (jobType === 'image_batch') return 'image';
  return 'smart';
}

function batchBasePath(jobType: JobTypeForNav, jobConfig?: Record<string, unknown> | null): string {
  return `/batch/${resolveBatchRouteMode(jobType, jobConfig)}`;
}

export function buildBatchWorkbenchUrl(
  jobId: string,
  jobType: JobTypeForNav,
  step: 1 | 2 | 3 | 4 | 5,
  itemId?: string,
  jobConfig?: Record<string, unknown> | null,
): string {
  const base = batchBasePath(jobType, jobConfig);
  const sp = new URLSearchParams();
  sp.set('jobId', jobId);
  sp.set('step', String(step));
  if (itemId) sp.set('itemId', itemId);
  return `${base}?${sp.toString()}`;
}

export function parseWizardFurthestFromUnknown(raw: unknown): 1 | 2 | 3 | 4 | 5 | null {
  if (raw == null || typeof raw === 'boolean') return null;
  let step: number;
  if (typeof raw === 'number' && Number.isFinite(raw)) {
    step = Math.trunc(raw);
  } else if (typeof raw === 'string') {
    const text = raw.trim();
    if (!text) return null;
    const parsed = Number.parseInt(text, 10);
    if (!Number.isFinite(parsed)) return null;
    step = parsed;
  } else {
    return null;
  }
  if (step < 1 || step > 5) return null;
  return step as 1 | 2 | 3 | 4 | 5;
}

function resolvedWizardFurthest(
  jobConfig: Record<string, unknown> | null | undefined,
  navHints: JobNavHints | null | undefined,
): 1 | 2 | 3 | 4 | 5 | null {
  const fromConfig =
    jobConfig && typeof jobConfig === 'object'
      ? parseWizardFurthestFromUnknown(jobConfig.wizard_furthest_step)
      : null;
  const fromHints = parseWizardFurthestFromUnknown(navHints?.wizard_furthest_step);
  const candidates = [fromConfig, fromHints].filter((value): value is 1 | 2 | 3 | 4 | 5 => value != null);
  if (!candidates.length) return null;
  return Math.max(...candidates) as 1 | 2 | 3 | 4 | 5;
}

export function inferWizardFloorFromBatchConfig(
  jobConfig: Record<string, unknown> | null | undefined,
  jobType: JobTypeForNav,
): 2 | null {
  if (!jobConfig || typeof jobConfig !== 'object') return null;
  if (jobType === 'text_batch') {
    return Array.isArray(jobConfig.entity_type_ids) && jobConfig.entity_type_ids.length > 0 ? 2 : null;
  }
  if (jobType === 'smart_batch') {
    if (Array.isArray(jobConfig.entity_type_ids) && jobConfig.entity_type_ids.length > 0) return 2;
    if (Array.isArray(jobConfig.ocr_has_types) && jobConfig.ocr_has_types.length > 0) return 2;
    if (Array.isArray(jobConfig.has_image_types) && jobConfig.has_image_types.length > 0) return 2;
    return null;
  }
  if (Array.isArray(jobConfig.ocr_has_types) && jobConfig.ocr_has_types.length > 0) return 2;
  if (Array.isArray(jobConfig.has_image_types) && jobConfig.has_image_types.length > 0) return 2;
  return null;
}

export function effectiveWizardFurthestStep(input: {
  jobConfig?: Record<string, unknown> | null;
  navHints?: JobNavHints | null;
  jobType: JobTypeForNav;
}): 1 | 2 | 3 | 4 | 5 | null {
  const explicitStep = resolvedWizardFurthest(input.jobConfig, input.navHints ?? undefined);
  const inferredStep = inferWizardFloorFromBatchConfig(input.jobConfig, input.jobType);
  const hintedStep = input.navHints?.batch_step1_configured ? (2 as const) : null;
  const candidates = [explicitStep, inferredStep, hintedStep].filter(
    (value): value is 1 | 2 | 3 | 4 | 5 => value != null,
  );
  if (!candidates.length) return null;
  return Math.max(...candidates) as 1 | 2 | 3 | 4 | 5;
}

function buildDraftStepLabel(step: 1 | 2 | 3 | 4 | 5): string {
  if (step === 1) return '继续配置';
  if (step === 2) return '继续上传';
  if (step === 3) return '继续识别';
  if (step === 4) return '继续审阅';
  return '继续导出';
}

function fixDraftEmptyBatchWorkbenchLink(input: {
  jobId: string;
  status: string;
  jobType: JobTypeForNav;
  itemCount: number;
  jobConfig?: Record<string, unknown> | null;
  navHints?: JobNavHints | null;
  nav: PrimaryNavAction;
}): PrimaryNavAction {
  const { jobId, status, jobType, itemCount, jobConfig, navHints, nav } = input;
  if (nav.kind !== 'link') return nav;
  if (status !== 'draft' || itemCount !== 0 || !nav.to.includes('step=1')) return nav;
  const step = effectiveWizardFurthestStep({ jobConfig, navHints, jobType });
  if (step == null || step < 2) return nav;
  const nextStep = Math.min(5, Math.max(2, step)) as 2 | 3 | 4 | 5;
  return {
    kind: 'link',
    label: buildDraftStepLabel(nextStep),
    to: buildBatchWorkbenchUrl(jobId, jobType, nextStep, undefined, jobConfig),
  };
}

export function coerceDraftEmptyBatchPrimaryNav(input: {
  jobId: string;
  status: string;
  jobType: JobTypeForNav;
  itemCount: number;
  jobConfig?: Record<string, unknown> | null;
  navHints?: JobNavHints | null;
  nav: PrimaryNavAction;
}): PrimaryNavAction {
  return fixDraftEmptyBatchWorkbenchLink(input);
}

export function resolveJobPrimaryNavigation(input: {
  jobId: string;
  status: string;
  jobType: JobTypeForNav;
  items: { id: string; status: string }[];
  currentPage?: 'job_detail' | 'other';
  navHints?: JobNavHints | null;
  jobConfig?: Record<string, unknown> | null;
}): PrimaryNavAction {
  const { jobId, status, jobType, items, currentPage, navHints, jobConfig } = input;
  const itemCount = navHints?.item_count ?? items.length;
  const firstAwaiting =
    items.find((item) => item.status === 'awaiting_review')?.id ??
    navHints?.first_awaiting_review_item_id ??
    undefined;

  let action: PrimaryNavAction;
  switch (status) {
    case 'draft': {
      const step = effectiveWizardFurthestStep({ jobConfig, navHints, jobType });
      if (itemCount === 0) {
        const nextStep: 1 | 2 = step != null && step >= 2 ? 2 : 1;
        action = {
          kind: 'link',
          label: buildDraftStepLabel(nextStep),
          to: buildBatchWorkbenchUrl(jobId, jobType, nextStep, undefined, jobConfig),
        };
        break;
      }
      const nextStep = Math.min(5, Math.max(2, step ?? 2)) as 2 | 3 | 4 | 5;
      action = {
        kind: 'link',
        label: buildDraftStepLabel(nextStep),
        to: buildBatchWorkbenchUrl(jobId, jobType, nextStep, undefined, jobConfig),
      };
      break;
    }
    case 'queued':
    case 'processing':
    case 'running':
    case 'redacting':
      action = {
        kind: 'link',
        label: '查看进度',
        to: buildBatchWorkbenchUrl(jobId, jobType, 3, undefined, jobConfig),
      };
      break;
    case 'awaiting_review':
      action = {
        kind: 'link',
        label: '继续审阅',
        to: buildBatchWorkbenchUrl(jobId, jobType, 4, firstAwaiting, jobConfig),
      };
      break;
    case 'completed':
      action = {
        kind: 'link',
        label: '下载脱敏结果',
        to: `/history?source=batch&jobId=${encodeURIComponent(jobId)}`,
      };
      break;
    case 'failed':
      action =
        currentPage === 'job_detail'
          ? { kind: 'none', reason: '任务已失败' }
          : { kind: 'link', label: '查看失败详情', to: `/jobs/${encodeURIComponent(jobId)}` };
      break;
    case 'cancelled':
      action =
        currentPage === 'job_detail'
          ? { kind: 'none', reason: '任务已取消，不可编辑' }
          : { kind: 'link', label: '查看详情', to: `/jobs/${encodeURIComponent(jobId)}` };
      break;
    default:
      action =
        currentPage === 'job_detail'
          ? { kind: 'none' }
          : { kind: 'link', label: '查看详情', to: `/jobs/${encodeURIComponent(jobId)}` };
  }

  return fixDraftEmptyBatchWorkbenchLink({
    jobId,
    status,
    jobType,
    itemCount,
    jobConfig,
    navHints,
    nav: action,
  });
}
