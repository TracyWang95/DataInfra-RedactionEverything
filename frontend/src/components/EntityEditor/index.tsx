import React, { useState } from 'react';
import { useEntityStore, useEntityStats } from '../../hooks/useRedaction';
import type { Entity } from '../../types';
import {
  CheckIcon,
  XMarkIcon,
  PencilIcon,
  PlusIcon,
  FunnelIcon,
} from '@heroicons/react/24/outline';
import clsx from 'clsx';

/**
 * 实体类型配置 - 基于 GB/T 37964-2019《信息安全技术 个人信息去标识化指南》
 * 
 * 颜色编码：
 * - 红色系: 直接标识符 (高风险)
 * - 橙色/琥珀色系: 准标识符 (中风险)
 * - 紫色系: 敏感属性
 */
const ENTITY_TYPE_CONFIG: Record<string, { label: string; color: string; bgColor: string; category?: string }> = {
  // === 直接标识符 (Direct Identifiers) - 红色系 ===
  PERSON: { label: '姓名', color: 'text-blue-700', bgColor: 'bg-blue-100', category: 'direct' },
  ID_CARD: { label: '身份证', color: 'text-red-700', bgColor: 'bg-red-100', category: 'direct' },
  PASSPORT: { label: '护照号', color: 'text-red-600', bgColor: 'bg-red-50', category: 'direct' },
  SOCIAL_SECURITY: { label: '社保号', color: 'text-rose-700', bgColor: 'bg-rose-100', category: 'direct' },
  DRIVER_LICENSE: { label: '驾驶证', color: 'text-rose-600', bgColor: 'bg-rose-50', category: 'direct' },
  PHONE: { label: '电话', color: 'text-orange-700', bgColor: 'bg-orange-100', category: 'direct' },
  EMAIL: { label: '邮箱', color: 'text-cyan-700', bgColor: 'bg-cyan-100', category: 'direct' },
  BANK_CARD: { label: '银行卡', color: 'text-pink-700', bgColor: 'bg-pink-100', category: 'direct' },
  BANK_ACCOUNT: { label: '银行账号', color: 'text-pink-600', bgColor: 'bg-pink-50', category: 'direct' },
  WECHAT_ALIPAY: { label: '支付账号', color: 'text-fuchsia-700', bgColor: 'bg-fuchsia-100', category: 'direct' },
  IP_ADDRESS: { label: 'IP地址', color: 'text-violet-700', bgColor: 'bg-violet-100', category: 'direct' },
  MAC_ADDRESS: { label: 'MAC地址', color: 'text-violet-600', bgColor: 'bg-violet-50', category: 'direct' },
  DEVICE_ID: { label: '设备ID', color: 'text-purple-700', bgColor: 'bg-purple-100', category: 'direct' },
  BIOMETRIC: { label: '生物特征', color: 'text-purple-800', bgColor: 'bg-purple-200', category: 'direct' },
  LEGAL_PARTY: { label: '当事人', color: 'text-amber-700', bgColor: 'bg-amber-100', category: 'direct' },
  LAWYER: { label: '律师', color: 'text-purple-600', bgColor: 'bg-purple-50', category: 'direct' },
  JUDGE: { label: '法官', color: 'text-sky-700', bgColor: 'bg-sky-100', category: 'direct' },
  WITNESS: { label: '证人', color: 'text-stone-700', bgColor: 'bg-stone-100', category: 'direct' },
  
  // === 准标识符 (Quasi-Identifiers) - 琥珀/黄色系 ===
  BIRTH_DATE: { label: '出生日期', color: 'text-lime-700', bgColor: 'bg-lime-100', category: 'quasi' },
  AGE: { label: '年龄', color: 'text-lime-600', bgColor: 'bg-lime-50', category: 'quasi' },
  GENDER: { label: '性别', color: 'text-green-600', bgColor: 'bg-green-50', category: 'quasi' },
  NATIONALITY: { label: '国籍', color: 'text-green-700', bgColor: 'bg-green-100', category: 'quasi' },
  ADDRESS: { label: '地址', color: 'text-indigo-700', bgColor: 'bg-indigo-100', category: 'quasi' },
  POSTAL_CODE: { label: '邮编', color: 'text-indigo-600', bgColor: 'bg-indigo-50', category: 'quasi' },
  GPS_LOCATION: { label: 'GPS坐标', color: 'text-blue-600', bgColor: 'bg-blue-50', category: 'quasi' },
  OCCUPATION: { label: '职业', color: 'text-pink-600', bgColor: 'bg-pink-50', category: 'quasi' },
  EDUCATION: { label: '学历', color: 'text-pink-500', bgColor: 'bg-pink-50', category: 'quasi' },
  WORK_UNIT: { label: '工作单位', color: 'text-fuchsia-600', bgColor: 'bg-fuchsia-50', category: 'quasi' },
  DATE: { label: '日期', color: 'text-cyan-600', bgColor: 'bg-cyan-100', category: 'quasi' },
  TIME: { label: '时间', color: 'text-cyan-500', bgColor: 'bg-cyan-50', category: 'quasi' },
  LICENSE_PLATE: { label: '车牌', color: 'text-teal-700', bgColor: 'bg-teal-100', category: 'quasi' },
  VIN: { label: '车架号', color: 'text-teal-600', bgColor: 'bg-teal-50', category: 'quasi' },
  CASE_NUMBER: { label: '案号', color: 'text-violet-700', bgColor: 'bg-violet-100', category: 'quasi' },
  CONTRACT_NO: { label: '合同号', color: 'text-slate-700', bgColor: 'bg-slate-100', category: 'quasi' },
  ORG: { label: '机构', color: 'text-emerald-700', bgColor: 'bg-emerald-100', category: 'quasi' },
  COMPANY_CODE: { label: '信用代码', color: 'text-emerald-600', bgColor: 'bg-emerald-50', category: 'quasi' },
  
  // === 敏感属性 (Sensitive Attributes) - 紫色系 ===
  HEALTH_INFO: { label: '健康信息', color: 'text-red-600', bgColor: 'bg-red-100', category: 'sensitive' },
  MEDICAL_RECORD: { label: '病历号', color: 'text-red-500', bgColor: 'bg-red-50', category: 'sensitive' },
  AMOUNT: { label: '金额', color: 'text-rose-700', bgColor: 'bg-rose-100', category: 'sensitive' },
  PROPERTY: { label: '财产', color: 'text-rose-600', bgColor: 'bg-rose-50', category: 'sensitive' },
  CRIMINAL_RECORD: { label: '犯罪记录', color: 'text-red-800', bgColor: 'bg-red-200', category: 'sensitive' },
  POLITICAL: { label: '政治面貌', color: 'text-amber-800', bgColor: 'bg-amber-100', category: 'sensitive' },
  RELIGION: { label: '宗教信仰', color: 'text-amber-700', bgColor: 'bg-amber-50', category: 'sensitive' },
  
  // === 其他/兼容旧版本 ===
  MONEY: { label: '金额', color: 'text-rose-700', bgColor: 'bg-rose-100', category: 'sensitive' },  // 兼容旧版
  CUSTOM: { label: '自定义', color: 'text-gray-700', bgColor: 'bg-surface-tertiary' },
};

export const EntityEditor: React.FC = () => {
  const {
    entities,
    toggleEntitySelection,
    selectAllEntities,
    deselectAllEntities,
    updateEntity,
  } = useEntityStore();

  const stats = useEntityStats();
  const [filterType, setFilterType] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');

  // 过滤后的实体列表
  const filteredEntities = filterType
    ? entities.filter((e) => e.type === filterType)
    : entities;

  // 按类型分组
  const groupedByType = entities.reduce((acc, entity) => {
    const type = entity.type;
    if (!acc[type]) acc[type] = [];
    acc[type].push(entity);
    return acc;
  }, {} as Record<string, Entity[]>);

  const handleEditStart = (entity: Entity) => {
    setEditingId(entity.id);
    setEditValue(entity.replacement || entity.text);
  };

  const handleEditSave = (entity: Entity) => {
    updateEntity(entity.id, { replacement: editValue });
    setEditingId(null);
    setEditValue('');
  };

  const handleEditCancel = () => {
    setEditingId(null);
    setEditValue('');
  };

  return (
    <div className="h-full flex flex-col bg-white dark:bg-gray-800 rounded-lg border border-line dark:border-gray-700 overflow-hidden" role="region" aria-label="识别结果编辑器">
      {/* 头部 */}
      <div className="p-4 border-b border-line">
        <h3 className="text-lg font-semibold text-ink" id="entity-editor-title">识别结果</h3>
        <p className="text-sm text-ink-muted mt-1" aria-live="polite">
          共识别 {stats.total} 个敏感信息，已选中 {stats.selected} 个
        </p>
      </div>

      {/* 快捷操作 */}
      <div className="p-3 border-b border-line flex items-center gap-2 flex-wrap" role="toolbar" aria-label="实体操作">
        <button
          onClick={selectAllEntities}
          aria-label="全选所有实体"
          className="px-3 py-1.5 text-sm bg-primary-50 text-primary-700 rounded-md hover:bg-primary-100 transition-colors"
        >
          全选
        </button>
        <button
          onClick={deselectAllEntities}
          aria-label="取消全选"
          className="px-3 py-1.5 text-sm bg-surface-tertiary text-gray-700 rounded-md hover:bg-neutral-200 transition-colors"
        >
          取消全选
        </button>
        
        <div className="flex-1" />
        
        {/* 类型筛选 */}
        <div className="relative">
          <select
            value={filterType || ''}
            onChange={(e) => setFilterType(e.target.value || null)}
            className="appearance-none pl-8 pr-4 py-1.5 text-sm bg-surface-tertiary border-0 rounded-md focus:ring-2 focus:ring-primary-500"
          >
            <option value="">全部类型</option>
            {Object.entries(ENTITY_TYPE_CONFIG).map(([type, config]) => (
              <option key={type} value={type}>
                {config.label} ({groupedByType[type]?.length || 0})
              </option>
            ))}
          </select>
          <FunnelIcon className="absolute left-2 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-subtle" />
        </div>
      </div>

      {/* 类型统计标签 */}
      <div className="p-3 border-b border-line flex flex-wrap gap-2">
        {Object.entries(stats.byType).map(([type, count]) => {
          const config = ENTITY_TYPE_CONFIG[type] || ENTITY_TYPE_CONFIG.CUSTOM;
          return (
            <button
              key={type}
              onClick={() => setFilterType(filterType === type ? null : type)}
              className={clsx(
                'px-2 py-1 text-xs rounded-full transition-all',
                config.bgColor,
                config.color,
                filterType === type && 'ring-2 ring-offset-1 ring-current'
              )}
            >
              {config.label} ({count})
            </button>
          );
        })}
      </div>

      {/* 实体列表 */}
      <div className="flex-1 overflow-auto p-3">
        {filteredEntities.length === 0 ? (
          <div className="text-center py-8 text-ink-subtle">
            <p>暂无识别结果</p>
          </div>
        ) : (
          <div className="space-y-2">
            {filteredEntities.map((entity) => (
              <EntityItem
                key={entity.id}
                entity={entity}
                isEditing={editingId === entity.id}
                editValue={editValue}
                onToggle={() => toggleEntitySelection(entity.id)}
                onEditStart={() => handleEditStart(entity)}
                onEditChange={setEditValue}
                onEditSave={() => handleEditSave(entity)}
                onEditCancel={handleEditCancel}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

// 实体项组件
interface EntityItemProps {
  entity: Entity;
  isEditing: boolean;
  editValue: string;
  onToggle: () => void;
  onEditStart: () => void;
  onEditChange: (value: string) => void;
  onEditSave: () => void;
  onEditCancel: () => void;
}

const EntityItem: React.FC<EntityItemProps> = ({
  entity,
  isEditing,
  editValue,
  onToggle,
  onEditStart,
  onEditChange,
  onEditSave,
  onEditCancel,
}) => {
  const config = ENTITY_TYPE_CONFIG[entity.type] || ENTITY_TYPE_CONFIG.CUSTOM;

  return (
    <div
      className={clsx(
        'p-3 rounded-lg border transition-all',
        entity.selected
          ? 'bg-primary-50 border-primary-200'
          : 'bg-surface-secondary border-line'
      )}
    >
      <div className="flex items-start gap-3">
        {/* 选择框 */}
        <button
          onClick={onToggle}
          role="checkbox"
          aria-checked={entity.selected}
          aria-label={`选择 ${config.label}: ${entity.text}`}
          className={clsx(
            'w-5 h-5 rounded border-2 flex items-center justify-center flex-shrink-0 mt-0.5 transition-colors',
            entity.selected
              ? 'bg-primary-600 border-primary-600 text-white'
              : 'border-gray-300 dark:border-gray-600 hover:border-primary-400'
          )}
        >
          {entity.selected && <CheckIcon className="w-3 h-3" />}
        </button>

        {/* 内容 */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            {/* 类型标签 */}
            <span className={clsx('px-2 py-0.5 text-xs rounded-full', config.bgColor, config.color)}>
              {config.label}
            </span>
            
            {/* 置信度 */}
            {entity.confidence < 1 && (
              <span className="text-xs text-ink-subtle">
                {Math.round(entity.confidence * 100)}%
              </span>
            )}
            
            {/* 页码 */}
            {entity.page > 1 && (
              <span className="text-xs text-ink-subtle">
                第{entity.page}页
              </span>
            )}
          </div>

          {/* 原始文本 */}
          <p className="mt-1 text-sm font-medium text-ink break-all">
            {entity.text}
          </p>

          {/* 替换文本编辑 */}
          {isEditing ? (
            <div className="mt-2 flex items-center gap-2">
              <span className="text-ink-subtle">→</span>
              <input
                type="text"
                value={editValue}
                onChange={(e) => onEditChange(e.target.value)}
                className="flex-1 px-2 py-1 text-sm border border-gray-300 dark:border-gray-600 rounded focus:outline-none focus:ring-2 focus:ring-primary-500"
                placeholder="输入替换文本"
                autoFocus
              />
              <button
                onClick={onEditSave}
                className="p-1 text-green-600 hover:bg-green-50 rounded"
                aria-label="保存替换文本"
              >
                <CheckIcon className="w-4 h-4" />
              </button>
              <button
                onClick={onEditCancel}
                className="p-1 text-ink-subtle hover:bg-surface-tertiary rounded"
                aria-label="取消编辑"
              >
                <XMarkIcon className="w-4 h-4" />
              </button>
            </div>
          ) : entity.replacement ? (
            <div className="mt-1 flex items-center gap-2 text-sm">
              <span className="text-ink-subtle">→</span>
              <span className="text-primary-700 font-medium">{entity.replacement}</span>
              <button
                onClick={onEditStart}
                className="p-1 text-ink-subtle hover:text-ink-muted hover:bg-surface-tertiary rounded"
                aria-label="编辑替换文本"
              >
                <PencilIcon className="w-3 h-3" />
              </button>
            </div>
          ) : (
            <button
              onClick={onEditStart}
              className="mt-1 text-xs text-ink-subtle hover:text-primary-600 flex items-center gap-1"
            >
              <PlusIcon className="w-3 h-3" />
              自定义替换
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default EntityEditor;
