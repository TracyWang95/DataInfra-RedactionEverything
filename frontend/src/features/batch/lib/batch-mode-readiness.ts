// Copyright 2026 DataInfra-RedactionEverything Contributors

import type { ServicesHealth } from '@/hooks/use-service-health';
import type { BatchWizardMode } from '@/services/batchPipeline';

type BatchModeReadinessReason = 'checking' | 'backend' | 'text_model' | 'vision_model' | null;

export type BatchModeReadiness = {
  ready: boolean;
  reason: BatchModeReadinessReason;
};

const usableStatuses = new Set(['online', 'busy', 'degraded']);

function isServiceUsable(status: ServicesHealth['services']['has_ner']['status']): boolean {
  return usableStatuses.has(status);
}

export function getBatchModeReadiness(
  mode: BatchWizardMode,
  health: ServicesHealth | null,
  checking = false,
): BatchModeReadiness {
  if (checking) return { ready: false, reason: 'checking' };
  if (!health) return { ready: false, reason: 'backend' };

  const textReady = isServiceUsable(health.services.has_ner.status);
  const visionReady =
    isServiceUsable(health.services.paddle_ocr.status) ||
    isServiceUsable(health.services.visual_features.status);

  if (mode === 'text') {
    return textReady ? { ready: true, reason: null } : { ready: false, reason: 'text_model' };
  }
  if (mode === 'image') {
    return visionReady ? { ready: true, reason: null } : { ready: false, reason: 'vision_model' };
  }
  if (textReady || visionReady) return { ready: true, reason: null };
  return { ready: false, reason: 'text_model' };
}

export function hasAnyBatchModeReady(health: ServicesHealth | null, checking = false): boolean {
  return (
    getBatchModeReadiness('text', health, checking).ready ||
    getBatchModeReadiness('image', health, checking).ready ||
    getBatchModeReadiness('smart', health, checking).ready
  );
}
