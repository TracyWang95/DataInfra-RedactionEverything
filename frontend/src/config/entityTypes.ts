/**
 * 实体类型配置 - 基于 GB/T 37964-2019《信息安全技术 个人信息去标识化指南》
 * 
 * 采用二级分组结构：
 * - 一级：功能分组（个人身份、联系通信、金融财务等）
 * - 二级：具体实体类型
 */

export interface EntityTypeConfig {
  id: string;
  name: string;
  description?: string;
}

export interface EntityGroup {
  id: string;
  label: string;
  color: string;        // 分组主色
  bgColor: string;      // 分组背景色
  textColor: string;    // 分组文字色
  types: EntityTypeConfig[];
}

/**
 * 统一四套语义色（Playground 结果页 / 批量审阅 / 侧栏气泡共用），限定为蓝 / 绿 / 紫三色体系。
 * personal：紫 · org：蓝 · contact：绿 · time：靛紫（蓝紫过渡）
 */
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

// 实体分组配置 - 与 Playground 上传页面一致
export const ENTITY_GROUPS: EntityGroup[] = [
  {
    id: 'identity',
    label: '个人身份',
    ...ENTITY_PALETTE.personal,
    types: [
      { id: 'PERSON', name: '姓名', description: '自然人姓名' },
      { id: 'ID_CARD', name: '身份证号', description: '居民身份证号码' },
      { id: 'PASSPORT', name: '护照号', description: '护照证件号码' },
      { id: 'SOCIAL_SECURITY', name: '社保号', description: '社会保障号码' },
      { id: 'DRIVER_LICENSE', name: '驾驶证号', description: '驾驶证号码' },
      { id: 'MILITARY_ID', name: '军官证号', description: '军官证件号码' },
      { id: 'BIOMETRIC', name: '生物特征', description: '指纹、人脸等' },
      { id: 'USERNAME_PASSWORD', name: '账号密码', description: '用户名密码' },
    ],
  },
  {
    id: 'contact',
    label: '联系通信',
    ...ENTITY_PALETTE.contact,
    types: [
      { id: 'PHONE', name: '电话号码', description: '手机号、固话' },
      { id: 'EMAIL', name: '电子邮箱', description: '电子邮件地址' },
      { id: 'QQ_WECHAT_ID', name: '社交账号', description: 'QQ/微信号' },
      { id: 'IP_ADDRESS', name: 'IP地址', description: '网络IP地址' },
      { id: 'MAC_ADDRESS', name: 'MAC地址', description: '设备MAC地址' },
      { id: 'DEVICE_ID', name: '设备ID', description: '设备标识符' },
      { id: 'URL_WEBSITE', name: '网址', description: '网站URL' },
    ],
  },
  {
    id: 'finance',
    label: '金融财务',
    ...ENTITY_PALETTE.contact,
    types: [
      { id: 'BANK_CARD', name: '银行卡号', description: '银行卡号码' },
      { id: 'BANK_ACCOUNT', name: '银行账号', description: '银行账户号码' },
      { id: 'BANK_NAME', name: '开户行', description: '开户银行名称' },
      { id: 'PAYMENT_ACCOUNT', name: '支付账号', description: '支付宝/微信支付' },
      { id: 'TAX_ID', name: '税号', description: '纳税人识别号' },
      { id: 'AMOUNT', name: '金额', description: '金额数值' },
      { id: 'PROPERTY', name: '财产', description: '财产信息' },
    ],
  },
  {
    id: 'org_address',
    label: '机构地址',
    ...ENTITY_PALETTE.org,
    types: [
      { id: 'ORG', name: '机构名称', description: '组织机构名称' },
      { id: 'COMPANY', name: '公司名称', description: '企业名称' },
      { id: 'COMPANY_CODE', name: '信用代码', description: '统一社会信用代码' },
      { id: 'ADDRESS', name: '地址', description: '详细地址信息' },
      { id: 'POSTAL_CODE', name: '邮编', description: '邮政编码' },
      { id: 'GPS_LOCATION', name: 'GPS坐标', description: 'GPS定位信息' },
      { id: 'WORK_UNIT', name: '工作单位', description: '所在单位' },
    ],
  },
  {
    id: 'time_number',
    label: '时间编号',
    ...ENTITY_PALETTE.time,
    types: [
      { id: 'BIRTH_DATE', name: '出生日期', description: '出生年月日' },
      { id: 'DATE', name: '日期', description: '一般日期信息' },
      { id: 'TIME', name: '时间', description: '时间信息' },
      { id: 'LICENSE_PLATE', name: '车牌号', description: '机动车号牌' },
      { id: 'VIN', name: '车架号', description: '车辆识别号' },
      { id: 'CASE_NUMBER', name: '案号', description: '案件编号' },
      { id: 'CONTRACT_NO', name: '合同号', description: '合同编号' },
      { id: 'LEGAL_DOC_NO', name: '法律文书号', description: '法律文书编号' },
    ],
  },
  {
    id: 'demographics',
    label: '人口统计',
    ...ENTITY_PALETTE.personal,
    types: [
      { id: 'AGE', name: '年龄', description: '年龄信息' },
      { id: 'GENDER', name: '性别', description: '性别信息' },
      { id: 'NATIONALITY', name: '国籍', description: '国籍/民族' },
      { id: 'MARITAL_STATUS', name: '婚姻状况', description: '婚姻状态' },
      { id: 'OCCUPATION', name: '职业', description: '职业信息' },
      { id: 'EDUCATION', name: '学历', description: '教育背景' },
    ],
  },
  {
    id: 'legal_party',
    label: '诉讼参与',
    ...ENTITY_PALETTE.personal,
    types: [
      { id: 'LEGAL_PARTY', name: '当事人', description: '案件当事人' },
      { id: 'LAWYER', name: '律师', description: '代理律师' },
      { id: 'JUDGE', name: '法官', description: '审判人员' },
      { id: 'WITNESS', name: '证人', description: '案件证人' },
    ],
  },
  {
    id: 'sensitive',
    label: '敏感信息',
    ...ENTITY_PALETTE.personal,
    types: [
      { id: 'HEALTH_INFO', name: '健康信息', description: '健康状况' },
      { id: 'MEDICAL_RECORD', name: '病历号', description: '医疗记录号' },
      { id: 'CRIMINAL_RECORD', name: '犯罪记录', description: '犯罪相关信息' },
      { id: 'POLITICAL', name: '政治面貌', description: '政治信息' },
      { id: 'RELIGION', name: '宗教信仰', description: '宗教信息' },
      { id: 'SEXUAL_ORIENTATION', name: '性取向', description: '性取向信息' },
    ],
  },
  {
    id: 'visual',
    label: '视觉元素',
    ...ENTITY_PALETTE.time,
    types: [
      { id: 'SEAL', name: '印章', description: '公章、私章' },
      { id: 'SIGNATURE', name: '签名', description: '手写签名' },
      { id: 'FINGERPRINT', name: '指纹', description: '指纹印记' },
      { id: 'PHOTO', name: '照片', description: '人物照片' },
      { id: 'QR_CODE', name: '二维码', description: '二维码信息' },
      { id: 'HANDWRITING', name: '手写内容', description: '手写文字' },
    ],
  },
];

// 所有实体类型的扁平列表
export const ALL_ENTITY_TYPES: EntityTypeConfig[] = ENTITY_GROUPS.flatMap(g => g.types);

// 根据类型ID获取所属分组
export function getEntityGroup(typeId: string): EntityGroup | undefined {
  return ENTITY_GROUPS.find(g => g.types.some(t => t.id === typeId));
}

// 获取实体类型配置
export function getEntityTypeConfig(typeId: string): EntityTypeConfig | undefined {
  return ALL_ENTITY_TYPES.find(t => t.id === typeId);
}

// 获取实体类型的颜色（基于所属分组）
export function getEntityColor(typeId: string): string {
  const group = getEntityGroup(typeId);
  return group?.color ?? ENTITY_FALLBACK_STYLE.color;
}

// 获取实体类型的背景颜色
export function getEntityBgColor(typeId: string): string {
  const group = getEntityGroup(typeId);
  return group?.bgColor ?? ENTITY_FALLBACK_STYLE.bgColor;
}

// 获取实体类型的文字颜色
export function getEntityTextColor(typeId: string): string {
  const group = getEntityGroup(typeId);
  return group?.textColor ?? ENTITY_FALLBACK_STYLE.textColor;
}

// 获取实体类型名称
export function getEntityTypeName(typeId: string): string {
  const config = getEntityTypeConfig(typeId);
  return config?.name || typeId;
}

// 获取实体的完整样式配置
export function getEntityRiskConfig(typeId: string) {
  const group = getEntityGroup(typeId);
  return {
    color: group?.color ?? ENTITY_FALLBACK_STYLE.color,
    bgColor: group?.bgColor ?? ENTITY_FALLBACK_STYLE.bgColor,
    textColor: group?.textColor ?? ENTITY_FALLBACK_STYLE.textColor,
    groupLabel: group?.label || '其他',
    groupId: group?.id || 'other',
    icon: '',
    riskLevel: 'MEDIUM' as const,
  };
}
