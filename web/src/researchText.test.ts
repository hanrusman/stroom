import { describe, expect, it } from 'vitest';
import { citationsToButtons, formatDateNL, monthHistogram, stageIndex } from './researchText';

describe('citationsToButtons', () => {
  it('turns single and grouped citations into buttons', () => {
    const out = citationsToButtons('<p>A [S3] en [S1, S12].</p>');
    expect(out).toContain('data-ref="S3"');
    expect(out).toContain('data-ref="S1"');
    expect(out).toContain('aria-label="Bron 12">12</button>');
    expect(out).not.toContain('[S');
  });
  it('leaves other brackets alone', () => {
    expect(citationsToButtons('<p>[link] [S] [Sx1]</p>')).toBe('<p>[link] [S] [Sx1]</p>');
  });
});

describe('monthHistogram', () => {
  it('fills empty months between first and last', () => {
    const bins = monthHistogram(['2026-01-05', '2026-03-02', '2026-03-20', null]);
    expect(bins.map(b => [b.month, b.n])).toEqual([['2026-01', 1], ['2026-02', 0], ['2026-03', 2]]);
  });
  it('caps at 60 months and folds older sources into the first bar', () => {
    const bins = monthHistogram(['2018-07-01', '2026-11-01']);
    expect(bins).toHaveLength(60);
    expect(bins[0].n).toBe(1);
    expect(bins.reduce((n, b) => n + b.n, 0)).toBe(2);
  });
  it('returns nothing without dates', () => {
    expect(monthHistogram([null])).toEqual([]);
  });
});

describe('stageIndex / formatDateNL', () => {
  it('maps statuses to pipeline steps', () => {
    expect(stageIndex('queued')).toBe(0);
    expect(stageIndex('extracting')).toBe(3);
    expect(stageIndex('deepening')).toBe(4);
    expect(stageIndex('done')).toBe(8);
  });
  it('formats dates and survives junk', () => {
    expect(formatDateNL('2026-07-10')).toMatch(/2026/);
    expect(formatDateNL(null)).toBe('?');
    expect(formatDateNL('nope')).toBe('?');
  });
});
