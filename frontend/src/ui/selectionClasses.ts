/**
 * 全站「类型勾选」语义色：正则 / NER（含 OCR+HaS 文本实体）/ YOLO（HaS Image）
 * 选中：浅色底 + 细边框 + 深色字；未选中：白底、低对比、无彩色底。
 */

export type SelectionVariant = 'regex' | 'ner' | 'yolo';

/** Playground / 批量向导 文本分组 key → 语义色 */
export function textGroupKeyToVariant(key: 'regex' | 'llm' | 'other'): SelectionVariant {
  return key === 'regex' ? 'regex' : 'ner';
}

const cardBase =
  'rounded-xl border transition-[background-color,border-color,box-shadow,color] duration-200 ease-out';

/** 侧栏 / Playground 标准行（略大圆角、苹果式轻阴影） */
export function selectableCardClass(selected: boolean, variant: SelectionVariant): string {
  if (!selected) {
    return `${cardBase} border-black/[0.06] bg-white text-[#6e6e73] shadow-[0_1px_2px_rgba(0,0,0,0.04)] hover:border-black/[0.1] hover:bg-[#fafafa] hover:shadow-[0_1px_3px_rgba(0,0,0,0.06)]`;
  }
  switch (variant) {
    case 'regex':
      return `${cardBase} border-[#007AFF]/32 bg-[#007AFF]/[0.09] text-[#0a4a8c] shadow-[0_1px_3px_rgba(0,122,255,0.12)]`;
    case 'ner':
      return `${cardBase} border-[#34C759]/32 bg-[#34C759]/[0.09] text-[#0d5c2f] shadow-[0_1px_3px_rgba(52,199,89,0.12)]`;
    case 'yolo':
      return `${cardBase} border-[#AF52DE]/32 bg-[#AF52DE]/[0.11] text-[#5c2d7a] shadow-[0_1px_3px_rgba(175,82,222,0.14)]`;
  }
}

/** 批量向导等紧凑网格 */
export function selectableCardClassCompact(selected: boolean, variant: SelectionVariant): string {
  if (!selected) {
    return `${cardBase} border-black/[0.06] bg-white text-[#6e6e73] hover:border-black/[0.1] hover:bg-[#fafafa]`;
  }
  switch (variant) {
    case 'regex':
      return `${cardBase} border-[#007AFF]/32 bg-[#007AFF]/[0.09] text-[#0a4a8c]`;
    case 'ner':
      return `${cardBase} border-[#34C759]/32 bg-[#34C759]/[0.09] text-[#0d5c2f]`;
    case 'yolo':
      return `${cardBase} border-[#AF52DE]/32 bg-[#AF52DE]/[0.11] text-[#5c2d7a]`;
  }
}

export function selectableCheckboxClass(variant: SelectionVariant, size: 'sm' | 'md' = 'sm'): string {
  const dim = size === 'md' ? 'h-4 w-4' : 'h-3.5 w-3.5';
  const ring =
    variant === 'regex'
      ? 'accent-[#007AFF] focus:ring-[#007AFF]/20'
      : variant === 'ner'
        ? 'accent-[#34C759] focus:ring-[#34C759]/20'
        : 'accent-[#AF52DE] focus:ring-[#AF52DE]/20';
  return `${dim} shrink-0 rounded border-gray-300/70 focus:ring-2 focus:ring-offset-0 focus:outline-none ${ring}`;
}

/** 无分组时的通用列表（如设置里整表 NER） */
export function selectableCardClassNeutral(selected: boolean): string {
  if (!selected) {
    return `${cardBase} border-black/[0.06] bg-white text-[#6e6e73] hover:border-black/[0.1] hover:bg-[#fafafa]`;
  }
  return `${cardBase} border-[#34C759]/32 bg-[#34C759]/[0.09] text-[#0d5c2f] shadow-[0_1px_3px_rgba(52,199,89,0.12)]`;
}

export function selectableCheckboxNeutral(size: 'sm' | 'md' = 'sm'): string {
  const dim = size === 'md' ? 'h-4 w-4' : 'h-3.5 w-3.5';
  return `${dim} shrink-0 rounded border-gray-300/70 accent-[#34C759] focus:ring-2 focus:ring-[#34C759]/20 focus:ring-offset-0 focus:outline-none`;
}

/** 确认步骤、导出列表等非语义勾选 */
export function formCheckboxClass(size: 'sm' | 'md' = 'sm'): string {
  const dim = size === 'md' ? 'h-4 w-4' : 'h-3.5 w-3.5';
  return `${dim} shrink-0 rounded border-gray-300/80 accent-[#1d1d1f] focus:ring-2 focus:ring-black/10 focus:ring-offset-0 focus:outline-none`;
}
