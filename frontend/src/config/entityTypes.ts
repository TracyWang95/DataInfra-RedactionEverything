// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { t } from '@/i18n';

export interface EntityTypeConfig {
  id: string;
  name: string;
  description?: string;
}

export interface EntityGroup {
  id: string;
  label: string;
  color: string;
  bgColor: string;
  textColor: string;
  types: EntityTypeConfig[];
}

export const ENTITY_PALETTE = {
  personal: { color: '#9333EA', bgColor: '#FAF5FF', textColor: '#6B21A8' },
  org: { color: '#0284C7', bgColor: '#F0F9FF', textColor: '#075985' },
  contact: { color: '#059669', bgColor: '#ECFDF5', textColor: '#065F46' },
  time: { color: '#6366F1', bgColor: '#EEF2FF', textColor: '#4338CA' },
} as const;

export const ENTITY_FALLBACK_STYLE = {
  color: '#0284C7',
  bgColor: '#F0F9FF',
  textColor: '#075985',
} as const;

function defineTypes(entries: Array<[id: string, name: string, description?: string]>): EntityTypeConfig[] {
  return entries.map(([id, name, description]) => ({ id, name, description }));
}

export const ENTITY_GROUPS: EntityGroup[] = [
  {
    id: 'identity',
    label: '个人身份',
    ...ENTITY_PALETTE.personal,
    types: defineTypes([
      ['PERSON', '姓名'],
      ['ID_CARD', '身份证号'],
      ['PASSPORT', '护照号'],
      ['SOCIAL_SECURITY', '社保号'],
      ['DRIVER_LICENSE', '驾驶证号'],
      ['MILITARY_ID', '军官证号'],
      ['BIOMETRIC', '生物特征'],
      ['USERNAME_PASSWORD', '账号密码'],
    ]),
  },
  {
    id: 'contact',
    label: '联系通信',
    ...ENTITY_PALETTE.contact,
    types: defineTypes([
      ['PHONE', '电话号码'],
      ['EMAIL', '电子邮箱'],
      ['QQ_WECHAT_ID', '社交账号'],
      ['IP_ADDRESS', 'IP 地址'],
      ['MAC_ADDRESS', 'MAC 地址'],
      ['DEVICE_ID', '设备 ID'],
      ['URL_WEBSITE', '网址'],
    ]),
  },
  {
    id: 'finance',
    label: '金融财务',
    ...ENTITY_PALETTE.contact,
    types: defineTypes([
      ['BANK_CARD', '银行卡号'],
      ['BANK_ACCOUNT', '银行账号'],
      ['BANK_NAME', '开户行'],
      ['PAYMENT_ACCOUNT', '支付账号'],
      ['TAX_ID', '税号'],
      ['AMOUNT', '金额'],
      ['PROPERTY', '财产信息'],
    ]),
  },
  {
    id: 'org_address',
    label: '机构与地址',
    ...ENTITY_PALETTE.org,
    types: defineTypes([
      ['ORG', '机构名称'],
      ['COMPANY', '公司名称'],
      ['COMPANY_CODE', '统一信用代码'],
      ['ADDRESS', '地址'],
      ['POSTAL_CODE', '邮编'],
      ['GPS_LOCATION', 'GPS 坐标'],
      ['WORK_UNIT', '工作单位'],
    ]),
  },
  {
    id: 'time_number',
    label: '时间与编号',
    ...ENTITY_PALETTE.time,
    types: defineTypes([
      ['BIRTH_DATE', '出生日期'],
      ['DATE', '日期'],
      ['TIME', '时间'],
      ['LICENSE_PLATE', '车牌号'],
      ['VIN', '车架号'],
      ['CASE_NUMBER', '案件编号'],
      ['CONTRACT_NO', '合同号'],
      ['LEGAL_DOC_NO', '法律文书号'],
    ]),
  },
  {
    id: 'demographics',
    label: '人口统计',
    ...ENTITY_PALETTE.personal,
    types: defineTypes([
      ['AGE', '年龄'],
      ['GENDER', '性别'],
      ['NATIONALITY', '国籍'],
      ['MARITAL_STATUS', '婚姻状况'],
      ['OCCUPATION', '职业'],
      ['EDUCATION', '学历'],
    ]),
  },
  {
    id: 'legal_party',
    label: '诉讼参与',
    ...ENTITY_PALETTE.personal,
    types: defineTypes([
      ['LEGAL_PARTY', '当事人'],
      ['LAWYER', '律师'],
      ['JUDGE', '法官'],
      ['WITNESS', '证人'],
    ]),
  },
  {
    id: 'sensitive',
    label: '敏感信息',
    ...ENTITY_PALETTE.personal,
    types: defineTypes([
      ['HEALTH_INFO', '健康信息'],
      ['MEDICAL_RECORD', '病历号'],
      ['CRIMINAL_RECORD', '犯罪记录'],
      ['POLITICAL', '政治面貌'],
      ['RELIGION', '宗教信仰'],
      ['SEXUAL_ORIENTATION', '性取向'],
    ]),
  },
  {
    id: 'visual',
    label: '视觉元素',
    ...ENTITY_PALETTE.time,
    types: defineTypes([
      ['SEAL', '印章'],
      ['SIGNATURE', '签名'],
      ['FINGERPRINT', '指纹'],
      ['PHOTO', '照片'],
      ['QR_CODE', '二维码'],
      ['HANDWRITING', '手写内容'],
    ]),
  },
];

export const ALL_ENTITY_TYPES: EntityTypeConfig[] = ENTITY_GROUPS.flatMap(group => group.types);

function prettifyTypeId(typeId: string) {
  return typeId
    .toLowerCase()
    .split('_')
    .map(part => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

export function getEntityGroup(typeId: string): EntityGroup | undefined {
  return ENTITY_GROUPS.find(group => group.types.some(type => type.id === typeId));
}

export function getEntityGroupLabel(groupId: string): string {
  const key = `entityGroup.${groupId}`;
  const translated = t(key);
  if (translated !== key) return translated;

  const group = ENTITY_GROUPS.find(item => item.id === groupId);
  return group?.label || groupId;
}

export function getEntityTypeConfig(typeId: string): EntityTypeConfig | undefined {
  return ALL_ENTITY_TYPES.find(type => type.id === typeId);
}

export function getEntityColor(typeId: string): string {
  const group = getEntityGroup(typeId);
  return group?.color ?? ENTITY_FALLBACK_STYLE.color;
}

export function getEntityBgColor(typeId: string): string {
  const group = getEntityGroup(typeId);
  return group?.bgColor ?? ENTITY_FALLBACK_STYLE.bgColor;
}

export function getEntityTextColor(typeId: string): string {
  const group = getEntityGroup(typeId);
  return group?.textColor ?? ENTITY_FALLBACK_STYLE.textColor;
}

export function getEntityTypeName(typeId: string): string {
  const key = `entity.${typeId}`;
  const translated = t(key);
  if (translated !== key) return translated;

  const config = getEntityTypeConfig(typeId);
  return config?.name || prettifyTypeId(typeId);
}

export function getEntityRiskConfig(typeId: string) {
  const group = getEntityGroup(typeId);
  return {
    color: group?.color ?? ENTITY_FALLBACK_STYLE.color,
    bgColor: group?.bgColor ?? ENTITY_FALLBACK_STYLE.bgColor,
    textColor: group?.textColor ?? ENTITY_FALLBACK_STYLE.textColor,
    groupLabel: group ? getEntityGroupLabel(group.id) : t('entityGroup.other'),
    groupId: group?.id || 'other',
    icon: '',
    riskLevel: 'MEDIUM' as const,
  };
}
