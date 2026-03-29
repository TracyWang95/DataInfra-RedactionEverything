/**
 * 企业级导航：Job 聚合状态 -> 唯一主 CTA
 */
export type JobTypeForNav = 'text_batch' | 'image_batch' | 'smart_batch';

export type PrimaryNavAction =
  | { kind: 'link'; label: string; to: string }
  | { kind: 'none'; reason?: string };

function batchBasePath(jobType: JobTypeForNav): string {
  if (jobType === 'image_batch') return '/batch/image';
  if (jobType === 'smart_batch') return '/batch/smart';
  return '/batch/text';
}

export function buildBatchWorkbenchUrl(
  jobId: string,
  jobType: JobTypeForNav,
  step: 1 | 2 | 3 | 4 | 5,
  itemId?: string
): string {
  const base = batchBasePath(jobType);
  const sp = new URLSearchParams();
  sp.set('jobId', jobId);
  sp.set('step', String(step));
  if (itemId) sp.set('itemId', itemId);
  return `${base}?${sp.toString()}`;
}


export type JobNavHints = {
  item_count: number;
  first_awaiting_review_item_id?: string | null;
  /** 列表接口从 config 抽出，避免嵌套字段被前端忽略或类型不一致 */
  wizard_furthest_step?: number | null;
  /** 与后端 infer_batch_step1_configured 一致：已选识别项则视为可进上传步 */
  batch_step1_configured?: boolean | null;
};

/** config / nav_hints 里可能是 number、字符串或 JSON 数字 */
export function parseWizardFurthestFromUnknown(raw: unknown): 1 | 2 | 3 | 4 | 5 | null {
  if (raw == null || typeof raw === 'boolean') return null;
  let n: number;
  if (typeof raw === 'number' && Number.isFinite(raw)) n = Math.trunc(raw);
  else if (typeof raw === 'string') {
    const t = raw.trim();
    if (!t) return null;
    const p = Number.parseInt(t, 10);
    if (!Number.isFinite(p)) return null;
    n = p;
  } else return null;
  if (n < 1 || n > 5) return null;
  return n as 1 | 2 | 3 | 4 | 5;
}

function resolvedWizardFurthest(
  jobConfig: Record<string, unknown> | null | undefined,
  navHints: JobNavHints | null | undefined
): 1 | 2 | 3 | 4 | 5 | null {
  const fromCfg =
    jobConfig && typeof jobConfig === 'object'
      ? parseWizardFurthestFromUnknown(jobConfig.wizard_furthest_step)
      : null;
  const fromNav = parseWizardFurthestFromUnknown(navHints?.wizard_furthest_step);
  const parts = [fromCfg, fromNav].filter((x): x is 1 | 2 | 3 | 4 | 5 => x != null);
  if (parts.length === 0) return null;
  return Math.max(...parts) as 1 | 2 | 3 | 4 | 5;
}

/** 从已持久化的批量配置推断：用户至少选过识别项，应能进入步骤 2（与后端 infer_batch_step1_configured 对齐） */
export function inferWizardFloorFromBatchConfig(
  jobConfig: Record<string, unknown> | null | undefined,
  jobType: JobTypeForNav
): 2 | null {
  if (!jobConfig || typeof jobConfig !== 'object') return null;
  if (jobType === 'text_batch') {
    const ids = jobConfig.entity_type_ids;
    return Array.isArray(ids) && ids.length > 0 ? 2 : null;
  }
  if (jobType === 'smart_batch') {
    const ids = jobConfig.entity_type_ids;
    const ocr = jobConfig.ocr_has_types;
    const hi = jobConfig.has_image_types;
    if (Array.isArray(ids) && ids.length > 0) return 2;
    if (Array.isArray(ocr) && ocr.length > 0) return 2;
    if (Array.isArray(hi) && hi.length > 0) return 2;
    return null;
  }
  const ocr = jobConfig.ocr_has_types;
  const hi = jobConfig.has_image_types;
  if (Array.isArray(ocr) && ocr.length > 0) return 2;
  if (Array.isArray(hi) && hi.length > 0) return 2;
  return null;
}

/**
 * 显式 wizard_furthest_step 与「配置已就绪」推断取大，供任务中心 CTA 与 Batch 深链恢复一致。
 */
export function effectiveWizardFurthestStep(input: {
  jobConfig?: Record<string, unknown> | null;
  navHints?: JobNavHints | null;
  jobType: JobTypeForNav;
}): 1 | 2 | 3 | 4 | 5 | null {
  const explicit = resolvedWizardFurthest(input.jobConfig, input.navHints ?? undefined);
  const fromCfg = inferWizardFloorFromBatchConfig(input.jobConfig, input.jobType);
  const fromHint = input.navHints?.batch_step1_configured ? (2 as const) : null;
  const parts = [explicit, fromCfg, fromHint].filter((x): x is 1 | 2 | 3 | 4 | 5 => x != null);
  if (parts.length === 0) return null;
  return Math.max(...parts) as 1 | 2 | 3 | 4 | 5;
}

/** 草稿 0 项时：若主链仍指向 step=1，但 config/nav_hints 任一能解析出 wizard≥2，则纠偏 */
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
  if (status !== 'draft') return nav;
  if (itemCount !== 0) return nav;
  const wf = effectiveWizardFurthestStep({ jobConfig, navHints, jobType });
  if (wf === null || wf < 2) return nav;
  if (!nav.to.includes('step=1')) return nav;
  const step = Math.min(5, Math.max(2, wf)) as 2 | 3 | 4 | 5;
  const label =
    step === 2 ? '继续上传' : step === 3 ? '继续识别' : step === 4 ? '继续审阅' : '继续导出';
  return { kind: 'link', label, to: buildBatchWorkbenchUrl(jobId, jobType, step) };
}

/** 供单测：模拟「先得到错误链再纠偏」的场景 */
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
  /** 草稿里可含 wizard_furthest_step，用于「继续配置/上传」回到上次步骤 */
  jobConfig?: Record<string, unknown> | null;
}): PrimaryNavAction {
  const { jobId, status, jobType, items, currentPage, navHints, jobConfig } = input;
  const itemCount = navHints?.item_count ?? items.length;
  const firstAwaiting =
    items.find(i => i.status === 'awaiting_review')?.id ??
    navHints?.first_awaiting_review_item_id ??
    undefined;

  let action: PrimaryNavAction;
  switch (status) {
    case 'draft': {
      const wf = effectiveWizardFurthestStep({ jobConfig, navHints, jobType });
      if (itemCount === 0) {
        const step: 1 | 2 = wf !== null && wf >= 2 ? 2 : 1;
        const label = step === 1 ? '继续配置' : '继续上传';
        action = { kind: 'link', label, to: buildBatchWorkbenchUrl(jobId, jobType, step) };
        break;
      }
      const stepRaw = wf !== null && wf >= 2 ? wf : 2;
      const step = Math.min(5, Math.max(2, stepRaw)) as 2 | 3 | 4 | 5;
      const label =
        step === 2 ? '继续上传' : step === 3 ? '继续识别' : step === 4 ? '继续审阅' : '继续导出';
      action = { kind: 'link', label, to: buildBatchWorkbenchUrl(jobId, jobType, step) };
      break;
    }
    case 'queued':
    case 'running':
    case 'redacting':
      if (currentPage === 'job_detail') {
        action = { kind: 'link', label: '打开工作台', to: buildBatchWorkbenchUrl(jobId, jobType, 3) };
      } else {
        action = { kind: 'link', label: '查看任务进度', to: `/jobs/${encodeURIComponent(jobId)}` };
      }
      break;
    case 'awaiting_review':
      action = {
        kind: 'link',
        label: '去审核',
        to: buildBatchWorkbenchUrl(jobId, jobType, 4, firstAwaiting),
      };
      break;
    case 'completed':
      action = { kind: 'link', label: '查看结果与下载', to: `/history?source=batch&jobId=${encodeURIComponent(jobId)}` };
      break;
    case 'failed':
      if (currentPage === 'job_detail') {
        action = { kind: 'none', reason: '任务已失败' };
      } else {
        action = { kind: 'link', label: '查看失败详情', to: `/jobs/${encodeURIComponent(jobId)}` };
      }
      break;
    case 'cancelled':
      if (currentPage === 'job_detail') {
        action = { kind: 'none', reason: '任务已取消，不可编辑' };
      } else {
        action = { kind: 'link', label: '查看详情', to: `/jobs/${encodeURIComponent(jobId)}` };
      }
      break;
    default:
      if (currentPage === 'job_detail') {
        action = { kind: 'none' };
      } else {
        action = { kind: 'link', label: '查看详情', to: `/jobs/${encodeURIComponent(jobId)}` };
      }
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
