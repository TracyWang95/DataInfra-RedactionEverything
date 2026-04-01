import { describe, it, expect, beforeEach } from 'vitest';
import { useFileStore, useEntityStore, useRedactionConfigStore, useUIStore, resetAllStores } from './useRedaction';
import { EntityType, ReplacementMode } from '../types';

describe('useFileStore', () => {
  beforeEach(() => useFileStore.getState().resetFile());

  it('sets and gets fileInfo', () => {
    const info = { file_id: '1', filename: 'test.pdf', file_type: 'pdf' as any, file_size: 100, page_count: 1 };
    useFileStore.getState().setFileInfo(info);
    expect(useFileStore.getState().fileInfo).toEqual(info);
  });

  it('resets to initial state', () => {
    useFileStore.getState().setContent('hello', ['p1']);
    useFileStore.getState().resetFile();
    expect(useFileStore.getState().content).toBe('');
    expect(useFileStore.getState().pages).toEqual([]);
  });
});

describe('useEntityStore', () => {
  beforeEach(() => useEntityStore.getState().resetEntities());

  it('toggles entity selection', () => {
    const entities = [
      { id: 'e1', text: '张三', type: EntityType.PERSON, start: 0, end: 2, page: 1, confidence: 0.9, selected: true },
      { id: 'e2', text: '李四', type: EntityType.PERSON, start: 5, end: 7, page: 1, confidence: 0.9, selected: false },
    ];
    useEntityStore.getState().setEntities(entities);
    useEntityStore.getState().toggleEntitySelection('e1');
    expect(useEntityStore.getState().entities[0].selected).toBe(false);
    expect(useEntityStore.getState().entities[1].selected).toBe(false);
  });

  it('selectAll / deselectAll', () => {
    const entities = [
      { id: 'e1', text: 'A', type: EntityType.PHONE, start: 0, end: 1, page: 1, confidence: 1, selected: false },
      { id: 'e2', text: 'B', type: EntityType.PHONE, start: 2, end: 3, page: 1, confidence: 1, selected: false },
    ];
    useEntityStore.getState().setEntities(entities);
    useEntityStore.getState().selectAllEntities();
    expect(useEntityStore.getState().entities.every(e => e.selected)).toBe(true);
    useEntityStore.getState().deselectAllEntities();
    expect(useEntityStore.getState().entities.every(e => !e.selected)).toBe(true);
  });

  it('adds manual entity with generated id', () => {
    useEntityStore.getState().addManualEntity({
      text: '测试', type: EntityType.CUSTOM, start: 0, end: 2, page: 1, confidence: 1, selected: true,
    });
    const entities = useEntityStore.getState().entities;
    expect(entities.length).toBe(1);
    expect(entities[0].id).toMatch(/^manual_/);
  });
});

describe('useRedactionConfigStore', () => {
  beforeEach(() => useRedactionConfigStore.getState().resetRedaction());

  it('toggles entity type', () => {
    const initial = useRedactionConfigStore.getState().config.entity_types;
    expect(initial).toContain(EntityType.PERSON);
    useRedactionConfigStore.getState().toggleEntityType(EntityType.PERSON);
    expect(useRedactionConfigStore.getState().config.entity_types).not.toContain(EntityType.PERSON);
    useRedactionConfigStore.getState().toggleEntityType(EntityType.PERSON);
    expect(useRedactionConfigStore.getState().config.entity_types).toContain(EntityType.PERSON);
  });

  it('sets replacement mode', () => {
    useRedactionConfigStore.getState().setReplacementMode(ReplacementMode.MASK);
    expect(useRedactionConfigStore.getState().config.replacement_mode).toBe(ReplacementMode.MASK);
  });
});

describe('useUIStore', () => {
  beforeEach(() => useUIStore.getState().resetUI());

  it('manages loading state', () => {
    useUIStore.getState().setIsLoading(true);
    useUIStore.getState().setLoadingMessage('Processing...');
    expect(useUIStore.getState().isLoading).toBe(true);
    expect(useUIStore.getState().loadingMessage).toBe('Processing...');
  });

  it('manages error state', () => {
    useUIStore.getState().setError('Network error');
    expect(useUIStore.getState().error).toBe('Network error');
    useUIStore.getState().setError(null);
    expect(useUIStore.getState().error).toBeNull();
  });
});

describe('resetAllStores', () => {
  it('clears all sub-store state', () => {
    useUIStore.getState().setStage('preview');
    useUIStore.getState().setIsLoading(true);
    resetAllStores();
    expect(useUIStore.getState().stage).toBe('upload');
    expect(useUIStore.getState().isLoading).toBe(false);
    expect(useFileStore.getState().fileInfo).toBeNull();
    expect(useEntityStore.getState().entities).toEqual([]);
    expect(useRedactionConfigStore.getState().redactionResult).toBeNull();
  });
});
