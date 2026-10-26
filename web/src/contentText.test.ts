// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { excerptText, readerHTML } from './contentText';
describe('feed excerpts', () => {
  it('decodes named and numeric entities', () => {
    expect(excerptText('<p>Han&#x27;s idee &mdash; café &amp; thee&nbsp; &#128512;</p>')).toBe("Han's idee — café & thee 😀");
  });
  it('preserves paragraph and list word boundaries', () => {
    expect(excerptText('<p>Eerste</p><p>Tweede<br>Derde</p><ul><li>Vier</li><li>Vijf</li></ul>')).toBe('Eerste Tweede Derde Vier Vijf');
  });
  it('shows Markdown labels without markup', () => {
    expect(excerptText('## Kop\n\nEen **goed** [idee](https://example.com).')).toBe('Kop Een goed idee.');
  });
  it('removes active and invisible content', () => {
    expect(excerptText('<script>alert(1)</script><style>body{}</style><p>Lees dit<img src="https://tracker.example/a"><iframe src="https://example.com"></iframe></p>')).toBe('Lees dit');
  });
  it('handles escaped tags and Markdown inside feed HTML', () => {
    expect(excerptText('&lt;p&gt;Hallo &amp;amp; dag&lt;/p&gt;')).toBe('Hallo & dag');
    expect(excerptText('<p>Een **goed** idee</p>')).toBe('Een goed idee');
  });
  it('handles plain comparisons, empty text and Unicode', () => {
    expect(excerptText('2 < 3 en 5 > 4')).toBe('2 < 3 en 5 > 4');
    expect(excerptText(null)).toBe(''); expect(excerptText('👩🏾‍💻 **café**')).toBe('👩🏾‍💻 café');
  });
});

it('reader preserves safe HTML and renders Markdown inside paragraphs', () => {
  const holder=document.createElement('div');
  holder.innerHTML=readerHTML('<h2>Titel</h2><p>Een **sterk** [idee](https://example.com).</p><script>bad()</script>');
  expect(holder.querySelector('h2')?.textContent).toBe('Titel');
  expect(holder.querySelector('strong')?.textContent).toBe('sterk');
  expect(holder.querySelector('a')?.getAttribute('href')).toBe('https://example.com');
  expect(holder.querySelector('script')).toBeNull();
});
it('reader keeps code literal and removes unsafe URLs', () => {
  const holder=document.createElement('div');
  holder.innerHTML=readerHTML('<code>**literal**</code><a href="javascript:alert(1)">link</a>');
  expect(holder.querySelector('code')?.textContent).toBe('**literal**');
  expect(holder.querySelector('a')?.getAttribute('href')).toBeNull();
});
