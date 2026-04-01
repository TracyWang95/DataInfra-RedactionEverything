/**
 * 拆分后的 Zustand 状态管理
 *
 * 将原 monolithic store 拆为 4 个领域 store：
 * - useFileStore:       文件信息、内容、页面
 * - useEntityStore:     实体列表、边界框、选择操作
 * - useRedactionStore:  脱敏配置、结果、对比数据
 * - useUIStore:         加载状态、错误、阶段
 *
 * 同时保留原有的 selector hooks 以保持向后兼容。
 */

import { create } from 'zustand';
import { useShallow } from 'zustand/react/shallow';
import {
  EntityType,
  ReplacementMode,
} from '../types';
import type {
  FileInfo,
  Entity,
  BoundingBox,
  RedactionConfig,
  RedactionResult,
  CompareData,
  AppStage,
} from '../types';

// ============================================================
// 1. File Store
// ============================================================
interface FileState {
  fileInfo: FileInfo | null;
  setFileInfo: (info: FileInfo | null) => void;
  content: string;
  pages: string[];
  setContent: (content: string, pages: string[]) => void;
  resetFile: () => void;
}

export const useFileStore = create<FileState>((set) => ({
  fileInfo: null,
  setFileInfo: (fileInfo) => set({ fileInfo }),
  content: '',
  pages: [],
  setContent: (content, pages) => set({ content, pages }),
  resetFile: () => set({ fileInfo: null, content: '', pages: [] }),
}));

// ============================================================
// 2. Entity Store
// ============================================================
interface EntityState {
  entities: Entity[];
  setEntities: (entities: Entity[]) => void;
  updateEntity: (id: string, updates: Partial<Entity>) => void;
  toggleEntitySelection: (id: string) => void;
  selectAllEntities: () => void;
  deselectAllEntities: () => void;
  addManualEntity: (entity: Omit<Entity, 'id'>) => void;
  boundingBoxes: BoundingBox[];
  setBoundingBoxes: (boxes: BoundingBox[]) => void;
  toggleBoxSelection: (id: string) => void;
  resetEntities: () => void;
}

export const useEntityStore = create<EntityState>((set) => ({
  entities: [],
  setEntities: (entities) => set({ entities }),
  updateEntity: (id, updates) =>
    set((state) => ({
      entities: state.entities.map((e) =>
        e.id === id ? { ...e, ...updates } : e
      ),
    })),
  toggleEntitySelection: (id) =>
    set((state) => ({
      entities: state.entities.map((e) =>
        e.id === id ? { ...e, selected: !e.selected } : e
      ),
    })),
  selectAllEntities: () =>
    set((state) => ({
      entities: state.entities.map((e) => ({ ...e, selected: true })),
    })),
  deselectAllEntities: () =>
    set((state) => ({
      entities: state.entities.map((e) => ({ ...e, selected: false })),
    })),
  addManualEntity: (entity) =>
    set((state) => ({
      entities: [
        ...state.entities,
        { ...entity, id: `manual_${Date.now()}` },
      ],
    })),
  boundingBoxes: [],
  setBoundingBoxes: (boundingBoxes) => set({ boundingBoxes }),
  toggleBoxSelection: (id) =>
    set((state) => ({
      boundingBoxes: state.boundingBoxes.map((b) =>
        b.id === id ? { ...b, selected: !b.selected } : b
      ),
    })),
  resetEntities: () => set({ entities: [], boundingBoxes: [] }),
}));

// ============================================================
// 3. Redaction Config & Result Store
// ============================================================
const initialConfig: RedactionConfig = {
  replacement_mode: ReplacementMode.SMART,
  entity_types: [
    EntityType.PERSON,
    EntityType.PHONE,
    EntityType.ID_CARD,
    EntityType.BANK_CARD,
    EntityType.CASE_NUMBER,
  ],
  custom_replacements: {},
};

interface RedactionState {
  config: RedactionConfig;
  setConfig: (config: Partial<RedactionConfig>) => void;
  toggleEntityType: (type: EntityType) => void;
  setReplacementMode: (mode: ReplacementMode) => void;
  redactionResult: RedactionResult | null;
  setRedactionResult: (result: RedactionResult | null) => void;
  compareData: CompareData | null;
  setCompareData: (data: CompareData | null) => void;
  resetRedaction: () => void;
}

export const useRedactionConfigStore = create<RedactionState>((set) => ({
  config: initialConfig,
  setConfig: (config) =>
    set((state) => ({ config: { ...state.config, ...config } })),
  toggleEntityType: (type) =>
    set((state) => {
      const types = state.config.entity_types;
      const newTypes = types.includes(type)
        ? types.filter((t) => t !== type)
        : [...types, type];
      return { config: { ...state.config, entity_types: newTypes } };
    }),
  setReplacementMode: (mode) =>
    set((state) => ({ config: { ...state.config, replacement_mode: mode } })),
  redactionResult: null,
  setRedactionResult: (redactionResult) => set({ redactionResult }),
  compareData: null,
  setCompareData: (compareData) => set({ compareData }),
  resetRedaction: () =>
    set({ config: initialConfig, redactionResult: null, compareData: null }),
}));

// ============================================================
// 4. UI Store
// ============================================================
interface UIState {
  stage: AppStage;
  setStage: (stage: AppStage) => void;
  isLoading: boolean;
  setIsLoading: (loading: boolean) => void;
  loadingMessage: string;
  setLoadingMessage: (message: string) => void;
  error: string | null;
  setError: (error: string | null) => void;
  resetUI: () => void;
}

export const useUIStore = create<UIState>((set) => ({
  stage: 'upload',
  setStage: (stage) => set({ stage }),
  isLoading: false,
  setIsLoading: (isLoading) => set({ isLoading }),
  loadingMessage: '',
  setLoadingMessage: (loadingMessage) => set({ loadingMessage }),
  error: null,
  setError: (error) => set({ error }),
  resetUI: () =>
    set({ stage: 'upload', isLoading: false, loadingMessage: '', error: null }),
}));

// ============================================================
// 兼容层：保留原有的 useRedactionStore 接口
// ============================================================

/**
 * Reset all sub-stores. Can be called outside of React components.
 */
export function resetAllStores() {
  useFileStore.getState().resetFile();
  useEntityStore.getState().resetEntities();
  useRedactionConfigStore.getState().resetRedaction();
  useUIStore.getState().resetUI();
}

/**
 * React hook that returns a reset callback (composes sub-store resets).
 */
export const useResetAllStores = () => {
  const resetFile = useFileStore((s) => s.resetFile);
  const resetEntities = useEntityStore((s) => s.resetEntities);
  const resetRedaction = useRedactionConfigStore((s) => s.resetRedaction);
  const resetUI = useUIStore((s) => s.resetUI);
  return () => {
    resetFile();
    resetEntities();
    resetRedaction();
    resetUI();
  };
};

/**
 * Legacy compatibility facade -- delegates entirely to sub-stores.
 * No local state duplication. Prefer using sub-stores directly.
 */
export function useRedactionStore() {
  const file = useFileStore();
  const entity = useEntityStore();
  const redaction = useRedactionConfigStore();
  const ui = useUIStore();

  return {
    ...file,
    ...entity,
    ...redaction,
    ...ui,
    reset: () => {
      file.resetFile();
      entity.resetEntities();
      redaction.resetRedaction();
      ui.resetUI();
    },
  };
}

// ============================================================
// Selector Hooks（保持原有 API 不变）
// ============================================================
export const useSelectedEntities = () => {
  return useEntityStore((state) => state.entities.filter((e) => e.selected));
};

export const useEntitiesByType = () => {
  return useEntityStore(
    useShallow((state) => {
      const grouped: Record<string, Entity[]> = {};
      state.entities.forEach((entity) => {
        if (!grouped[entity.type]) grouped[entity.type] = [];
        grouped[entity.type].push(entity);
      });
      return grouped;
    })
  );
};

export const useEntityStats = () => {
  return useEntityStore((state) => {
    const total = state.entities.length;
    const selected = state.entities.filter((e) => e.selected).length;
    const byType: Record<string, number> = {};
    state.entities.forEach((entity) => {
      byType[entity.type] = (byType[entity.type] || 0) + 1;
    });
    return { total, selected, byType };
  });
};

// Fine-grained selector hooks
export const useFileInfo = () => useFileStore((s) => s.fileInfo);
export const useSetFileInfo = () => useFileStore((s) => s.setFileInfo);
export const useStage = () => useUIStore((s) => s.stage);
export const useSetStage = () => useUIStore((s) => s.setStage);
export const useEntities = () => useEntityStore((s) => s.entities);
export const useSetEntities = () => useEntityStore((s) => s.setEntities);
export const useBoundingBoxes = () => useEntityStore((s) => s.boundingBoxes);
export const useSetBoundingBoxes = () => useEntityStore((s) => s.setBoundingBoxes);
export const useRedactionConfig = () => useRedactionConfigStore((s) => s.config);
export const useSetConfig = () => useRedactionConfigStore((s) => s.setConfig);
export const useRedactionResult = () => useRedactionConfigStore((s) => s.redactionResult);
export const useCompareData = () => useRedactionConfigStore((s) => s.compareData);
export const useIsLoading = () => useUIStore((s) => s.isLoading);
export const useSetIsLoading = () => useUIStore((s) => s.setIsLoading);
export const useLoadingMessage = () => useUIStore((s) => s.loadingMessage);
export const useAppError = () => useUIStore((s) => s.error);
export const useResetStore = () => {
  const reset = useResetAllStores();
  return reset;
};
