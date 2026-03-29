import { useState, useEffect } from 'react';

const STEPS = [
  {
    title: '欢迎使用 DataShield 智能脱敏平台',
    description: '本平台支持 Word、PDF、图片等多格式文档的敏感信息自动识别与脱敏处理，所有处理均在本地完成，数据不会上传到云端。',
  },
  {
    title: '上传文档',
    description: '在 Playground 页面拖拽或点击上传文件，支持 .docx、.pdf、.jpg、.png 等格式。',
  },
  {
    title: '智能识别',
    description: '系统自动识别文档中的姓名、身份证号、电话、地址等 77+ 类敏感信息，支持 NER 模型识别和正则匹配双引擎。',
  },
  {
    title: '编辑与脱敏',
    description: '您可以手动调整识别结果、添加或删除标记，然后选择智能替换、掩码、自定义等模式执行脱敏。',
  },
  {
    title: '批量处理',
    description: '使用「批量任务」功能可以一次处理多个文件，支持文本批量和图像批量两种模式。',
  },
];

export function OnboardingGuide() {
  const [show, setShow] = useState(false);
  const [step, setStep] = useState(0);

  useEffect(() => {
    const done = localStorage.getItem('onboarding_completed');
    if (!done) setShow(true);
  }, []);

  const finish = () => {
    localStorage.setItem('onboarding_completed', 'true');
    setShow(false);
  };

  if (!show) return null;

  const current = STEPS[step];
  const isLast = step === STEPS.length - 1;

  return (
    <div className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-white dark:bg-[#1e1e1e] rounded-2xl shadow-2xl max-w-md w-full mx-4 overflow-hidden border border-transparent dark:border-white/10">
        {/* Progress bar */}
        <div className="h-1 bg-gray-100 dark:bg-white/5">
          <div
            className="h-full bg-[#1d1d1f] dark:bg-white/70 transition-all duration-300"
            style={{ width: `${((step + 1) / STEPS.length) * 100}%` }}
          />
        </div>

        <div className="p-6">
          <div className="text-xs text-gray-400 mb-2">{step + 1} / {STEPS.length}</div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">{current.title}</h2>
          <p className="text-sm text-gray-600 dark:text-gray-300 leading-relaxed">{current.description}</p>
        </div>

        <div className="px-6 pb-6 flex justify-between items-center">
          <button
            onClick={finish}
            className="text-sm text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
          >
            跳过引导
          </button>
          <div className="flex gap-2">
            {step > 0 && (
              <button
                onClick={() => setStep(s => s - 1)}
                className="px-4 py-2 text-sm border border-gray-200 dark:border-white/10 rounded-lg hover:bg-gray-50 dark:hover:bg-white/5 dark:text-gray-100"
              >
                上一步
              </button>
            )}
            <button
              onClick={isLast ? finish : () => setStep(s => s + 1)}
              className="px-4 py-2 text-sm bg-[#1d1d1f] text-white rounded-lg hover:bg-[#2a2a2a] dark:bg-[#3d3d3d] dark:hover:bg-[#4a4a4a] border border-transparent dark:border-white/10"
            >
              {isLast ? '开始使用' : '下一步'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
