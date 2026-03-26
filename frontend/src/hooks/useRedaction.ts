import { create } from 'zustand';
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

interface RedactionState {
  // 当前阶段
  stage: AppStage;
  setStage: (stage: AppStage) => void;

  // 文件信息
  fileInfo: FileInfo | null;
  setFileInfo: (info: FileInfo | null) => void;

  // 文件内容
  content: string;
  pages: string[];
  setContent: (content: string, pages: string[]) => void;

  // 实体列表
  entities: Entity[];
  setEntities: (entities: Entity[]) => void;
  updateEntity: (id: string, updates: Partial<Entity>) => void;
  toggleEntitySelection: (id: string) => void;
  selectAllEntities: () => void;
  deselectAllEntities: () => void;
  addManualEntity: (entity: Omit<Entity, 'id'>) => void;

  // 图片边界框
  boundingBoxes: BoundingBox[];
  setBoundingBoxes: (boxes: BoundingBox[]) => void;
  toggleBoxSelection: (id: string) => void;

  // 脱敏配置
  config: RedactionConfig;
  setConfig: (config: Partial<RedactionConfig>) => void;
  toggleEntityType: (type: EntityType) => void;
  setReplacementMode: (mode: ReplacementMode) => void;

  // 脱敏结果
  redactionResult: RedactionResult | null;
  setRedactionResult: (result: RedactionResult | null) => void;

  // 对比数据
  compareData: CompareData | null;
  setCompareData: (data: CompareData | null) => void;

  // 加载状态
  isLoading: boolean;
  setIsLoading: (loading: boolean) => void;
  loadingMessage: string;
  setLoadingMessage: (message: string) => void;

  // 错误状态
  error: string | null;
  setError: (error: string | null) => void;

  // 重置状态
  reset: () => void;
}

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

export const useRedactionStore = create<RedactionState>((set) => ({
  // 当前阶段
  stage: 'upload',
  setStage: (stage) => set({ stage }),

  // 文件信息
  fileInfo: null,
  setFileInfo: (fileInfo) => set({ fileInfo }),

  // 文件内容
  content: '',
  pages: [],
  setContent: (content, pages) => set({ content, pages }),

  // 实体列表
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
        {
          ...entity,
          id: `manual_${Date.now()}`,
        },
      ],
    })),

  // 图片边界框
  boundingBoxes: [],
  setBoundingBoxes: (boundingBoxes) => set({ boundingBoxes }),
  toggleBoxSelection: (id) =>
    set((state) => ({
      boundingBoxes: state.boundingBoxes.map((b) =>
        b.id === id ? { ...b, selected: !b.selected } : b
      ),
    })),

  // 脱敏配置
  config: initialConfig,
  setConfig: (config) =>
    set((state) => ({
      config: { ...state.config, ...config },
    })),
  toggleEntityType: (type) =>
    set((state) => {
      const types = state.config.entity_types;
      const newTypes = types.includes(type)
        ? types.filter((t) => t !== type)
        : [...types, type];
      return {
        config: { ...state.config, entity_types: newTypes },
      };
    }),
  setReplacementMode: (mode) =>
    set((state) => ({
      config: { ...state.config, replacement_mode: mode },
    })),

  // 脱敏结果
  redactionResult: null,
  setRedactionResult: (redactionResult) => set({ redactionResult }),

  // 对比数据
  compareData: null,
  setCompareData: (compareData) => set({ compareData }),

  // 加载状态
  isLoading: false,
  setIsLoading: (isLoading) => set({ isLoading }),
  loadingMessage: '',
  setLoadingMessage: (loadingMessage) => set({ loadingMessage }),

  // 错误状态
  error: null,
  setError: (error) => set({ error }),

  // 重置状态
  reset: () =>
    set({
      stage: 'upload',
      fileInfo: null,
      content: '',
      pages: [],
      entities: [],
      boundingBoxes: [],
      config: initialConfig,
      redactionResult: null,
      compareData: null,
      isLoading: false,
      loadingMessage: '',
      error: null,
    }),
}));

// 自定义 Hook：获取选中的实体
export const useSelectedEntities = () => {
  return useRedactionStore((state) =>
    state.entities.filter((e) => e.selected)
  );
};

// 自定义 Hook：按类型分组的实体
export const useEntitiesByType = () => {
  return useRedactionStore((state) => {
    const grouped: Record<string, Entity[]> = {};
    state.entities.forEach((entity) => {
      const type = entity.type;
      if (!grouped[type]) {
        grouped[type] = [];
      }
      grouped[type].push(entity);
    });
    return grouped;
  });
};

// 自定义 Hook：实体统计
export const useEntityStats = () => {
  return useRedactionStore((state) => {
    const total = state.entities.length;
    const selected = state.entities.filter((e) => e.selected).length;
    const byType: Record<string, number> = {};
    state.entities.forEach((entity) => {
      byType[entity.type] = (byType[entity.type] || 0) + 1;
    });
    return { total, selected, byType };
  });
};
