// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0


export type TextSegment =
  | { text: string; isMatch: false }
  | {
      text: string;
      isMatch: true;
      origKey: string;
      safeKey: string;
      matchIdx: number;
    };


export function mergePreviewMapWithDocumentSlices(
  content: string,
  entities: Array<{
    text: string;
    start: number;
    end: number;
    selected: boolean;
  }>,
  apiMap: Record<string, string>
): Record<string, string> {
  const out = { ...apiMap };
  if (!content) return out;
  for (const e of entities) {
    if (typeof e.start !== 'number' || typeof e.end !== 'number' || e.start < 0 || e.end > content.length) {
      continue;
    }
    const slice = content.slice(e.start, e.end);
    if (!slice) continue;
    const repl = apiMap[e.text];
    if (repl != null && slice !== e.text) {
      out[slice] = repl;
    }
  }
  return out;
}


export function buildFallbackPreviewEntityMap(
  entities: Array<{ text: string; type: string; selected?: boolean }>,
  mode: 'structured' | 'smart' | 'mask'
): Record<string, string> {
  const selected = entities.filter(e => e.selected !== false && e.text);
  const map: Record<string, string> = {};
  const typeCounters: Record<string, number> = {};

  const structuredPaths: Record<string, [string, string]> = {
    PERSON: ['人物', '个人.姓名'],
    ORG: ['组织', '企业.完整名称'],
    COMPANY: ['组织', '企业.完整名称'],
    ADDRESS: ['地点', '办公地址.完整地址'],
    PHONE: ['电话', '固定电话.号码'],
    ID_CARD: ['编号', '身份证.号码'],
    BANK_CARD: ['编号', '银行卡.号码'],
    CASE_NUMBER: ['编号', '案件编号.号码'],
    DATE: ['日期/时间', '具体日期.年月日'],
    EMAIL: ['邮箱', '个人邮箱.地址'],
    LICENSE_PLATE: ['编号', '车牌.号码'],
    CONTRACT_NO: ['编号', '合同编号.代码'],
    WORK_UNIT: ['组织', '工作单位.完整名称'],
    COMPANY_CODE: ['编号', '统一社会信用代码.代码'],
    AMOUNT: ['金额', '合同金额.数值'],
    MONEY: ['金额', '合同金额.数值'],
  };

  const chineseNums = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九', '十'];

  const maskOne = (text: string, typeKey: string): string => {
    const len = text.length;
    if (typeKey === 'PERSON') {
      return len >= 2 ? text[0] + '*'.repeat(len - 1) : '*';
    }
    if (typeKey === 'PHONE') {
      return len >= 11 ? text.slice(0, 3) + '****' + text.slice(-4) : '*'.repeat(len);
    }
    if (typeKey === 'ID_CARD') {
      return len >= 18 ? text.slice(0, 6) + '********' + text.slice(-4) : '*'.repeat(len);
    }
    if (typeKey === 'BANK_CARD') {
      return len >= 16 ? '*'.repeat(len - 4) + text.slice(-4) : '*'.repeat(len);
    }
    return '*'.repeat(len);
  };

  const smartOne = (typeKey: string, count: number): string => {
    const typeLabels: Record<string, string> = {
      PERSON: '当事人',
      ORG: '公司',
      COMPANY: '公司',
      ID_CARD: '证件号',
      PHONE: '电话',
      ADDRESS: '地址',
      BANK_CARD: '账号',
      CASE_NUMBER: '案号',
      DATE: '日期',
      EMAIL: '邮箱',
      LICENSE_PLATE: '车牌',
      CONTRACT_NO: '合同编号',
      WORK_UNIT: '工作单位',
      COMPANY_CODE: '信用代码',
    };
    const label = typeLabels[typeKey] ?? '敏感信息';
    const numStr = count <= 10 ? chineseNums[count] : String(count);
    return `[${label}${numStr}]`;
  };

  for (const e of selected) {
    const typeKey = e.type || 'CUSTOM';
    typeCounters[typeKey] = (typeCounters[typeKey] || 0) + 1;
    const idx = typeCounters[typeKey];
    const t = e.text;
    let repl: string;
    if (mode === 'mask') {
      repl = maskOne(t, typeKey);
    } else if (mode === 'smart') {
      repl = smartOne(typeKey, idx);
    } else {
      const pair = structuredPaths[typeKey];
      if (pair) {
        const [cat, path] = pair;
        repl = `<${cat}[${String(idx).padStart(3, '0')}].${path}>`;
      } else {
        repl = `<${typeKey}[${String(idx).padStart(3, '0')}].完整名称>`;
      }
    }
    map[t] = repl;
  }
  return map;
}

export function buildTextSegments(text: string, map: Record<string, string>): TextSegment[] {
  if (!text || Object.keys(map).length === 0) return [{ text, isMatch: false }];
  const sortedKeys = Object.keys(map).sort((a, b) => b.length - a.length);
  const regex = new RegExp(`(${sortedKeys.map(k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'g');
  const parts = text.split(regex);
  const counters: Record<string, number> = {};
  return parts.map(part => {
    if (map[part] !== undefined) {
      const safeKey = part.replace(/[^a-zA-Z0-9\u4e00-\u9fff]/g, '_');
      const idx = counters[safeKey] || 0;
      counters[safeKey] = idx + 1;
      return { text: part, isMatch: true as const, origKey: part, safeKey, matchIdx: idx };
    }
    return { text: part, isMatch: false as const };
  });
}
