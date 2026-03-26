import React, { useState, useEffect, useCallback } from 'react';
import { fetchWithTimeout } from '../utils/fetchWithTimeout';

/** 仅 HaS（llama-server）；保存时仍附带后端兼容用的占位字段 */
const OLLAMA_PLACEHOLDER = {
  ollama_base_url: 'http://127.0.0.1:11434/v1',
  ollama_model: 'qwen3:8b',
};

/**
 * 文本模型配置：版式与「视觉服务配置」对齐（说明卡 + 推理后端白卡片 + 列表行 + 底部重置）
 */
export const TextModelSettings: React.FC = () => {
  const [llamacppBaseUrl, setLlamacppBaseUrl] = useState('http://127.0.0.1:8080/v1');
  const [nerLoading, setNerLoading] = useState(true);
  const [nerSaving, setNerSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  /** 与 /health/services 中 has_ner 对齐 */
  const [nerLive, setNerLive] = useState<'online' | 'offline' | undefined>(undefined);

  const fetchNerBackend = useCallback(async () => {
    try {
      setNerLoading(true);
      const res = await fetchWithTimeout('/api/v1/ner-backend', { timeoutMs: 25000 });
      if (!res.ok) throw new Error('获取失败');
      const data = await res.json();
      setLlamacppBaseUrl(data.llamacpp_base_url || 'http://127.0.0.1:8080/v1');
    } catch (e) {
      console.error('获取文本 NER 配置失败', e);
    } finally {
      setNerLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchNerBackend();
  }, [fetchNerBackend]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch('/health/services');
        if (!res.ok || cancelled) return;
        const d = await res.json();
        const st = d.services?.has_ner?.status;
        if (st === 'online' || st === 'offline') setNerLive(st);
        else setNerLive(undefined);
      } catch {
        if (!cancelled) setNerLive(undefined);
      }
    };
    void load();
    const t = setInterval(load, 15000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  const payload = useCallback(
    () => ({
      backend: 'llamacpp' as const,
      llamacpp_base_url: llamacppBaseUrl,
      ...OLLAMA_PLACEHOLDER,
    }),
    [llamacppBaseUrl]
  );

  const saveNerBackend = async () => {
    try {
      setNerSaving(true);
      setTestResult(null);
      const res = await fetch('/api/v1/ner-backend', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload()),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        alert((d as { detail?: string }).detail || '保存失败');
        return;
      }
      setTestResult({ success: true, message: '配置已保存并生效。' });
    } catch (e) {
      console.error(e);
      alert('保存失败');
    } finally {
      setNerSaving(false);
    }
  };

  const testConnection = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await fetch('/api/v1/ner-backend/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload()),
      });
      let data: { success?: boolean; message?: string; detail?: unknown } = {};
      try {
        data = await res.json();
      } catch {
        setTestResult({
          success: false,
          message: `HTTP ${res.status}：响应不是 JSON（请确认后端已启动）`,
        });
        return;
      }
      if (!res.ok) {
        const d = data.detail;
        let errMsg = `请求失败 (${res.status})`;
        if (Array.isArray(d)) {
          errMsg = d.map((x: { msg?: string }) => x.msg || JSON.stringify(x)).join('；');
        } else if (typeof d === 'string') {
          errMsg = d;
        } else if (d && typeof d === 'object' && 'msg' in (d as object)) {
          errMsg = String((d as { msg: string }).msg);
        }
        setTestResult({ success: false, message: errMsg });
        return;
      }
      setTestResult({
        success: Boolean(data.success),
        message:
          data.message ||
          (data.success ? '连接成功' : '连接失败（请查看后端日志或保存配置后重试）'),
      });
    } catch {
      setTestResult({ success: false, message: '测试请求失败（网络或跨域）' });
    } finally {
      setTimeout(() => setTesting(false), 300);
    }
  };

  const clearNerOverride = async () => {
    if (!confirm('确定清除前端保存的配置，恢复为服务器环境变量默认值？')) return;
    try {
      const res = await fetch('/api/v1/ner-backend', { method: 'DELETE' });
      if (res.ok) {
        await fetchNerBackend();
        setTestResult({ success: true, message: '已恢复为环境变量默认。' });
      }
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="h-full min-h-0 min-w-0 flex flex-col overflow-hidden bg-[#fafafa]">
      <div className="flex-1 min-h-0 overflow-auto overscroll-contain p-4 sm:p-6 w-full max-w-5xl mx-auto">
        {nerLoading ? (
          <div className="flex items-center justify-center py-24">
            <div className="w-7 h-7 border-2 border-[#e5e5e5] border-t-[#0a0a0a] rounded-full animate-spin" />
          </div>
        ) : (
          <div className="flex flex-col gap-5">
            <section className="rounded-xl border border-gray-200/90 bg-gray-50/90 p-5">
              <h3 className="text-sm font-semibold text-gray-900">文本 NER 推理</h3>
              <p className="text-xs text-gray-600 leading-relaxed mt-2">
                <strong className="font-medium text-gray-800">HaS</strong> 通过{' '}
                <strong className="font-medium text-gray-800">llama-server</strong> 提供 OpenAI 兼容{' '}
                <code className="text-2xs bg-white px-1 py-0.5 rounded border border-gray-200/90">/v1</code>
                。保存后写入{' '}
                <code className="text-2xs bg-white px-1 py-0.5 rounded border border-gray-200/90">data/ner_backend.json</code>
                ，优先级高于环境变量，<strong className="font-medium">无需重启</strong>后端。侧栏「HaS」离线时多为本机未启动对应进程；可运行{' '}
                <code className="text-2xs bg-white px-1 py-0.5 rounded border border-gray-200/90">scripts/start_has.bat</code>
                。下方「测试」使用当前输入框地址，无需先保存。
              </p>
              <div className="flex flex-wrap gap-2 mt-4 pt-4 border-t border-gray-200/80">
                <span className="text-xs text-gray-700 px-2 py-1 rounded-md bg-white border border-gray-200/90">
                  OpenAI 兼容
                </span>
                <span className="text-xs text-gray-700 px-2 py-1 rounded-md bg-white border border-gray-200/90">
                  本地 HTTP
                </span>
                <span className="text-xs text-gray-700 px-2 py-1 rounded-md bg-white border border-gray-200/90">
                  llama-server
                </span>
              </div>
            </section>

            <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
              <div className="px-5 py-4 border-b border-gray-100 flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
                <div>
                  <h2 className="text-base font-semibold text-gray-900">推理后端</h2>
                  <p className="text-xs text-gray-500 mt-1 leading-relaxed">
                    当前仅支持 HaS 文本 NER；配置 OpenAI 兼容根路径后，点「保存配置」写入运行时文件。
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void saveNerBackend()}
                  disabled={nerSaving}
                  className="px-3 py-1.5 text-xs rounded-lg bg-[#0a0a0a] text-white hover:bg-[#262626] disabled:opacity-50 shrink-0"
                >
                  {nerSaving ? '保存中…' : '保存配置'}
                </button>
              </div>

              <div className="divide-y divide-gray-50">
                <div className="px-5 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-medium text-gray-900 text-sm">HaS 文本 NER</span>
                        <span className="text-xs px-1.5 py-0.5 rounded bg-green-100 text-green-700">启用</span>
                        <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">内置</span>
                        {nerLive === undefined ? (
                          <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">检测中…</span>
                        ) : nerLive === 'online' ? (
                          <span className="text-xs px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700">在线</span>
                        ) : (
                          <span className="text-xs px-1.5 py-0.5 rounded bg-red-50 text-red-600">离线</span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 mt-1 flex-wrap">
                        <span className="text-2xs text-gray-600 border border-gray-200 rounded px-1.5 py-0.5 bg-gray-50">
                          OpenAI 兼容
                        </span>
                        <span className="text-xs text-gray-300">|</span>
                        <span className="text-xs text-gray-400 font-mono truncate max-w-[min(100%,28rem)]">
                          {llamacppBaseUrl || '—'}
                        </span>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => void testConnection()}
                      disabled={testing}
                      className={`px-2 py-1 text-xs rounded shrink-0 ${
                        testing ? 'bg-gray-100 text-gray-400' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                      }`}
                    >
                      {testing ? '测试中...' : '测试'}
                    </button>
                  </div>

                  <div className="mt-3">
                    <label className="block text-xs font-medium text-gray-700 mb-1.5">OpenAI 兼容 API 根路径</label>
                    <input
                      type="text"
                      value={llamacppBaseUrl}
                      onChange={e => setLlamacppBaseUrl(e.target.value)}
                      className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg font-mono focus:outline-none focus:ring-2 focus:ring-gray-400/25 focus:border-gray-300"
                      placeholder="http://127.0.0.1:8080/v1"
                    />
                    <p className="text-xs text-gray-500 mt-1.5 leading-relaxed">
                      测试会依次尝试 <code className="text-2xs bg-gray-50 px-1 rounded border border-gray-100">GET …/v1/models</code>、
                      <code className="text-2xs bg-gray-50 px-1 rounded border border-gray-100">…/v1/health</code> 等路径。
                    </p>
                  </div>
                </div>
              </div>

              {testResult && (
                <div
                  className={`mx-5 mb-4 p-3 rounded-lg text-sm border ${
                    testResult.success
                      ? 'bg-green-50 text-green-800 border-green-100'
                      : 'bg-red-50 text-red-800 border-red-100'
                  }`}
                >
                  {testResult.success ? '✓ ' : '✗ '}
                  {testResult.message}
                </div>
              )}
            </div>

            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => void clearNerOverride()}
                className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 border border-gray-200 rounded-lg hover:bg-gray-50"
              >
                恢复环境变量默认
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default TextModelSettings;
