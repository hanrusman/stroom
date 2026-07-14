/**
 * Eén sanitize-beleid voor alle dangerouslySetInnerHTML-plekken (verbeterplan S4).
 *
 * Feed-content is untrusted input. Alles wat als HTML gerenderd wordt gaat
 * door dit ene module: strikte tag/attr-allowlist, rel=noopener op elke link
 * (reverse-tabnabbing), en alleen http(s)-afbeeldingen (geen data:-URI's).
 */
import DOMPurify from 'dompurify';
import { marked } from 'marked';

const ALLOWED_TAGS = ['p', 'br', 'strong', 'em', 'ul', 'ol', 'li',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a', 'blockquote', 'code', 'pre', 'span', 'img'];
const ALLOWED_ATTR = ['href', 'target', 'class', 'src', 'alt'];

DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('rel', 'noopener noreferrer');
    if (!node.getAttribute('target')) node.setAttribute('target', '_blank');
  }
  if (node.tagName === 'IMG') {
    const src = node.getAttribute('src') ?? '';
    if (!/^https?:\/\//i.test(src)) node.removeAttribute('src');
  }
});

/** Sanitize kant-en-klare HTML (bv. item.description uit een feed). */
export const sanitizeHtml = (html: string | null | undefined): string =>
  DOMPurify.sanitize(html ?? '', { ALLOWED_TAGS, ALLOWED_ATTR });

/** Render markdown en sanitize het resultaat. */
export const sanitizeMarkdown = (content: string | null | undefined,
                                 options?: { breaks?: boolean }): string => {
  if (!content) return '';
  const html = marked.parse(content, { async: false, breaks: options?.breaks ?? true }) as string;
  return sanitizeHtml(html);
};
