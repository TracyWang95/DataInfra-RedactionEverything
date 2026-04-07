
import { useState, useCallback } from 'react';
import { useUndoRedo } from '@/hooks/useUndoRedo';
import { authFetch } from '@/services/api-client';
import { showToast } from '@/components/Toast';
import { localizeErrorMessage } from '@/utils/localizeError';
import { safeJson } from '../utils';
import type { Entity } from '../types';

export function usePlaygroundEntities() {
  const [entities, setEntities] = useState<Entity[]>([]);
  const entityHistory = useUndoRedo<Entity[]>();

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

  const handleRerunNerText = useCallback(async (
    fileId: string,
    selectedTypes: string[],
    setIsLoading: (v: boolean) => void,
    setLoadingMessage: (v: string) => void,
  ) => {
    setIsLoading(true);
    setLoadingMessage('重新识别中（正则+AI语义识别）...');
    try {
      const nerRes = await authFetch(`/api/v1/files/${fileId}/ner/hybrid`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entity_type_ids: selectedTypes }),
      });
      if (!nerRes.ok) throw new Error('重新识别失败');
      const nerData = await safeJson(nerRes);
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
      showToast(localizeErrorMessage(err, 'playground.recognizeFailed'), 'error');
    } finally {
      setIsLoading(false);
      setLoadingMessage('');
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
