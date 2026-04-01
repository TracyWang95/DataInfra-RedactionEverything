import React from 'react';
import { useRedactionConfigStore } from '../../hooks/useRedaction';
import { EntityType, ReplacementMode, IdentifierCategory } from '../../types';
import { Switch } from '@headlessui/react';
import clsx from 'clsx';

/**
 * 实体类型配置 - 基于 GB/T 37964-2019《信息安全技术 个人信息去标识化指南》
 * 
 * 分类说明：
 * - direct: 直接标识符 - 能够单独识别个人
 * - quasi: 准标识符 - 与其他信息结合可识别个人
 * - sensitive: 敏感属性 - 涉及敏感信息
 */
const ENTITY_TYPE_CONFIG = [
  // === 直接标识符 (Direct Identifiers) ===
  { 
    type: EntityType.PERSON, 
    label: '姓名', 
    description: '自然人姓名',
    category: IdentifierCategory.DIRECT,
    riskLevel: 5,
  },
  { 
    type: EntityType.ID_CARD, 
    label: '身份证号', 
    description: '18位身份证',
    category: IdentifierCategory.DIRECT,
    riskLevel: 5,
  },
  { 
    type: EntityType.PASSPORT, 
    label: '护照号', 
    description: '护照号码',
    category: IdentifierCategory.DIRECT,
    riskLevel: 5,
  },
  { 
    type: EntityType.PHONE, 
    label: '电话号码', 
    description: '手机号/座机',
    category: IdentifierCategory.DIRECT,
    riskLevel: 5,
  },
  { 
    type: EntityType.EMAIL, 
    label: '电子邮箱', 
    description: '电子邮件地址',
    category: IdentifierCategory.DIRECT,
    riskLevel: 4,
  },
  { 
    type: EntityType.BANK_CARD, 
    label: '银行卡号', 
    description: '银行卡账号',
    category: IdentifierCategory.DIRECT,
    riskLevel: 5,
  },
  { 
    type: EntityType.LEGAL_PARTY, 
    label: '案件当事人', 
    description: '原告/被告等',
    category: IdentifierCategory.DIRECT,
    riskLevel: 5,
  },
  { 
    type: EntityType.LAWYER, 
    label: '律师/代理人', 
    description: '律师姓名',
    category: IdentifierCategory.DIRECT,
    riskLevel: 4,
  },
  { 
    type: EntityType.JUDGE, 
    label: '法官/书记员', 
    description: '司法人员',
    category: IdentifierCategory.DIRECT,
    riskLevel: 4,
  },
  { 
    type: EntityType.WITNESS, 
    label: '证人', 
    description: '证人姓名',
    category: IdentifierCategory.DIRECT,
    riskLevel: 4,
  },
  
  // === 准标识符 (Quasi-Identifiers) ===
  { 
    type: EntityType.ADDRESS, 
    label: '详细地址', 
    description: '完整地址信息',
    category: IdentifierCategory.QUASI,
    riskLevel: 4,
  },
  { 
    type: EntityType.BIRTH_DATE, 
    label: '出生日期', 
    description: '出生年月日',
    category: IdentifierCategory.QUASI,
    riskLevel: 3,
  },
  { 
    type: EntityType.DATE, 
    label: '日期', 
    description: '事件日期',
    category: IdentifierCategory.QUASI,
    riskLevel: 2,
  },
  { 
    type: EntityType.LICENSE_PLATE, 
    label: '车牌号', 
    description: '机动车号牌',
    category: IdentifierCategory.QUASI,
    riskLevel: 3,
  },
  { 
    type: EntityType.CASE_NUMBER, 
    label: '案件编号', 
    description: '法院案号',
    category: IdentifierCategory.QUASI,
    riskLevel: 3,
  },
  { 
    type: EntityType.CONTRACT_NO, 
    label: '合同编号', 
    description: '合同协议号',
    category: IdentifierCategory.QUASI,
    riskLevel: 2,
  },
  { 
    type: EntityType.ORG, 
    label: '机构名称', 
    description: '公司/单位名',
    category: IdentifierCategory.QUASI,
    riskLevel: 3,
  },
  
  // === 敏感属性 (Sensitive Attributes) ===
  { 
    type: EntityType.AMOUNT, 
    label: '金额', 
    description: '财务金额',
    category: IdentifierCategory.SENSITIVE,
    riskLevel: 3,
  },
  { 
    type: EntityType.HEALTH_INFO, 
    label: '健康信息', 
    description: '疾病/病历',
    category: IdentifierCategory.SENSITIVE,
    riskLevel: 4,
  },
  { 
    type: EntityType.CRIMINAL_RECORD, 
    label: '犯罪记录', 
    description: '违法犯罪信息',
    category: IdentifierCategory.SENSITIVE,
    riskLevel: 5,
  },
];

// 分类标签配置
const CATEGORY_CONFIG = {
  [IdentifierCategory.DIRECT]: { 
    label: '直接标识符', 
    color: 'text-red-700', 
    bgColor: 'bg-red-50',
    description: '能够单独识别个人',
  },
  [IdentifierCategory.QUASI]: { 
    label: '准标识符', 
    color: 'text-amber-700', 
    bgColor: 'bg-amber-50',
    description: '与其他信息结合可识别',
  },
  [IdentifierCategory.SENSITIVE]: { 
    label: '敏感属性', 
    color: 'text-purple-700', 
    bgColor: 'bg-purple-50',
    description: '涉及敏感信息',
  },
};

const REPLACEMENT_MODES = [
  {
    value: ReplacementMode.SMART,
    label: '智能替换',
    description: '替换为语义化标识，如"当事人甲"、"公司A"',
    preview: '张三 → [当事人一]',
  },
  {
    value: ReplacementMode.STRUCTURED,
    label: '结构化语义标签',
    description: '替换为结构化标签，保留层级语义与指代关系',
    preview: '张三 → <人物[001].个人.姓名>',
  },
  {
    value: ReplacementMode.MASK,
    label: '掩码替换',
    description: '用 *** 或部分隐藏，如"张**"、"138****1234"',
    preview: '张三 → 张** · 13800138000 → 138****8000',
  },
  {
    value: ReplacementMode.CUSTOM,
    label: '自定义替换',
    description: '手动指定每个敏感信息的替换文本',
    preview: '用户指定每项的替换文本',
  },
];

export const ConfigPanel: React.FC = () => {
  const { config, toggleEntityType, setReplacementMode } = useRedactionConfigStore();

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg border border-line dark:border-gray-700 overflow-hidden" role="form" aria-label="脱敏配置">
      {/* 头部 */}
      <div className="p-4 border-b border-line">
        <h3 className="text-lg font-semibold text-ink" id="config-panel-title">脱敏配置</h3>
        <p className="text-sm text-ink-muted mt-1">配置要识别的实体类型和替换方式</p>
      </div>

      {/* 替换模式 */}
      <div className="p-4 border-b border-line">
        <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3" id="replacement-mode-label">替换模式</h4>
        <div className="space-y-2" role="radiogroup" aria-labelledby="replacement-mode-label">
          {REPLACEMENT_MODES.map((mode) => (
            <label
              key={mode.value}
              className={clsx(
                'flex items-start gap-3 p-3 rounded-lg border-2 cursor-pointer transition-all',
                config.replacement_mode === mode.value
                  ? 'border-primary-500 bg-primary-50'
                  : 'border-line dark:border-gray-600 hover:border-gray-300 dark:hover:border-gray-500'
              )}
            >
              <input
                type="radio"
                name="replacement_mode"
                value={mode.value}
                checked={config.replacement_mode === mode.value}
                onChange={() => setReplacementMode(mode.value)}
                className="mt-1 text-primary-600 focus:ring-primary-500"
              />
              <div>
                <p className="font-medium text-ink">{mode.label}</p>
                <p className="text-sm text-ink-muted">{mode.description}</p>
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5 font-mono">{mode.preview}</p>
              </div>
            </label>
          ))}
        </div>
      </div>

      {/* 实体类型 - 按GB/T 37964-2019分类 */}
      <div className="p-4">
        <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">识别的实体类型</h4>
        <p className="text-xs text-ink-subtle mb-3">基于 GB/T 37964-2019 分类</p>
        
        {/* 按分类显示 */}
        {Object.entries(CATEGORY_CONFIG).map(([category, categoryConfig]) => {
          const categoryItems = ENTITY_TYPE_CONFIG.filter(item => item.category === category);
          if (categoryItems.length === 0) return null;
          
          return (
            <div key={category} className="mb-4">
              {/* 分类标题 */}
              <div className={clsx('px-2 py-1 rounded-md mb-2', categoryConfig.bgColor)}>
                <p className={clsx('text-xs font-medium', categoryConfig.color)}>
                  {categoryConfig.label}
                  <span className="font-normal ml-1">- {categoryConfig.description}</span>
                </p>
              </div>
              
              {/* 该分类下的实体类型 */}
              <div className="space-y-2 pl-2">
                {categoryItems.map((item) => (
                  <div key={item.type} className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div>
                        <p className="text-sm font-medium text-ink">{item.label}</p>
                        <p className="text-xs text-ink-muted">{item.description}</p>
                      </div>
                      {/* 风险等级指示 */}
                      <span className={clsx(
                        'text-xs px-1.5 py-0.5 rounded',
                        item.riskLevel >= 5 ? 'bg-red-100 text-red-700' :
                        item.riskLevel >= 4 ? 'bg-orange-100 text-orange-700' :
                        item.riskLevel >= 3 ? 'bg-yellow-100 text-yellow-700' :
                        'bg-surface-tertiary text-ink-muted'
                      )}>
                        L{item.riskLevel}
                      </span>
                    </div>
                    <Switch
                      checked={config.entity_types.includes(item.type)}
                      onChange={() => toggleEntityType(item.type)}
                      className={clsx(
                        'relative inline-flex h-6 w-11 items-center rounded-full transition-colors',
                        config.entity_types.includes(item.type)
                          ? 'bg-primary-600'
                          : 'bg-neutral-200'
                      )}
                    >
                      <span
                        className={clsx(
                          'inline-block h-4 w-4 transform rounded-full bg-white transition-transform',
                          config.entity_types.includes(item.type)
                            ? 'translate-x-6'
                            : 'translate-x-1'
                        )}
                      />
                    </Switch>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default ConfigPanel;
