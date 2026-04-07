// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0


import { useState, useCallback, useRef, useEffect } from 'react';
import { t } from '@/i18n';
import { useUndoRedo } from '@/hooks/useUndoRedo';
import { authFetch } from '@/services/api-client';
import { showToast } from '@/components/Toast';
import { localizeErrorMessage } from '@/utils/localizeError';
import { safeJson } from '../utils';
import type { Entity } from '../types';

export function usePlaygroundEntities() {
  const [entities, setEntities] = useState<Entity[]>([]);
  const entityHistory = useUndoRedo<Entity[]>();
  const nerAbortRef = useRef<AbortController | null>(null);

  const applyEntities = useCallback((next: Entity[]) => {
    entityHistory.save(entities);
    setEntities(next);
  }, [entities, entityHistory]);

  const removeEntity = useCallback((id: string) => {
    setEntities(prev => {
      entityHistory.save(prev);
      return prev.filter(e => e.id !== id);
    });
    showToast('已删除', 'info');
  }, [entityHistory]);

  const selectAllEntities = useCallback(() => {
    setEntities(prev => prev.map(e => ({ ...e, selected: true })));
  }, []);

  const deselectAllEntities = useCallback(() => {
    setEntities(prev => prev.map(e => ({ ...e, selected: false })));
  }, []);

  // Abort NER on unmount
  useEffect(() => () => { nerAbortRef.current?.abort(); }, []);

  const handleRerunNerText = useCallback(async (
    fileId: string,
    selectedTypes: string[],
    setIsLoading: (v: boolean) => void,
    setLoadingMessage: (v: string) => void,
  ) => {
    // Abort any in-flight NER request before starting a new one
    nerAbortRef.current?.abort();
    const controller = new AbortController();
    nerAbortRef.current = controller;

    setIsLoading(true);
    setLoadingMessage('重新识别中（正则+AI语义识别）...');
    try {
      const nerRes = await authFetch(`/api/v1/files/${fileId}/ner/hybrid`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entity_type_ids: selectedTypes }),
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      if (!nerRes.ok) throw new Error(t('error.reRecognizeFailed'));
      const nerData = await safeJson(nerRes);
      if (controller.signal.aborted) return;
      const entitiesWithSource = (nerData.entities || []).map(
        (e: Record<string, unknown>, idx: number) => ({
          ...e,
          id: e.id || `entity_${idx}`,
          selected: true,
          source: e.source || 'llm',
        }),
      );
      setEntities(entitiesWithSource);
      entityHistory.reset();
      showToast(`重新识别完成：${entitiesWithSource.length} 处`, 'success');
    } catch (err) {
      if (controller.signal.aborted) return;
      showToast(localizeErrorMessage(err, 'playground.recognizeFailed'), 'error');
    } finally {
      if (!controller.signal.aborted) {
        setIsLoading(false);
        setLoadingMessage('');
      }
    }
  }, [entityHistory]);

  return {
    entities,
    setEntities,
    entityHistory,
    applyEntities,
    removeEntity,
    selectAllEntities,
    deselectAllEntities,
    handleRerunNerText,
  };
}
