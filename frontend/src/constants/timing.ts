// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

/**
 * Centralized timing constants used across the frontend.
 *
 * Keeping timeouts, intervals, and debounce values in one place makes them
 * easy to tune and prevents the same magic number from drifting between files.
 */

// ── Polling intervals ────────────────────────────────────────────────────────

/** Interval for polling job-detail status while a job is actively processing. */
export const JOB_DETAIL_POLL_ACTIVE_MS = 5_000;

/** Interval for polling job-detail status when a job is in a waiting state. */
export const JOB_DETAIL_POLL_IDLE_MS = 2_000;

/** Interval for polling the jobs list page. */
export const JOBS_LIST_POLL_MS = 10_000;

/** Interval for polling batch file analysis progress. */
export const BATCH_FILE_POLL_MS = 1_000;

/** Interval for checking if a popout window has been closed. */
export const POPOUT_CLOSE_CHECK_MS = 1_000;

// ── Debounce / delay ─────────────────────────────────────────────────────────

/** Delay before showing the suspense spinner so quick loads feel instant. */
export const SUSPENSE_SPINNER_DELAY_MS = 150;

/** Delay before prefetching routes when requestIdleCallback is unavailable. */
export const ROUTE_PREFETCH_DELAY_MS = 2_000;

/** Minimum visible time for a "testing" spinner to avoid flash of state. */
export const TEST_BUTTON_MIN_SPIN_MS = 300;

/** Debounce delay for batch review auto-save drafts. */
export const REVIEW_AUTOSAVE_DEBOUNCE_MS = 900;

/** Debounce delay for preview-map / image-preview re-computation. */
export const PREVIEW_DEBOUNCE_MS = 300;

/** Duration of the highlight ring shown when scrolling to an entity. */
export const ENTITY_HIGHLIGHT_DURATION_MS = 1_500;

/** Duration of the highlight ring shown when jumping between result marks. */
export const RESULT_MARK_HIGHLIGHT_MS = 2_500;

/** Minimum visible time for the "submitting" state in batch step 3. */
export const SUBMIT_BUTTON_MIN_SPIN_MS = 2_000;

// ── React-Query defaults ─────────────────────────────────────────────────────

/** Default staleTime for queries (30 s). */
export const QUERY_STALE_TIME_MS = 30_000;

/** Default retry count for failed queries. */
export const QUERY_RETRY_COUNT = 1;
