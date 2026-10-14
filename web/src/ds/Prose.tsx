import React from 'react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { cn } from './cn';

export type ProseSize = 'sm' | 'md' | 'lg';

export interface ProseProps {
  /** Markdown source. Rendered to sanitized HTML. Use this for AI summaries/digests. */
  markdown?: string;
  /** Pre-rendered HTML (e.g. RSS article bodies). Sanitized before display. */
  html?: string;
  /** Reading size: `sm` (14px), `md` (16px) or `lg` (19px) — the article body size. */
  size?: ProseSize;
  /** Use the light-on-dark variant for placement on ink/accent surfaces. */
  invert?: boolean;
  className?: string;
}

const ALLOWED_TAGS = ['p', 'br', 'strong', 'em', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a', 'blockquote', 'code', 'pre', 'span', 'img', 'figure', 'figcaption', 'hr'];
const ALLOWED_ATTR = ['href', 'target', 'class', 'src', 'alt'];

const SIZES: Record<ProseSize, string> = {
  sm: 'text-[14px] leading-[1.6]',
  md: 'text-[16px] leading-[1.65]',
  lg: 'text-[19px] leading-[1.75]',
};

/**
 * Renders long-form editorial content with Stroom's `prose-stroom` typography (Newsreader
 * headings, accent links, styled blockquotes/code). Pass `markdown` for AI summaries or
 * `html` for RSS bodies; both are sanitized with DOMPurify before rendering.
 * @category Composites
 */
export function Prose({ markdown, html, size = 'md', invert = false, className }: ProseProps) {
  const raw = markdown != null ? (marked.parse(markdown, { async: false, breaks: true }) as string) : (html ?? '');
  const clean = DOMPurify.sanitize(raw, { ALLOWED_TAGS, ALLOWED_ATTR });
  return (
    <div
      className={cn(
        'prose-stroom font-serif text-brand-ink/85 max-w-none',
        invert && 'prose-stroom-dark text-brand-cream/85',
        SIZES[size],
        className,
      )}
      dangerouslySetInnerHTML={{ __html: clean }}
    />
  );
}
