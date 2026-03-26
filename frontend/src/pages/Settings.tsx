import React, { useState, useEffect, useMemo } from 'react';
import { fetchWithTimeout } from '../utils/fetchWithTimeout';

interface EntityTypeConfig {
  id: string;
  name: string;
  description?: string;
  examples?: string[];
  color: string;
  regex_pattern?: string | null;
  use_llm?: boolean;
  enabled?: boolean;
  order?: number;
  tag_template?: string | null;
}

interface PipelineTypeConfig {
  id: string;
  name: string;
  description?: string;
  examples?: string[];
  color: string;
  enabled: boolean;
  order: number;
}

interface PipelineConfig {
  mode: 'ocr_has' | 'has_image';
  name: string;
  description: string;
  enabled: boolean;
  types: PipelineTypeConfig[];
}

/** 新增正则弹窗：校验表达式语法 + 与样例文本的匹配结果 */
type RegexModalCheck =
  | 'empty_pattern'
  | 'invalid_pattern'
  | 'no_sample'
  | 'pass'
  | 'fail';

function getRegexModalCheck(pattern: string, sample: string): RegexModalCheck {
  const p = pattern.trim();
  if (!p) return 'empty_pattern';
  let re: RegExp;
  try {
    re = new RegExp(p);
  } catch {
    return 'invalid_pattern';
  }
  const s = sample.trim();
  if (!s) return 'no_sample';
  return re.test(s) ? 'pass' : 'fail';
}

const settingsFieldClass =
  'w-full px-3 py-2 border border-[#e5e5e5] rounded-lg text-sm text-[#1d1d1f] placeholder:text-[#a3a3a3] bg-white focus:outline-none focus:border-[#1d1d1f]';
const settingsLabelClass = 'block text-sm font-medium text-[#1d1d1f] mb-1';

export const Settings: React.FC = () => {
  const [entityTypes, setEntityTypes] = useState<EntityTypeConfig[]>([]);
  const [pipelines, setPipelines] = useState<PipelineConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'text' | 'vision'>('text');
  /** 文本规则：正则 / 语义，单屏切换减少纵向滚动 */
  const [textRuleSub, setTextRuleSub] = useState<'regex' | 'llm'>('regex');
  /** 图像规则：OCR+HaS / HaS Image */
  const [visionRuleSub, setVisionRuleSub] = useState<'ocr_has' | 'has_image'>('ocr_has');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<Partial<EntityTypeConfig>>({});
  const [showAddModal, setShowAddModal] = useState(false);
  /** 正则弹窗：用于「通过/不通过」试匹配的样例文本 */
  const [regexModalTestInput, setRegexModalTestInput] = useState('');
  const [showAddPipelineTypeModal, setShowAddPipelineTypeModal] = useState<'ocr_has' | 'has_image' | null>(null);
  const [editingPipelineType, setEditingPipelineType] = useState<{ mode: string; type: PipelineTypeConfig } | null>(null);
  const [newPipelineType, setNewPipelineType] = useState({
    id: '',
    name: '',
    description: '',
    color: '#6B7280',
  });
  const [newType, setNewType] = useState({
    name: '',
    description: '',
    examples: '',
    color: '#6B7280',
    regex_pattern: '',
    use_llm: true,
    tag_template: '',
  });

  useEffect(() => {
    fetchEntityTypes();
    fetchPipelines();
  }, []);

  const fetchEntityTypes = async () => {
    try {
      setLoading(true);
      const res = await fetchWithTimeout('/api/v1/custom-types?enabled_only=false', { timeoutMs: 25000 });
      if (!res.ok) throw new Error('获取失败');
      const data = await res.json();
      setEntityTypes(data.custom_types || []);
    } catch (err) {
      console.error('获取实体类型失败', err);
    } finally {
      setLoading(false);
    }
  };

  const fetchPipelines = async () => {
    try {
      const res = await fetchWithTimeout('/api/v1/vision-pipelines', { timeoutMs: 25000 });
      if (!res.ok) throw new Error('获取失败');
      const data = await res.json();
      const normalizedPipelines = (data || []).map((p: PipelineConfig) =>
        p.mode === 'has_image'
          ? {
              ...p,
              name: 'HaS Image',
              description: '使用视觉语言模型识别签名、印章、手写等视觉信息。',
            }
          : p
      );
      setPipelines(normalizedPipelines);
    } catch (err) {
      console.error('获取Pipeline配置失败', err);
    }
  };

  const resetPipelines = async () => {
    if (!confirm('确定要重置所有Pipeline配置为默认吗？')) return;
    try {
      const res = await fetch('/api/v1/vision-pipelines/reset', { method: 'POST' });
      if (res.ok) {
        fetchPipelines();
      }
    } catch (err) {
      console.error('重置Pipeline配置失败', err);
    }
  };

  const createPipelineType = async () => {
    if (!showAddPipelineTypeModal || !newPipelineType.name.trim()) return;
    try {
      const typeId = newPipelineType.id || `custom_${Date.now()}`;
      const res = await fetch(`/api/v1/vision-pipelines/${showAddPipelineTypeModal}/types`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: typeId,
          name: newPipelineType.name,
          description: newPipelineType.description?.trim() || null,
          examples: [],
          color: '#6B7280',
          enabled: true,
          order: 100,
        }),
      });
      if (res.ok) {
        setShowAddPipelineTypeModal(null);
        setNewPipelineType({ id: '', name: '', description: '', color: '#6B7280' });
        fetchPipelines();
      } else {
        const data = await res.json();
        alert(data.detail || '创建失败');
      }
    } catch (err) {
      console.error('创建Pipeline类型失败', err);
    }
  };

  const deletePipelineType = async (mode: string, typeId: string) => {
    if (!confirm('确定要删除此类型吗？')) return;
    try {
      const res = await fetch(`/api/v1/vision-pipelines/${mode}/types/${typeId}`, { method: 'DELETE' });
      if (res.ok) {
        fetchPipelines();
      } else {
        const data = await res.json();
        alert(data.detail || '删除失败');
      }
    } catch (err) {
      console.error('删除Pipeline类型失败', err);
    }
  };

  const startEditPipelineType = (mode: string, type: PipelineTypeConfig) => {
    setEditingPipelineType({ mode, type: { ...type } });
    setNewPipelineType({
      id: type.id,
      name: type.name,
      description: type.description || '',
      color: type.color || '#6B7280',
    });
    setShowAddPipelineTypeModal(mode as 'ocr_has' | 'has_image');
  };

  const updatePipelineType = async () => {
    if (!editingPipelineType || !newPipelineType.name.trim()) return;
    try {
      const res = await fetch(`/api/v1/vision-pipelines/${editingPipelineType.mode}/types/${editingPipelineType.type.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: editingPipelineType.type.id,
          name: newPipelineType.name,
          description: newPipelineType.description?.trim() || null,
          examples: editingPipelineType.type.examples || [],
          color: editingPipelineType.type.color || '#6B7280',
          enabled: editingPipelineType.type.enabled,
          order: editingPipelineType.type.order,
        }),
      });
      if (res.ok) {
        setShowAddPipelineTypeModal(null);
        setEditingPipelineType(null);
        setNewPipelineType({ id: '', name: '', description: '', color: '#6B7280' });
        fetchPipelines();
      } else {
        const data = await res.json();
        alert(data.detail || '更新失败');
      }
    } catch (err) {
      console.error('更新Pipeline类型失败', err);
    }
  };

  const startEdit = (type: EntityTypeConfig) => {
    setEditingId(type.id);
    setEditForm({
      name: type.name,
      description: type.description || '',
      color: type.color,
      regex_pattern: type.regex_pattern || '',
      use_llm: type.use_llm ?? true,
      tag_template: type.tag_template || '',
    });
  };

  const saveEdit = async () => {
    if (!editingId) return;
    try {
      const res = await fetch(`/api/v1/custom-types/${editingId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editForm),
      });
      if (res.ok) {
        setEditingId(null);
        fetchEntityTypes();
      }
    } catch (err) {
      console.error('保存失败', err);
    }
  };
  void saveEdit; // 预留：文本类型编辑功能

  const createType = async () => {
    try {
      const res = await fetch('/api/v1/custom-types', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newType.name.trim(),
          description: newType.use_llm ? newType.description?.trim() || null : null,
          examples: [],
          color: '#6B7280',
          regex_pattern: newType.use_llm ? null : newType.regex_pattern || null,
          use_llm: newType.use_llm,
          tag_template: null,
        }),
      });
      if (res.ok) {
        setShowAddModal(false);
        setRegexModalTestInput('');
        setNewType({ name: '', description: '', examples: '', color: '#6B7280', regex_pattern: '', use_llm: true, tag_template: '' });
        fetchEntityTypes();
      }
    } catch (err) {
      console.error('创建失败', err);
    }
  };

  const deleteType = async (id: string) => {
    if (!confirm('确定要删除此类型吗？')) return;
    try {
      const res = await fetch(`/api/v1/custom-types/${id}`, { method: 'DELETE' });
      if (res.ok) {
        fetchEntityTypes();
      } else {
        const data = await res.json();
        alert(data.detail || '删除失败');
      }
    } catch (err) {
      console.error('删除失败', err);
    }
  };

  const resetToDefault = async () => {
    if (!confirm('确定要重置为默认配置吗？这将覆盖所有自定义修改。')) return;
    try {
      const res = await fetch('/api/v1/custom-types/reset', { method: 'POST' });
      if (res.ok) {
        fetchEntityTypes();
      }
    } catch (err) {
      console.error('重置失败', err);
    }
  };

  // 分类：正则类型和AI类型
  const regexTypes = entityTypes.filter(t => t.regex_pattern);
  const llmTypes = entityTypes.filter(t => t.use_llm);

  const regexModalCheck = useMemo(
    () => getRegexModalCheck(newType.regex_pattern, regexModalTestInput),
    [newType.regex_pattern, regexModalTestInput]
  );

  const pipeOcr = useMemo(() => pipelines.find(p => p.mode === 'ocr_has'), [pipelines]);
  const pipeImg = useMemo(() => pipelines.find(p => p.mode === 'has_image'), [pipelines]);
  const nOcr = pipeOcr?.types.length ?? 0;
  const nImg = pipeImg?.types.length ?? 0;
  const visionPipeline = useMemo(
    () => pipelines.find(p => p.mode === visionRuleSub),
    [pipelines, visionRuleSub]
  );

  return (
    <div className="flex-1 min-h-0 min-w-0 flex flex-col overflow-hidden bg-[#fafafa]">
      <div className="flex-1 min-h-0 flex flex-col overflow-hidden px-3 py-2 sm:px-4 sm:py-3 w-full max-w-[min(100%,1920px)] mx-auto">
        {loading ? (
          <div className="flex items-center justify-center py-24">
            <div className="w-7 h-7 border-2 border-[#e5e5e5] border-t-[#0a0a0a] rounded-full animate-spin" />
          </div>
        ) : (
          <div className="flex-1 min-h-0 flex flex-col gap-2 overflow-hidden">
            <div className="shrink-0 flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => setActiveTab('text')}
                className={`px-3 py-1.5 text-xs font-medium rounded-md border transition-colors ${
                  activeTab === 'text'
                    ? 'border-black bg-black text-white'
                    : 'border-[#e5e5e5] text-[#737373] hover:bg-[#f5f5f5]'
                }`}
              >
                文本识别规则
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('vision')}
                className={`px-3 py-1.5 text-xs font-medium rounded-md border transition-colors ${
                  activeTab === 'vision'
                    ? 'border-black bg-black text-white'
                    : 'border-[#e5e5e5] text-[#737373] hover:bg-[#f5f5f5]'
                }`}
              >
                图像识别规则
              </button>
            </div>

            {activeTab === 'text' && (
              <div className="flex-1 min-h-0 flex flex-col overflow-hidden gap-2">
                {/* 与图像页一致：说明一行 + 下一行 w-fit 切换条与「重置」 */}
                <div className="shrink-0 flex flex-wrap items-center gap-2 text-2xs text-[#737373]">
                  <span>正则</span>
                  <span>+</span>
                  <span>AI 语义（HaS）</span>
                  <span className="text-[#d4d4d4]">|</span>
                  <span>双路规则</span>
                </div>
                <div className="shrink-0 flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap gap-1 p-0.5 bg-gray-100/90 rounded-md border border-gray-200/80 w-fit max-w-full">
                    <button
                      type="button"
                      onClick={() => setTextRuleSub('regex')}
                      className={`px-2 py-1 text-caption font-medium rounded transition-colors ${
                        textRuleSub === 'regex'
                          ? 'bg-white text-[#1d1d1f] shadow-sm border border-[#007AFF]/55'
                          : 'text-[#737373] hover:text-[#1d1d1f]'
                      }`}
                    >
                      正则
                      <span className="ml-1 tabular-nums text-[#a3a3a3] font-normal">({regexTypes.length})</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setTextRuleSub('llm')}
                      className={`px-2 py-1 text-caption font-medium rounded transition-colors ${
                        textRuleSub === 'llm'
                          ? 'bg-white text-[#1d1d1f] shadow-sm border border-[#34C759]/55'
                          : 'text-[#737373] hover:text-[#1d1d1f]'
                      }`}
                    >
                      语义
                      <span className="ml-1 tabular-nums text-[#a3a3a3] font-normal">({llmTypes.length})</span>
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={resetToDefault}
                    className="text-caption text-[#737373] hover:text-[#1d1d1f] shrink-0"
                  >
                    重置文本规则
                  </button>
                </div>

                {textRuleSub === 'regex' && (
                  <div className="flex-1 min-h-0 flex flex-col overflow-hidden rounded-lg border border-[#007AFF]/22 bg-white shadow-sm shadow-black/[0.04]">
                    <div className="shrink-0 px-3 py-2 border-b border-[#007AFF]/15 bg-[#007AFF]/[0.05] flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="w-2 h-2 rounded-full shrink-0 bg-[#007AFF]/90 ring-1 ring-[#007AFF]/25" />
                          <span className="font-semibold text-[#1d1d1f] text-xs truncate">正则规则</span>
                        </div>
                        <p className="text-2xs text-[#737373] mt-0.5 line-clamp-2">每条为一条正则模式 · 多列卡片展示</p>
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          setRegexModalTestInput('');
                          setNewType({
                            name: '',
                            description: '',
                            examples: '',
                            color: '#6B7280',
                            regex_pattern: '',
                            use_llm: false,
                            tag_template: '',
                          });
                          setShowAddModal(true);
                        }}
                        className="px-2 py-1 text-caption rounded-md text-white shrink-0 bg-black hover:bg-zinc-900"
                      >
                        + 新增
                      </button>
                    </div>
                    <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain p-2">
                      {regexTypes.length === 0 ? (
                        <p className="py-6 text-sm text-[#a3a3a3] text-center">暂无类型配置</p>
                      ) : (
                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-1.5">
                          {regexTypes.map(type => (
                            <div
                              key={type.id}
                              className="rounded-md border border-[#007AFF]/22 bg-[#007AFF]/[0.06] px-2 py-1.5 flex gap-1.5 items-start shadow-sm shadow-black/[0.03]"
                            >
                              <div className="min-w-0 flex-1">
                                <div className="flex items-start justify-between gap-2">
                                  <div className="min-w-0">
                                    <span className="font-medium text-[#0a4a8c] text-xs leading-tight">{type.name}</span>
                                    <span className="text-2xs text-[#007AFF]/80 block truncate">{type.id}</span>
                                  </div>
                                  <div className="flex items-center gap-0.5 shrink-0">
                                    <button
                                      type="button"
                                      onClick={() => startEdit(type)}
                                      className="p-1 text-[#007AFF]/50 hover:text-[#007AFF]"
                                      title="编辑"
                                    >
                                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                                      </svg>
                                    </button>
                                    {type.id.startsWith('custom_') && (
                                      <button
                                        type="button"
                                        onClick={() => deleteType(type.id)}
                                        className="p-1 text-[#007AFF]/50 hover:text-red-500"
                                        title="删除"
                                      >
                                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                        </svg>
                                      </button>
                                    )}
                                  </div>
                                </div>
                                {type.regex_pattern && (
                                  <code className="text-2xs text-[#1e40af]/90 mt-1 font-mono block break-all leading-snug">
                                    {type.regex_pattern}
                                  </code>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {textRuleSub === 'llm' && (
                  <div className="flex-1 min-h-0 flex flex-col overflow-hidden rounded-lg border border-[#34C759]/22 bg-white shadow-sm shadow-black/[0.04]">
                    <div className="shrink-0 px-3 py-2 border-b border-[#34C759]/15 bg-[#34C759]/[0.06] flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="w-2 h-2 rounded-full shrink-0 bg-[#34C759]/90 ring-1 ring-[#34C759]/30" />
                          <span className="font-semibold text-[#1d1d1f] text-xs truncate">AI 语义（HaS）</span>
                        </div>
                        <p className="text-2xs text-[#737373] mt-0.5 line-clamp-2">无固定正则 · 由模型识别语义类型</p>
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          setRegexModalTestInput('');
                          setNewType({
                            name: '',
                            description: '',
                            examples: '',
                            color: '#6B7280',
                            regex_pattern: '',
                            use_llm: true,
                            tag_template: '',
                          });
                          setShowAddModal(true);
                        }}
                        className="px-2 py-1 text-caption rounded-md text-white shrink-0 bg-black hover:bg-zinc-900"
                      >
                        + 新增
                      </button>
                    </div>
                    <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain p-2">
                      {llmTypes.length === 0 ? (
                        <p className="py-4 text-xs text-[#a3a3a3] text-center">暂无类型配置</p>
                      ) : (
                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-1.5">
                          {llmTypes.map(type => (
                            <div
                              key={type.id}
                              className="rounded-md border border-[#34C759]/22 bg-[#34C759]/[0.07] px-2 py-1.5 flex gap-1.5 items-start shadow-sm shadow-black/[0.03]"
                            >
                              <div className="min-w-0 flex-1">
                                <div className="flex items-start justify-between gap-2">
                                  <div className="min-w-0">
                                    <span className="font-medium text-[#0d5c2f] text-xs leading-tight">{type.name}</span>
                                    <span className="text-2xs text-[#34C759]/85 block truncate">{type.id}</span>
                                  </div>
                                  <div className="flex items-center gap-0.5 shrink-0">
                                    <button
                                      type="button"
                                      onClick={() => startEdit(type)}
                                      className="p-1 text-[#34C759]/45 hover:text-[#34C759]"
                                      title="编辑"
                                    >
                                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                                      </svg>
                                    </button>
                                    {type.id.startsWith('custom_') && (
                                      <button
                                        type="button"
                                        onClick={() => deleteType(type.id)}
                                        className="p-1 text-[#34C759]/45 hover:text-red-500"
                                        title="删除"
                                      >
                                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                        </svg>
                                      </button>
                                    )}
                                  </div>
                                </div>
                                {type.description && (
                                  <p className="text-caption text-[#166534]/90 mt-1 line-clamp-2 leading-snug">{type.description}</p>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}

            {activeTab === 'vision' && (
              <div className="flex-1 min-h-0 flex flex-col overflow-hidden gap-2">
                <div className="shrink-0 flex flex-wrap items-center gap-2 text-2xs text-[#737373]">
                  <span>OCR+HaS</span>
                  <span>+</span>
                  <span>HaS Image</span>
                  <span className="text-[#d4d4d4]">|</span>
                  <span>两路合并输出</span>
                </div>
                <div className="shrink-0 flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap gap-1 p-0.5 bg-gray-100/90 rounded-md border border-gray-200/80 w-fit max-w-full">
                  <button
                    type="button"
                    onClick={() => setVisionRuleSub('ocr_has')}
                    className={`px-2 py-1 text-caption font-medium rounded transition-colors ${
                      visionRuleSub === 'ocr_has'
                        ? 'bg-white text-[#1d1d1f] shadow-sm border border-[#34C759]/55'
                        : 'text-[#737373] hover:text-[#1d1d1f]'
                    }`}
                  >
                    {pipeOcr?.name ?? 'OCR+HaS'}
                    <span className="ml-1 tabular-nums text-[#a3a3a3] font-normal">({nOcr})</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setVisionRuleSub('has_image')}
                    className={`px-2 py-1 text-caption font-medium rounded transition-colors ${
                      visionRuleSub === 'has_image'
                        ? 'bg-white text-[#1d1d1f] shadow-sm border border-[#AF52DE]/55'
                        : 'text-[#737373] hover:text-[#1d1d1f]'
                    }`}
                  >
                    {pipeImg?.name ?? 'HaS Image'}
                    <span className="ml-1 tabular-nums text-[#a3a3a3] font-normal">({nImg})</span>
                  </button>
                  </div>
                  <button
                    type="button"
                    onClick={resetPipelines}
                    className="text-caption text-[#737373] hover:text-[#1d1d1f] shrink-0"
                  >
                    重置图像规则
                  </button>
                </div>

                {!visionPipeline ? (
                  <div className="flex-1 min-h-0 flex items-center justify-center text-xs text-gray-400 py-6">
                    加载 Pipeline 配置中…
                  </div>
                ) : (
                  (() => {
                    const pipeline = visionPipeline;
                    const isHasImageVision = pipeline.mode === 'has_image';
                    const displayName = isHasImageVision ? 'HaS Image' : pipeline.name;
                    const displayDesc = isHasImageVision
                      ? 'YOLO11 · 视觉特征'
                      : pipeline.description;
                    return (
                      <div
                        className={`flex-1 min-h-0 flex flex-col overflow-hidden rounded-lg border bg-white shadow-sm shadow-black/[0.04] ${
                          isHasImageVision
                            ? 'border-[#AF52DE]/25'
                            : 'border-[#34C759]/22'
                        }`}
                      >
                        <div
                          className={`shrink-0 px-3 py-2 border-b flex items-center justify-between gap-2 ${
                            isHasImageVision
                              ? 'border-[#AF52DE]/18 bg-[#AF52DE]/[0.06]'
                              : 'border-[#34C759]/15 bg-[#34C759]/[0.05]'
                          }`}
                        >
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <span
                                className={`w-2 h-2 rounded-full shrink-0 ring-1 ${
                                  isHasImageVision
                                    ? 'bg-[#AF52DE]/90 ring-[#AF52DE]/35'
                                    : 'bg-[#34C759]/90 ring-[#34C759]/30'
                                }`}
                              />
                              <span className="font-semibold text-[#1d1d1f] text-xs truncate">{displayName}</span>
                            </div>
                            <p className="text-2xs text-[#737373] mt-0.5 line-clamp-2">{displayDesc}</p>
                          </div>
                          <button
                            type="button"
                            onClick={() => {
                              setEditingPipelineType(null);
                              setNewPipelineType({ id: '', name: '', description: '', color: '#6B7280' });
                              setShowAddPipelineTypeModal(pipeline.mode);
                            }}
                            className="px-2 py-1 text-caption rounded-md text-white shrink-0 bg-black hover:bg-zinc-900"
                          >
                            + 新增
                          </button>
                        </div>
                        <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain p-2">
                          {pipeline.types.length === 0 ? (
                            <p className="py-4 text-xs text-[#a3a3a3] text-center">暂无类型配置</p>
                          ) : (
                            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-1.5">
                              {pipeline.types.map(type => (
                                <div
                                  key={type.id}
                                  className={`rounded-md px-2 py-1.5 flex gap-2 items-start shadow-sm shadow-black/[0.03] ${
                                    isHasImageVision
                                      ? 'border border-[#AF52DE]/22 bg-[#AF52DE]/[0.07]'
                                      : 'border border-[#34C759]/22 bg-[#34C759]/[0.06]'
                                  }`}
                                >
                                  <div className="min-w-0 flex-1">
                                    <div className="flex items-start justify-between gap-1">
                                      <div className="min-w-0">
                                        <span
                                          className={`font-medium text-xs leading-tight block truncate ${
                                            isHasImageVision ? 'text-[#5c2d7a]' : 'text-[#0d5c2f]'
                                          }`}
                                        >
                                          {type.name}
                                        </span>
                                        <span
                                          className={`text-2xs truncate block ${
                                            isHasImageVision ? 'text-[#AF52DE]/85' : 'text-[#34C759]/85'
                                          }`}
                                        >
                                          {type.id}
                                        </span>
                                      </div>
                                      <div className="flex items-center gap-0.5 shrink-0">
                                        <button
                                          type="button"
                                          onClick={() => startEditPipelineType(pipeline.mode, type)}
                                          className={`p-1 hover:text-[#1d1d1f] ${
                                            isHasImageVision ? 'text-[#AF52DE]/45' : 'text-[#34C759]/45'
                                          }`}
                                          title="编辑"
                                        >
                                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                                          </svg>
                                        </button>
                                        <button
                                          type="button"
                                          onClick={() => deletePipelineType(pipeline.mode, type.id)}
                                          className={`p-1 hover:text-red-500 ${
                                            isHasImageVision ? 'text-[#AF52DE]/45' : 'text-[#34C759]/45'
                                          }`}
                                          title="删除"
                                        >
                                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                          </svg>
                                        </button>
                                      </div>
                                    </div>
                                    {type.description && (
                                      <p
                                        className={`text-2xs mt-0.5 line-clamp-2 leading-snug ${
                                          isHasImageVision ? 'text-[#6b2d7a]/90' : 'text-[#166534]/90'
                                        }`}
                                      >
                                        {type.description}
                                      </p>
                                    )}
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })()
                )}
              </div>
            )}
          </div>
        )}

      {/* 新增弹窗：正则精简卡片 / 语义保留完整表单 */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
          <div
            className={`bg-white rounded-xl w-full p-6 shadow-xl border border-black/[0.06] ${newType.use_llm ? 'max-w-md' : 'max-w-lg'}`}
          >
            <div className="flex items-start gap-2.5 mb-3">
              <span
                className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ring-1 ${
                  newType.use_llm
                    ? 'bg-[#34C759]/90 ring-[#34C759]/30'
                    : 'bg-[#007AFF]/90 ring-[#007AFF]/25'
                }`}
              />
              <div className="min-w-0">
                <h3 className="text-lg font-semibold text-[#1d1d1f] leading-tight">
                  {newType.use_llm ? '新增语义类型' : '新增正则类型'}
                </h3>
                <p className="text-2xs text-[#737373] mt-1 leading-snug">
                  {newType.use_llm
                    ? '与批量向导「语义规则」同色（绿）；名称必填，说明选填。'
                    : '与批量向导「正则规则」同色（蓝）；名称与正则必填，可填样例即时校验。'}
                </p>
              </div>
            </div>

            {!newType.use_llm ? (
              <div className="space-y-4">
                <div>
                  <label className={settingsLabelClass}>
                    名称 <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={newType.name}
                    onChange={e => setNewType({ ...newType, name: e.target.value })}
                    className={settingsFieldClass}
                    placeholder="如：合同签订日期"
                  />
                </div>
                <div>
                  <label className={settingsLabelClass}>
                    正则表达式 <span className="text-red-500">*</span>
                  </label>
                  <textarea
                    value={newType.regex_pattern}
                    onChange={e => setNewType({ ...newType, regex_pattern: e.target.value })}
                    rows={3}
                    className={`${settingsFieldClass} font-mono leading-relaxed resize-y min-h-[4.5rem]`}
                    placeholder={'例如：\\d{4}-\\d{2}-\\d{2}'}
                    spellCheck={false}
                  />
                </div>
                <div>
                  <label className={settingsLabelClass}>试匹配文本</label>
                  <textarea
                    value={regexModalTestInput}
                    onChange={e => setRegexModalTestInput(e.target.value)}
                    rows={2}
                    className={`${settingsFieldClass} resize-y leading-relaxed`}
                    placeholder="粘贴或输入一段文字，用于验证正则在其中能否匹配"
                  />
                </div>
                <div className="rounded-lg border border-[#007AFF]/22 bg-[#007AFF]/[0.06] px-3 py-2.5 flex flex-wrap items-center gap-2">
                  <span className="text-2xs font-medium text-[#007AFF]/90">正则验证</span>
                  {regexModalCheck === 'empty_pattern' && (
                    <span className="text-sm text-[#a3a3a3]">请先填写正则表达式</span>
                  )}
                  {regexModalCheck === 'invalid_pattern' && (
                    <span className="text-sm font-medium text-red-600">不通过 · 表达式无效</span>
                  )}
                  {regexModalCheck === 'no_sample' && (
                    <span className="text-sm text-[#737373]">已就绪 · 填写试匹配文本可查看通过/不通过</span>
                  )}
                  {regexModalCheck === 'pass' && (
                    <span className="text-sm font-medium text-emerald-700">通过 · 样例中可匹配</span>
                  )}
                  {regexModalCheck === 'fail' && (
                    <span className="text-sm font-medium text-red-600">不通过 · 样例中未匹配</span>
                  )}
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                <div>
                  <label className={settingsLabelClass}>
                    名称 <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={newType.name}
                    onChange={e => setNewType({ ...newType, name: e.target.value })}
                    className={settingsFieldClass}
                    placeholder="如：项目负责人职务"
                  />
                </div>
                <div>
                  <label className={settingsLabelClass}>说明（选填）</label>
                  <textarea
                    value={newType.description}
                    onChange={e => setNewType({ ...newType, description: e.target.value })}
                    rows={3}
                    className={`${settingsFieldClass} resize-y leading-relaxed`}
                    placeholder="简要说明这类信息在文档中的文字特征，便于模型识别"
                  />
                </div>
              </div>
            )}

            <div className="flex justify-end gap-3 mt-6">
              <button
                type="button"
                onClick={() => {
                  setRegexModalTestInput('');
                  setShowAddModal(false);
                }}
                className="px-4 py-2 text-sm text-[#737373] hover:text-[#1d1d1f]"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void createType()}
                disabled={
                  !newType.name.trim() ||
                  (newType.use_llm ? false : !newType.regex_pattern.trim() || regexModalCheck === 'invalid_pattern')
                }
                className="px-4 py-2 text-sm font-medium text-white bg-black rounded-lg hover:bg-zinc-900 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                创建
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 新增/编辑 Pipeline 类型（OCR+HaS / HaS Image） */}
      {showAddPipelineTypeModal && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl w-full max-w-md p-6 shadow-xl border border-black/[0.06]">
            <div className="flex items-start gap-2.5 mb-4">
              <span
                className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ring-1 ${
                  showAddPipelineTypeModal === 'has_image'
                    ? 'bg-[#AF52DE]/90 ring-[#AF52DE]/35'
                    : 'bg-[#34C759]/90 ring-[#34C759]/30'
                }`}
              />
              <div className="min-w-0">
                <h3 className="text-lg font-semibold text-[#1d1d1f] leading-tight">
                  {editingPipelineType ? '编辑类型' : '新增类型'}
                </h3>
                <p className="text-2xs text-[#737373] mt-1 leading-snug">
                  {showAddPipelineTypeModal === 'ocr_has'
                    ? 'OCR + HaS · 与批量向导「图片类文本」同色（绿）'
                    : 'HaS Image · 与批量向导「图像特征」同色（紫）'}
                </p>
              </div>
            </div>
            <div className="space-y-4">
              {!editingPipelineType && (
                <div>
                  <label className={settingsLabelClass}>类型 ID（选填）</label>
                  <input
                    type="text"
                    value={newPipelineType.id}
                    onChange={e =>
                      setNewPipelineType({
                        ...newPipelineType,
                        id: e.target.value.toUpperCase().replace(/\s+/g, '_'),
                      })
                    }
                    className={`${settingsFieldClass} font-mono`}
                    placeholder="如：LAB_NAME，留空自动生成"
                  />
                </div>
              )}
              {editingPipelineType && (
                <div>
                  <label className={settingsLabelClass}>类型 ID</label>
                  <div className="px-3 py-2 bg-[#fafafa] border border-[#e5e5e5] rounded-lg font-mono text-sm text-[#737373]">
                    {editingPipelineType.type.id}
                  </div>
                </div>
              )}
              <div>
                <label className={settingsLabelClass}>
                  显示名称 <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  value={newPipelineType.name}
                  onChange={e => setNewPipelineType({ ...newPipelineType, name: e.target.value })}
                  className={settingsFieldClass}
                  placeholder={showAddPipelineTypeModal === 'ocr_has' ? '如：合同甲方名称' : '如：人脸区域'}
                />
              </div>
              <div>
                <label className={settingsLabelClass}>说明（选填）</label>
                <textarea
                  value={newPipelineType.description}
                  onChange={e => setNewPipelineType({ ...newPipelineType, description: e.target.value })}
                  rows={3}
                  className={`${settingsFieldClass} resize-y leading-relaxed`}
                  placeholder={
                    showAddPipelineTypeModal === 'ocr_has'
                      ? '文字在图中的常见写法或上下文提示'
                      : '视觉上如何辨认该区域（形状、位置、用途）'
                  }
                />
              </div>
              <p className="text-2xs text-[#a3a3a3] leading-snug">
                保存后列表按上方面板配色展示（绿 / 紫），与批量向导一致。
              </p>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button
                type="button"
                onClick={() => {
                  setShowAddPipelineTypeModal(null);
                  setEditingPipelineType(null);
                  setNewPipelineType({ id: '', name: '', description: '', color: '#6B7280' });
                }}
                className="px-4 py-2 text-sm text-[#737373] hover:text-[#1d1d1f]"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void (editingPipelineType ? updatePipelineType() : createPipelineType())}
                disabled={!newPipelineType.name.trim()}
                className="px-4 py-2 text-sm font-medium text-white bg-black rounded-lg hover:bg-zinc-900 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {editingPipelineType ? '保存' : '创建'}
              </button>
            </div>
          </div>
        </div>
      )}

      </div>
    </div>
  );
};

export default Settings;
