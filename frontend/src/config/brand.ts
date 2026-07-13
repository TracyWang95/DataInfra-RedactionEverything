// Copyright 2026 DataInfra-RedactionEverything Contributors

/**
 * 白标配置（W1-1）：客户交付时通过构建期环境变量整站换牌，
 * 不改任何源码。空值 = 使用内置默认（i18n 产品名/标语、内置 logo、品牌绿）。
 *
 *   VITE_BRAND_NAME     产品名（覆盖 sidebar.productName / document.title）
 *   VITE_BRAND_TAGLINE  标语（覆盖 sidebar.subtitle）
 *   VITE_BRAND_LOGO     logo 路径（默认 /brand-logo.svg，放 public/ 下）
 *   VITE_BRAND_COLOR    主色 hex（注入 CSS --brand，主按钮/成功态/语义高亮全部跟随）
 */
export const BRAND = {
  name: (import.meta.env.VITE_BRAND_NAME as string | undefined) || '',
  tagline: (import.meta.env.VITE_BRAND_TAGLINE as string | undefined) || '',
  logoUrl: (import.meta.env.VITE_BRAND_LOGO as string | undefined) || '/brand-logo.svg',
  color: (import.meta.env.VITE_BRAND_COLOR as string | undefined) || '',
};

export function brandName(t: (key: string) => string): string {
  return BRAND.name || t('sidebar.productName');
}

export function brandTagline(t: (key: string) => string): string {
  return BRAND.tagline || t('sidebar.subtitle');
}

/** 启动时应用运行期品牌覆盖（标题 + 主色）。在应用入口调用一次。 */
export function applyBrand(): void {
  if (BRAND.name) document.title = BRAND.name;
  if (BRAND.color) document.documentElement.style.setProperty('--brand', BRAND.color);
}
