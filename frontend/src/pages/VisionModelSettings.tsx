import React, { useState, useEffect } from 'react';
import { fetchWithTimeout } from '../utils/fetchWithTimeout';
import { formCheckboxClass } from '../ui/selectionClasses';

interface ModelConfig {
  id: string;
  name: string;
  provider: 'local' | 'zhipu' | 'openai' | 'custom';
  enabled: boolean;
  base_url?: string;
  api_key?: string;
  model_name: string;
  temperature: number;
  top_p: number;
  max_tokens: number;
  enable_thinking: boolean;
  description?: string;
}

interface ModelConfigList {
  configs: ModelConfig[];
  active_id?: string;
}

/** 与 GET /health/services 对齐，用于内置行展示「在线/离线」 */
interface BuiltinServiceLive {
  paddle?: 'online' | 'offline';
  has_image?: 'online' | 'offline';
}

export const VisionModelSettings: React.FC = () => {
  const [modelConfigs, setModelConfigs] = useState<ModelConfigList>({ configs: [], active_id: undefined });
  const [loading, setLoading] = useState(true);
  const [builtinLive, setBuiltinLive] = useState<BuiltinServiceLive | null>(null);

  // 模型配置相关状态
  const [showAddModelModal, setShowAddModelModal] = useState(false);
  const [editingModelId, setEditingModelId] = useState<string | null>(null);
  const [modelForm, setModelForm] = useState<Partial<ModelConfig>>({
    provider: 'local',
    temperature: 0.8,
    top_p: 0.6,
    max_tokens: 4096,
    enable_thinking: false,
  });
  const [testingModelId, setTestingModelId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);

  /** 与后端 VISION_BUILTIN_IDS 一致：不显示删除 */
  const BUILTIN_VISION_IDS = new Set(['paddle_ocr_service', 'has_image_service']);

  useEffect(() => {
    fetchModelConfigs();
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch('/health/services');
        if (!res.ok || cancelled) return;
        const d = await res.json();
        setBuiltinLive({
          paddle: d.services?.paddle_ocr?.status,
          has_image: d.services?.has_image?.status,
        });
      } catch {
        if (!cancelled) setBuiltinLive({ paddle: undefined, has_image: undefined });
      }
    };
    load();
    const t = setInterval(load, 15000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  const fetchModelConfigs = async () => {
    try {
      setLoading(true);
      const res = await fetchWithTimeout('/api/v1/model-config', { timeoutMs: 25000 });
      if (!res.ok) throw new Error('获取失败');
      const data = await res.json();
      setModelConfigs(data);
    } catch (err) {
      console.error('获取模型配置失败', err);
    } finally {
      setLoading(false);
    }
  };

  const saveModelConfig = async () => {
    if (!modelForm.name || !modelForm.model_name) return;
    
    try {
      const configId = editingModelId || `custom_${Date.now()}`;
      const payload = {
        ...modelForm,
        id: configId,
        enabled:
          editingModelId && BUILTIN_VISION_IDS.has(editingModelId) ? true : (modelForm.enabled ?? true),
      };
      
      const url = editingModelId 
        ? `/api/v1/model-config/${editingModelId}`
        : '/api/v1/model-config';
      const method = editingModelId ? 'PUT' : 'POST';
      
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      
      if (res.ok) {
        setShowAddModelModal(false);
        setEditingModelId(null);
        setModelForm({
          provider: 'local',
          temperature: 0.8,
          top_p: 0.6,
          max_tokens: 4096,
          enable_thinking: false,
        });
        fetchModelConfigs();
      } else {
        const data = await res.json();
        alert(data.detail || '保存失败');
      }
    } catch (err) {
      console.error('保存模型配置失败', err);
    }
  };

  const deleteModelConfig = async (configId: string) => {
    if (!confirm('确定要删除此模型配置吗？')) return;
    try {
      const res = await fetch(`/api/v1/model-config/${configId}`, { method: 'DELETE' });
      if (res.ok) {
        fetchModelConfigs();
      } else {
        const data = await res.json();
        alert(data.detail || '删除失败');
      }
    } catch (err) {
      console.error('删除模型配置失败', err);
    }
  };

  const testModelConfig = async (configId: string) => {
    setTestingModelId(configId);
    setTestResult(null);
    try {
      const timeoutMs = configId === 'paddle_ocr_service' ? 60000 : 15000;
      const res = await fetchWithTimeout(`/api/v1/model-config/test/${configId}`, {
        method: 'POST',
        timeoutMs,
      });
      const data = await res.json();
      setTestResult(data);
    } catch (err) {
      setTestResult({
        success: false,
        message:
          configId === 'paddle_ocr_service'
            ? '测试请求失败或超时（OCR 首启加载可能较慢）'
            : '测试请求失败',
      });
    } finally {
      setTestingModelId(null);
    }
  };

  const resetModelConfigs = async () => {
    if (!confirm('确定要重置所有模型配置为默认吗？')) return;
    try {
      const res = await fetch('/api/v1/model-config/reset', { method: 'POST' });
      if (res.ok) {
        fetchModelConfigs();
      }
    } catch (err) {
      console.error('重置模型配置失败', err);
    }
  };

  const startEditModel = (config: ModelConfig) => {
    setEditingModelId(config.id);
    setModelForm({ ...config });
    setShowAddModelModal(true);
  };

  const getProviderLabel = (provider: string) => {
    switch (provider) {
      case 'local': return '本地';
      case 'zhipu': return '智谱（旧）';
      case 'openai': return 'OpenAI';
      case 'custom': return '自定义';
      default: return provider;
    }
  };

  const liveForBuiltin = (configId: string): 'online' | 'offline' | undefined => {
    if (configId === 'paddle_ocr_service') return builtinLive?.paddle;
    if (configId === 'has_image_service') return builtinLive?.has_image;
    return undefined;
  };

  return (
    <div className="h-full min-h-0 min-w-0 flex flex-col overflow-hidden bg-[#fafafa]">
      <div className="flex-1 min-h-0 overflow-auto overscroll-contain p-4 sm:p-6 w-full max-w-5xl mx-auto">
      {loading ? (
        <div className="flex items-center justify-center py-24">
          <div className="w-7 h-7 border-2 border-[#e5e5e5] border-t-[#0a0a0a] rounded-full animate-spin" />
        </div>
      ) : (
        <div className="flex flex-col gap-5">
          <section className="rounded-xl border border-gray-200/90 bg-gray-50/90 p-5">
            <h3 className="text-sm font-semibold text-gray-900">视觉微服务</h3>
            <p className="text-xs text-gray-600 leading-relaxed mt-2">
              <strong className="font-medium text-gray-800">PaddleOCR-VL</strong> 默认端口{' '}
              <strong>8082</strong>（<code className="text-2xs bg-white px-1 py-0.5 rounded border border-gray-200/90">OCR_BASE_URL</code>），启动示例{' '}
              <code className="text-2xs bg-white px-1 py-0.5 rounded border border-gray-200/90">scripts\start_paddle_ocr.ps1</code>。
              <strong className="font-medium text-gray-800"> HaS Image</strong> 默认端口 <strong>8081</strong>（
              <code className="text-2xs bg-white px-1 py-0.5 rounded border border-gray-200/90">HAS_IMAGE_BASE_URL</code>），
              <code className="text-2xs bg-white px-1 py-0.5 rounded border border-gray-200/90">has_image_server.py</code>，启动{' '}
              <code className="text-2xs bg-white px-1 py-0.5 rounded border border-gray-200/90">scripts\start_has_image.bat</code>。
              下方列表为内置登记与自定义后端，均可「测试」连通性。
            </p>
            <div className="flex flex-wrap gap-2 mt-4 pt-4 border-t border-gray-200/80">
              <span className="text-xs text-gray-700 px-2 py-1 rounded-md bg-white border border-gray-200/90">本地 HTTP</span>
              <span className="text-xs text-gray-700 px-2 py-1 rounded-md bg-white border border-gray-200/90">OpenAI 兼容</span>
              <span className="text-xs text-gray-700 px-2 py-1 rounded-md bg-white border border-gray-200/90">自定义 HTTP</span>
            </div>
          </section>

          <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
            <div className="px-5 py-4 border-b border-gray-100 flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold text-gray-900">推理后端</h2>
                <p className="text-xs text-gray-500 mt-1 leading-relaxed">
                  PaddleOCR-VL 与 HaS Image 为内置登记；路由由后端环境变量决定，无需在此切换提供方。
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setEditingModelId(null);
                  setModelForm({
                    provider: 'local',
                    temperature: 0.8,
                    top_p: 0.6,
                    max_tokens: 4096,
                    enable_thinking: false,
                    enabled: true,
                  });
                  setShowAddModelModal(true);
                }}
                className="px-3 py-1.5 text-xs rounded-lg bg-[#0a0a0a] text-white hover:bg-[#262626]"
              >
                + 新增后端
              </button>
            </div>

            <div className="divide-y divide-gray-50">
              {modelConfigs.configs.map(config => (
                <div key={config.id} className="px-5 py-4 flex items-center gap-4">
                  <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-medium text-gray-900 text-sm">{config.name}</span>
                        <span
                          className={`text-xs px-1.5 py-0.5 rounded ${
                            BUILTIN_VISION_IDS.has(config.id) || config.enabled
                              ? 'bg-green-100 text-green-700'
                              : 'bg-gray-100 text-gray-500'
                          }`}
                        >
                          {BUILTIN_VISION_IDS.has(config.id) ? '启用' : config.enabled ? '启用' : '禁用'}
                        </span>
                        {BUILTIN_VISION_IDS.has(config.id) && (
                          <span
                            className={`text-xs px-1.5 py-0.5 rounded ${
                              liveForBuiltin(config.id) === 'online'
                                ? 'bg-emerald-50 text-emerald-700'
                                : liveForBuiltin(config.id) === 'offline'
                                  ? 'bg-red-50 text-red-600'
                                  : 'bg-gray-100 text-gray-500'
                            }`}
                          >
                            {builtinLive === null
                              ? '检测中…'
                              : liveForBuiltin(config.id) === 'online'
                                ? '在线'
                                : liveForBuiltin(config.id) === 'offline'
                                  ? '离线'
                                  : '—'}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 mt-1 flex-wrap">
                        <span className="text-2xs text-gray-600 border border-gray-200 rounded px-1.5 py-0.5 bg-gray-50">
                          {getProviderLabel(config.provider)}
                        </span>
                        <span className="text-xs text-gray-300">|</span>
                        <span className="text-xs text-gray-400 font-mono">{config.model_name}</span>
                        {config.base_url && (
                          <>
                            <span className="text-xs text-gray-300">|</span>
                            <span className="text-xs text-gray-400 truncate max-w-[200px]">{config.base_url}</span>
                          </>
                        )}
                      </div>
                      {config.description && (
                        <p className="text-xs text-gray-500 mt-1 line-clamp-1">{config.description}</p>
                      )}
                  </div>
                  
                  <div className="flex items-center gap-2">
                    {/* 测试按钮 */}
                    <button
                      onClick={() => testModelConfig(config.id)}
                      disabled={testingModelId === config.id}
                      className={`px-2 py-1 text-xs rounded ${
                        testingModelId === config.id 
                          ? 'bg-gray-100 text-gray-400' 
                          : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                      }`}
                    >
                      {testingModelId === config.id ? '测试中...' : '测试'}
                    </button>
                    
                    {/* 编辑按钮 */}
                    <button
                      onClick={() => startEditModel(config)}
                      className="p-1 text-gray-400 hover:text-gray-600"
                      title="编辑"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                      </svg>
                    </button>
                    
                    {/* 删除按钮（内置后端不可删） */}
                    <button
                      onClick={() => deleteModelConfig(config.id)}
                      disabled={BUILTIN_VISION_IDS.has(config.id)}
                      className={`p-1 ${
                        BUILTIN_VISION_IDS.has(config.id)
                          ? 'text-gray-200 cursor-not-allowed'
                          : 'text-gray-400 hover:text-red-500'
                      }`}
                      title={BUILTIN_VISION_IDS.has(config.id) ? '内置视觉后端不可删除' : '删除'}
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                </div>
              ))}
              {modelConfigs.configs.length === 0 && (
                <p className="px-5 py-6 text-sm text-gray-400 text-center">暂无推理后端配置</p>
              )}
            </div>

            {testResult && (
              <div className={`mx-5 mb-4 p-3 rounded-lg text-sm border ${testResult.success ? 'bg-green-50 text-green-800 border-green-100' : 'bg-red-50 text-red-800 border-red-100'}`}>
                {testResult.success ? '✓ ' : '✗ '}
                {testResult.message}
              </div>
            )}
          </div>

          <div className="flex justify-end">
            <button
              type="button"
              onClick={resetModelConfigs}
              className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 border border-gray-200 rounded-lg hover:bg-gray-50"
            >
              重置为默认配置
            </button>
          </div>
        </div>
      )}

      {/* 新增/编辑模型配置弹窗 */}
      {showAddModelModal && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center overflow-auto py-8">
          <div className="bg-white rounded-xl w-full max-w-lg p-6 mx-4">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">
              {editingModelId ? '编辑推理后端' : '新增推理后端'}
            </h3>
            <div className="space-y-4 max-h-[60vh] overflow-auto">
              {/* 基本信息 */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">显示名称 *</label>
                <input
                  type="text"
                  value={modelForm.name || ''}
                  onChange={e => setModelForm({ ...modelForm, name: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg"
                  placeholder="如：HaS Image 本机 8081"
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">类型 *</label>
                <select
                  value={modelForm.provider || 'local'}
                  onChange={e => setModelForm({ ...modelForm, provider: e.target.value as ModelConfig['provider'] })}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg"
                >
                  <option value="local">本地 HTTP（HaS Image /health）</option>
                  <option value="openai">OpenAI 兼容（/v1/models）</option>
                  <option value="custom">自定义 HTTP</option>
                </select>
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">标识名 *</label>
                <input
                  type="text"
                  value={modelForm.model_name || ''}
                  onChange={e => setModelForm({ ...modelForm, model_name: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg font-mono text-sm"
                  placeholder={modelForm.provider === 'local' ? 'HaS-Image-YOLO11' : 'gpt-4-vision-preview'}
                />
              </div>
              
              {/* API 配置 */}
              {(modelForm.provider === 'local' || modelForm.provider === 'openai' || modelForm.provider === 'custom') && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">服务基址（无尾斜杠）</label>
                  <input
                    type="text"
                    value={modelForm.base_url || ''}
                    onChange={e => setModelForm({ ...modelForm, base_url: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-200 rounded-lg font-mono text-sm"
                    placeholder={modelForm.provider === 'local' ? 'http://127.0.0.1:8081' : 'https://api.openai.com'}
                  />
                </div>
              )}
              
              {(modelForm.provider === 'openai' || modelForm.provider === 'custom') && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">API Key（可选）</label>
                  <input
                    type="password"
                    value={modelForm.api_key || ''}
                    onChange={e => setModelForm({ ...modelForm, api_key: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-200 rounded-lg font-mono text-sm"
                    placeholder="sk-..."
                  />
                  <p className="text-xs text-gray-400 mt-1">
                    {modelForm.provider === 'openai' && '在 platform.openai.com 获取 API Key'}
                  </p>
                </div>
              )}
              
              {/* 生成参数 */}
              <div className="border-t pt-4 mt-4">
                <h4 className="text-sm font-medium text-gray-700 mb-3">扩展字段（HaS Image 不使用，可保留默认）</h4>
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Temperature</label>
                    <input
                      type="number"
                      step="0.1"
                      min="0"
                      max="2"
                      value={modelForm.temperature ?? 0.8}
                      onChange={e => setModelForm({ ...modelForm, temperature: parseFloat(e.target.value) })}
                      className="w-full px-2 py-1.5 border border-gray-200 rounded text-sm"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Top P</label>
                    <input
                      type="number"
                      step="0.1"
                      min="0"
                      max="1"
                      value={modelForm.top_p ?? 0.6}
                      onChange={e => setModelForm({ ...modelForm, top_p: parseFloat(e.target.value) })}
                      className="w-full px-2 py-1.5 border border-gray-200 rounded text-sm"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Max Tokens</label>
                    <input
                      type="number"
                      step="256"
                      min="1"
                      max="32768"
                      value={modelForm.max_tokens ?? 4096}
                      onChange={e => setModelForm({ ...modelForm, max_tokens: parseInt(e.target.value) })}
                      className="w-full px-2 py-1.5 border border-gray-200 rounded text-sm"
                    />
                  </div>
                </div>
              </div>
              
              {/* 启用状态（内置视觉后端始终启用） */}
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="enabled"
                  disabled={Boolean(editingModelId && BUILTIN_VISION_IDS.has(editingModelId))}
                  checked={editingModelId && BUILTIN_VISION_IDS.has(editingModelId) ? true : (modelForm.enabled ?? true)}
                  onChange={e => setModelForm({ ...modelForm, enabled: e.target.checked })}
                  className={`${formCheckboxClass('md')} disabled:opacity-50`}
                />
                <label htmlFor="enabled" className="text-sm text-gray-700">
                  启用此配置
                  {editingModelId && BUILTIN_VISION_IDS.has(editingModelId) && (
                    <span className="text-gray-400">（内置 PaddleOCR / HaS Image 固定为启用）</span>
                  )}
                </label>
              </div>
              
              {/* 描述 */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">备注说明</label>
                <textarea
                  value={modelForm.description || ''}
                  onChange={e => setModelForm({ ...modelForm, description: e.target.value })}
                  rows={2}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm"
                  placeholder="可选，描述此配置的用途"
                />
              </div>
            </div>
            
            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => {
                  setShowAddModelModal(false);
                  setEditingModelId(null);
                }}
                className="px-4 py-2 text-sm text-gray-600"
              >
                取消
              </button>
              <button
                onClick={saveModelConfig}
                disabled={!modelForm.name || !modelForm.model_name}
                className="px-4 py-2 text-sm text-white bg-[#0a0a0a] rounded-lg hover:bg-[#262626] disabled:opacity-50"
              >
                {editingModelId ? '保存' : '创建'}
              </button>
            </div>
          </div>
        </div>
      )}
      </div>
    </div>
  );
};

export default VisionModelSettings;
