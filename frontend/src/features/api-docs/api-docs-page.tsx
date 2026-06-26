// Copyright 2026 DataInfra-RedactionEverything Contributors

import React, { useCallback, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { BookOpen, Check, Copy, ExternalLink } from 'lucide-react';
import { useT } from '@/i18n';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import apiInventoryMd from '../../../../docs/api-inventory.md?raw';
import { slugifyHeading } from './slugify';

/** Swagger UI：优先 VITE_SWAGGER_URL，否则 VITE_BACKEND_URL/docs，否则同域 /docs（需 dev proxy）。 */
export function resolveSwaggerUrl(): string {
  const explicit = import.meta.env.VITE_SWAGGER_URL as string | undefined;
  if (explicit?.trim()) {
    return explicit.trim().replace(/\/+$/, '');
  }
  const backend = import.meta.env.VITE_BACKEND_URL as string | undefined;
  if (backend?.trim() && /^https?:\/\//i.test(backend.trim())) {
    return `${backend.trim().replace(/\/+$/, '')}/docs`;
  }
  if (typeof window !== 'undefined') {
    return `${window.location.origin}/docs`;
  }
  return '/docs';
}

const SECTION_RE = /^## (.+)$/gm;
const SCROLL_OFFSET_PX = 24;

function extractSections(markdown: string): { id: string; title: string }[] {
  const sections: { id: string; title: string }[] = [];
  for (const match of markdown.matchAll(SECTION_RE)) {
    const title = match[1]?.trim() ?? '';
    if (!title || title === '场景索引') continue;
    sections.push({ id: slugifyHeading(title), title });
  }
  return sections;
}

function resolveAnchorId(href: string): string {
  try {
    return decodeURIComponent(href.replace(/^#/, ''));
  } catch {
    return href.replace(/^#/, '');
  }
}

function CopyCodeButton({ code }: { code: string }) {
  const t = useT();
  const [copied, setCopied] = useState(false);

  const onCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* ignore */
    }
  }, [code]);

  return (
    <button
      type="button"
      onClick={() => void onCopy()}
      className="absolute right-2 top-2 inline-flex h-7 items-center gap-1 rounded-md border border-border/60 bg-background/90 px-2 text-[11px] font-medium text-muted-foreground shadow-sm transition hover:text-foreground"
      aria-label={t('apiDocs.copyCode')}
    >
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      {copied ? t('apiDocs.copied') : t('apiDocs.copy')}
    </button>
  );
}

function MarkdownCode({
  className,
  children,
  ...props
}: React.ComponentPropsWithoutRef<'code'>) {
  const match = /language-(\w+)/.exec(className ?? '');
  const language = match?.[1];
  const raw = String(children ?? '').replace(/\n$/, '');
  const isBlock = Boolean(language) || raw.includes('\n');

  if (!isBlock) {
    return (
      <code
        className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-[0.85em] text-foreground"
        {...props}
      >
        {children}
      </code>
    );
  }

  return (
    <div className="group relative my-3 overflow-hidden rounded-xl border border-border/70 bg-muted/35">
      {language ? (
        <div className="border-b border-border/60 px-3 py-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {language === 'mermaid' ? 'sequence' : language}
        </div>
      ) : null}
      <CopyCodeButton code={raw} />
      <pre className="overflow-x-auto p-4 pt-9 font-mono text-xs leading-6 text-foreground">
        <code className={className} {...props}>
          {raw}
        </code>
      </pre>
    </div>
  );
}

function headingText(children: React.ReactNode): string {
  if (typeof children === 'string') return children;
  if (Array.isArray(children)) return children.map(headingText).join('');
  if (React.isValidElement<{ children?: React.ReactNode }>(children)) {
    return headingText(children.props.children);
  }
  return '';
}

export function ApiDocsPage() {
  const t = useT();
  const mainRef = useRef<HTMLElement>(null);
  const sections = useMemo(() => extractSections(apiInventoryMd), []);
  const swaggerUrl = useMemo(() => resolveSwaggerUrl(), []);

  const scrollTo = useCallback((rawId: string) => {
    const id = resolveAnchorId(rawId);
    const target = document.getElementById(id);
    const container = mainRef.current;
    if (!target || !container) return;

    const targetTop = target.getBoundingClientRect().top;
    const containerTop = container.getBoundingClientRect().top;
    container.scrollTo({
      top: container.scrollTop + targetTop - containerTop - SCROLL_OFFSET_PX,
      behavior: 'smooth',
    });
  }, []);

  const markdownComponents = useMemo(
    () => ({
      h1: ({ children }: { children?: React.ReactNode }) => (
        <h1 className="scroll-mt-24 text-3xl font-semibold tracking-tight text-foreground">
          {children}
        </h1>
      ),
      h2: ({ children }: { children?: React.ReactNode }) => {
        const id = slugifyHeading(headingText(children));
        return (
          <h2
            id={id}
            className="scroll-mt-24 border-b border-border/60 pb-2 pt-10 text-xl font-semibold tracking-tight text-foreground first:pt-4"
          >
            {children}
          </h2>
        );
      },
      h3: ({ children }: { children?: React.ReactNode }) => {
        const id = slugifyHeading(headingText(children));
        return (
          <h3 id={id} className="scroll-mt-24 pt-6 text-base font-semibold text-foreground">
            {children}
          </h3>
        );
      },
      p: ({ children }: { children?: React.ReactNode }) => (
        <p className="my-3 text-sm leading-7 text-muted-foreground">{children}</p>
      ),
      ul: ({ children }: { children?: React.ReactNode }) => (
        <ul className="my-3 list-disc space-y-1.5 pl-5 text-sm leading-7 text-muted-foreground">
          {children}
        </ul>
      ),
      ol: ({ children }: { children?: React.ReactNode }) => (
        <ol className="my-3 list-decimal space-y-1.5 pl-5 text-sm leading-7 text-muted-foreground">
          {children}
        </ol>
      ),
      li: ({ children }: { children?: React.ReactNode }) => <li className="pl-1">{children}</li>,
      strong: ({ children }: { children?: React.ReactNode }) => (
        <strong className="font-semibold text-foreground">{children}</strong>
      ),
      a: ({ href, children }: { href?: string; children?: React.ReactNode }) => {
        if (href?.startsWith('#')) {
          const id = resolveAnchorId(href);
          return (
            <a
              href={href}
              onClick={(event) => {
                event.preventDefault();
                scrollTo(id);
              }}
              className="cursor-pointer font-medium text-primary underline-offset-4 hover:underline"
            >
              {children}
            </a>
          );
        }
        const external = href?.startsWith('http');
        return (
          <a
            href={href}
            target={external ? '_blank' : undefined}
            rel={external ? 'noreferrer' : undefined}
            className="font-medium text-primary underline-offset-4 hover:underline"
          >
            {children}
          </a>
        );
      },
      hr: () => <hr className="my-8 border-border/70" />,
      table: ({ children }: { children?: React.ReactNode }) => (
        <div className="my-4 overflow-x-auto rounded-xl border border-border/70">
          <table className="w-full min-w-[480px] border-collapse text-sm">{children}</table>
        </div>
      ),
      thead: ({ children }: { children?: React.ReactNode }) => (
        <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
          {children}
        </thead>
      ),
      tbody: ({ children }: { children?: React.ReactNode }) => <tbody>{children}</tbody>,
      tr: ({ children }: { children?: React.ReactNode }) => (
        <tr className="border-t border-border/60 first:border-t-0">{children}</tr>
      ),
      th: ({ children }: { children?: React.ReactNode }) => (
        <th className="px-3 py-2.5 font-semibold text-foreground">{children}</th>
      ),
      td: ({ children }: { children?: React.ReactNode }) => (
        <td className="px-3 py-2.5 align-top text-muted-foreground">{children}</td>
      ),
      code: MarkdownCode,
      pre: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
    }),
    [scrollTo],
  );

  return (
    <div className="saas-page flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background">
      <div className="page-shell !max-w-[min(100%,1600px)] !px-3 !py-3 sm:!px-4 2xl:!px-5">
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden lg:flex-row lg:gap-4">
          <aside className="hidden w-56 shrink-0 lg:block xl:w-64">
            <div className="sticky top-3 rounded-2xl border border-border/70 bg-card p-3 shadow-[var(--shadow-sm)]">
              <div className="mb-3 flex items-center gap-2 px-1">
                <BookOpen className="h-4 w-4 text-muted-foreground" />
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {t('apiDocs.toc')}
                </p>
              </div>
              <ScrollArea className="max-h-[calc(100dvh-8rem)] pr-2">
                <nav className="grid gap-0.5" aria-label={t('apiDocs.toc')}>
                  {sections.map((section) => (
                    <button
                      key={section.id}
                      type="button"
                      onClick={() => scrollTo(section.id)}
                      className="rounded-lg px-2 py-1.5 text-left text-xs leading-5 text-muted-foreground transition hover:bg-accent hover:text-foreground"
                    >
                      {section.title}
                    </button>
                  ))}
                </nav>
              </ScrollArea>
            </div>
          </aside>

          <main
            ref={mainRef}
            className="min-h-0 min-w-0 flex-1 overflow-auto rounded-2xl border border-border/70 bg-card px-4 py-5 shadow-[var(--shadow-sm)] sm:px-6 lg:max-h-[calc(100dvh-4.5rem)]"
          >
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b border-border/60 pb-4">
              <div className="space-y-1">
                <span className="saas-kicker">{t('apiDocs.eyebrow')}</span>
                <p className="text-sm text-muted-foreground">{t('apiDocs.subtitle')}</p>
              </div>
              <Button variant="outline" size="sm" asChild className="rounded-full">
                <a
                  href={swaggerUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1.5"
                >
                  {t('apiDocs.openSwagger')}
                  <ExternalLink className="h-3.5 w-3.5" />
                </a>
              </Button>
            </div>

            <article className="api-docs-markdown pb-8">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                {apiInventoryMd}
              </ReactMarkdown>
            </article>
          </main>
        </div>
      </div>
    </div>
  );
}
