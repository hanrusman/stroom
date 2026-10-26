import DOMPurify from 'dompurify';
import { marked } from 'marked';

/** Inert, sanitized parsing: no feed images/iframes are loaded for an excerpt. */
function plainPass(value: string | null | undefined): string {
  const html = marked.parse(value ?? '', { async: false }) as string;
  const fragment = DOMPurify.sanitize(html, {
    RETURN_DOM_FRAGMENT: true,
    ALLOWED_TAGS: ['p', 'br', 'div', 'li', 'ul', 'ol', 'blockquote', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'strong', 'em', 'a', 'code', 'pre', 'span'],
    ALLOWED_ATTR: [],
  });
  fragment.querySelectorAll('p,br,div,li,blockquote,h1,h2,h3,h4,h5,h6,pre').forEach(el => {
    el.prepend(document.createTextNode(' '));
    el.append(document.createTextNode(' '));
  });
  return (fragment.textContent ?? '').replace(/\s+/g, ' ').trim();
}

export function excerptText(value: string | null | undefined): string {
  return plainPass(plainPass(value));
}

/** Preserve article structure, including Markdown supplied inside HTML paragraphs. */
export function readerHTML(value: string | null | undefined): string {
  const source = value ?? '';
  const containsHTML = /<\/?(?:p|div|br|h[1-6]|ul|ol|li|a|img|blockquote|pre|code|strong|em|b|i|span|table)\b[^>]*>/i.test(source);
  const fragment = DOMPurify.sanitize(containsHTML ? source : marked.parse(source, { async: false }) as string, { RETURN_DOM_FRAGMENT: true });
  const walker = document.createTreeWalker(fragment, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  while (walker.nextNode()) nodes.push(walker.currentNode as Text);
  for (const node of nodes) {
    if (node.parentElement?.closest('pre,code')) continue;
    if (!/[*_`\[]/.test(node.data)) continue;
    // Escape literal HTML before inline Markdown parsing so a text node cannot
    // become an active element. Sanitize the result independently as well.
    const escaped = node.data.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    node.replaceWith(DOMPurify.sanitize(marked.parseInline(escaped, { async: false }) as string, { RETURN_DOM_FRAGMENT: true }));
  }
  const holder = document.createElement('div'); holder.append(fragment);
  return holder.innerHTML;
}
