// Copyright 2026 DataInfra-RedactionEverything Contributors

/** Match heading anchors in docs/api-inventory.md (GitHub-style, 中文标题). */
export function slugifyHeading(text: string): string {
  return text
    .trim()
    .toLowerCase()
    .replace(/[·/（）()]/g, '')
    .replace(/[^\w\u4e00-\u9fff\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-+|-+$/g, '');
}
