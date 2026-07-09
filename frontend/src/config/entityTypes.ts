// Copyright 2026 DataInfra-RedactionEverything Contributors

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
  pii: { color: '#9333EA', bgColor: '#FAF5FF', textColor: '#6B21A8' },
  org: { color: '#0284C7', bgColor: '#F0F9FF', textColor: '#075985' },
  account: { color: '#059669', bgColor: '#ECFDF5', textColor: '#065F46' },
  code: { color: '#6366F1', bgColor: '#EEF2FF', textColor: '#4338CA' },
  record: { color: '#C2410C', bgColor: '#FFF7ED', textColor: '#9A3412' },
  visual: { color: '#7C3AED', bgColor: '#F5F3FF', textColor: '#5B21B6' },
} as const;

export const ENTITY_FALLBACK_STYLE = {
  color: '#0284C7',
  bgColor: '#F0F9FF',
  textColor: '#075985',
} as const;

const ENTITY_TYPE_ALIASES: Record<string, string> = {
  DRIVER_LICENSE: 'ID_CARD',
  MILITARY_ID: 'ID_CARD',
  QQ_WECHAT_ID: 'USERNAME_PASSWORD',
  PAYMENT_ACCOUNT: 'BANK_ACCOUNT',
  MONEY: 'AMOUNT',
  MAC_ADDRESS: 'DEVICE_ID',
  URL: 'URL_WEBSITE',
  WEBSITE: 'URL_WEBSITE',
  LINK: 'URL_WEBSITE',
  DATETIME: 'DATE',
  DATE_TIME: 'DATE',
  COMPANY: 'COMPANY_NAME',
  INSTITUTION: 'INSTITUTION_NAME',
  EMPLOYER: 'WORK_UNIT',
  WORKPLACE: 'WORK_UNIT',
  CONTRACT_ID: 'CASE_NUMBER',
  CONTRACT_NO: 'CASE_NUMBER',
  CONTRACT_NUMBER: 'CASE_NUMBER',
  LEGAL_CASE_ID: 'DOCUMENT_NUMBER',
  LEGAL_DOC_NO: 'DOCUMENT_NUMBER',
  MEDICAL_RECORD: 'MED_RECORD_ID',
  LAWYER: 'LEGAL_ATTORNEY',
  seal: 'official_seal',
  stamp: 'official_seal',
  signature: 'SIGNATURE',
  handwritten_signature: 'SIGNATURE',
};

export function normalizeEntityTypeId(typeId: string): string {
  const trimmed = typeId.trim();
  return ENTITY_TYPE_ALIASES[trimmed] ?? trimmed;
}

function defineTypes(
  entries: Array<[id: string, name: string, description?: string]>,
): EntityTypeConfig[] {
  return entries.map(([id, name, description]) => ({ id, name, description }));
}

export const ENTITY_GROUPS: EntityGroup[] = [
  {
    id: 'pii',
    label: 'PII',
    ...ENTITY_PALETTE.pii,
    types: defineTypes([
      ['PERSON', '姓名'],
      ['ID_CARD', '身份证号'],
      ['PASSPORT', '护照号'],
      ['SOCIAL_SECURITY', '社保号'],
      ['BIOMETRIC', '生物特征'],
      ['PHONE', '电话'],
      ['EMAIL', '邮箱'],
      ['BIRTH_DATE', '出生日期'],
      ['AGE', '年龄'],
      ['GENDER', '性别'],
      ['NATIONALITY', '国籍'],
      ['ETHNICITY', '民族'],
      ['MARITAL_STATUS', '婚姻状态'],
      ['RELIGION', '宗教信仰'],
      ['POLITICAL', '政治面貌'],
      ['SEXUAL_ORIENTATION', '性取向'],
      ['CRIMINAL_RECORD', '法律记录'],
      ['LEGAL_PLAINTIFF', '原告'],
      ['LEGAL_DEFENDANT', '被告'],
      ['LEGAL_THIRD_PARTY', '第三人'],
      ['LEGAL_ATTORNEY', '代理律师'],
      ['MED_PATIENT', '患者'],
      ['MED_CLINICIAN', '医务人员'],
    ]),
  },
  {
    id: 'organization_subject',
    label: '组织主体信息',
    ...ENTITY_PALETTE.org,
    types: defineTypes([
      ['ORG', '组织机构'],
      ['COMPANY_NAME', '公司名称'],
      ['INSTITUTION_NAME', '机构名称'],
      ['GOVERNMENT_AGENCY', '机关单位'],
      ['WORK_UNIT', '工作单位'],
      ['DEPARTMENT_NAME', '部门名称'],
      ['PROJECT_NAME', '项目名称'],
      ['FIN_INSTITUTION', '金融机构'],
      ['MED_INSTITUTION', '医疗机构'],
      ['MED_DEPARTMENT', '科室'],
      ['LEGAL_COURT', '法院'],
      ['LEGAL_LAW_FIRM', '律所'],
      ['CREDIT_CODE', '统一社会信用代码'],
      ['TAX_ID', '税号'],
    ]),
  },
  {
    id: 'account_transaction',
    label: '账户与交易信息',
    ...ENTITY_PALETTE.account,
    types: defineTypes([
      ['BANK_CARD', '银行卡号'],
      ['BANK_ACCOUNT', '银行账号'],
      ['BANK_NAME', '开户行'],
      ['AMOUNT', '金额'],
      ['FIN_CUSTOMER_ID', '客户号'],
      ['FIN_ACCOUNT_NAME', '账户户名'],
      ['FIN_INSTITUTION', '金融机构'],
      ['FIN_TRANSACTION_ID', '交易流水号'],
      ['FIN_MERCHANT_ID', '商户号'],
      ['FIN_RISK_RATING', '风险评级'],
    ]),
  },
  {
    id: 'address_location',
    label: '地址位置空间信息',
    ...ENTITY_PALETTE.account,
    types: defineTypes([
      ['ADDRESS', '地址'],
      ['GPS_LOCATION', '定位位置'],
    ]),
  },
  {
    id: 'time_event',
    label: '时间事件信息',
    ...ENTITY_PALETTE.code,
    types: defineTypes([
      ['DATE', '日期'],
      ['TIME', '时间'],
    ]),
  },
  {
    id: 'credential_access',
    label: '凭证密钥与访问控制信息',
    ...ENTITY_PALETTE.account,
    types: defineTypes([
      ['USERNAME_PASSWORD', '登录账号'],
      ['AUTH_SECRET', '密码'],
      ['DEVICE_ID', '设备号'],
      ['IP_ADDRESS', 'IP地址'],
      ['URL_WEBSITE', '网址'],
    ]),
  },
  {
    id: 'asset_resource',
    label: '资产资源与标的物信息',
    ...ENTITY_PALETTE.record,
    types: defineTypes([
      ['PROJECT_NAME', '项目名称'],
      ['LICENSE_PLATE', '车牌号'],
      ['VIN', '车架号'],
      ['PROPERTY', '财产'],
    ]),
  },
  {
    id: 'document_record',
    label: '文档内容与业务记录信息',
    ...ENTITY_PALETTE.record,
    types: defineTypes([
      ['LEGAL_CLAIM', '诉讼请求'],
      ['DOCUMENT_NUMBER', '文书编号'],
      ['MED_RECORD_ID', '病历号'],
      ['MED_DIAGNOSIS', '诊断'],
      ['MED_MEDICATION', '用药'],
      ['MED_EXAM_RESULT', '检查结果'],
      ['MED_CHIEF_COMPLAINT', '主诉'],
      ['MED_PRESENT_ILLNESS', '现病史'],
      ['MED_PAST_HISTORY', '既往史'],
      ['MED_ALLERGY_HISTORY', '过敏史'],
      ['MED_PROCEDURE', '医疗操作'],
      ['MED_ORDER', '医嘱'],
      ['MED_VITAL_SIGN', '生命体征'],
    ]),
  },
  {
    id: 'custom_extension',
    label: '其他文本',
    ...ENTITY_PALETTE.code,
    types: defineTypes([
      ['CASE_NUMBER', '编号'],
    ]),
  },
  {
    id: 'visual_mark',
    label: '视觉印记与版式要素',
    ...ENTITY_PALETTE.visual,
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

export const ALL_ENTITY_TYPES: EntityTypeConfig[] = ENTITY_GROUPS.flatMap((group) => group.types);

const VISUAL_FEATURE_TYPE_IDS = new Set([
  'face',
  'fingerprint',
  'palmprint',
  'id_card',
  'hk_macau_permit',
  'passport',
  'employee_badge',
  'license_plate',
  'bank_card',
  'physical_key',
  'receipt',
  'shipping_label',
  'official_seal',
  'whiteboard',
  'sticky_note',
  'mobile_screen',
  'monitor_screen',
  'medical_wristband',
  'qr_code',
  'barcode',
  'paper',
]);

function prettifyTypeId(typeId: string) {
  if (/^custom_ocr_has_/i.test(typeId)) return t('entity.customOcrHas');
  if (/^custom_/i.test(typeId)) return t('entity.custom');

  return typeId
    .toLowerCase()
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

export function getEntityGroup(typeId: string): EntityGroup | undefined {
  const canonicalTypeId = normalizeEntityTypeId(typeId);
  if (VISUAL_FEATURE_TYPE_IDS.has(canonicalTypeId)) {
    return ENTITY_GROUPS.find((group) => group.id === 'visual_mark');
  }
  return ENTITY_GROUPS.find((group) => group.types.some((type) => type.id === canonicalTypeId));
}

export function getEntityGroupLabel(groupId: string): string {
  const key = `entityGroup.${groupId}`;
  const translated = t(key);
  if (translated !== key) return translated;

  const group = ENTITY_GROUPS.find((item) => item.id === groupId);
  return group?.label || groupId;
}

export function getEntityTypeConfig(typeId: string): EntityTypeConfig | undefined {
  const canonicalTypeId = normalizeEntityTypeId(typeId);
  return ALL_ENTITY_TYPES.find((type) => type.id === canonicalTypeId);
}

export function getEntityTypeName(typeId: string): string {
  const canonicalTypeId = normalizeEntityTypeId(typeId);
  const key = `entity.${canonicalTypeId}`;
  const translated = t(key);
  if (translated !== key) return translated;

  const config = getEntityTypeConfig(canonicalTypeId);
  return config?.name || prettifyTypeId(canonicalTypeId);
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
