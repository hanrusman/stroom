import React from 'react';
import type { QualityScoreDetail, ScoreRubric } from './api';

// De rubric-niveaus zoals de decision-scorer ze aan nimble geeft (Engels), met
// een Nederlands label voor de UI. Onbekende labels tonen we ongewijzigd.
const LABELS: Record<string, string> = {
  'Spam, clickbait or advertisement': 'Spam / reclame',
  'Shallow, low signal': 'Oppervlakkig',
  'Decent but unremarkable': 'Degelijk',
  'Well-argued with specific insights': 'Goed onderbouwd',
  'Exceptional depth or rare expertise': 'Uitzonderlijk diep',
  'Not interesting': 'Niet interessant',
  'Slightly interesting': 'Een beetje',
  'Interesting': 'Interessant',
  'Must read': 'Must read',
};

const pct = (p: number) => `${Math.round(p * 100)}%`;

const Rubric = ({ title, rubric, note, showScore = true }: { title: string; rubric: ScoreRubric; note?: string; showScore?: boolean }) => (
  <div>
    <div className="flex items-baseline justify-between text-xs text-brand-ink/70 mb-1">
      <span className="font-medium">{title}{note && <span className="font-normal text-brand-ink/40"> · {note}</span>}</span>
      {showScore && <span className="font-bold text-brand-ink">{rubric.score10}/10</span>}
    </div>
    <div className="space-y-0.5">
      {Object.entries(rubric.probabilities).map(([label, p]) => (
        <div key={label} className="flex items-center gap-2 text-[11px] text-brand-ink/60">
          <span className="w-32 shrink-0 truncate" title={label}>{LABELS[label] ?? label}</span>
          <div className="flex-1 h-1.5 bg-brand-surface rounded">
            <div className="h-1.5 bg-brand-accent rounded" style={{ width: pct(p) }} />
          </div>
          <span className="w-9 text-right tabular-nums">{pct(p)}</span>
        </div>
      ))}
    </div>
  </div>
);

/** "Waarom deze score?" — wat het decision model teruggaf voor dit item. */
export const ScoreDetail = ({ detail }: { detail?: QualityScoreDetail | null }) => {
  if (!detail) {
    return <p className="text-xs text-brand-ink/40">Geen uitleg beschikbaar (oudere of handmatige score).</p>;
  }
  if (detail.error) {
    return <p className="text-xs text-brand-ink/50">Kon niet automatisch gescoord worden: {detail.error}</p>;
  }
  const interestCounts = (detail.interest_weight ?? 0) > 0;
  const cal = detail.calibration?.method === 'percentile' ? detail.calibration : null;
  return (
    <div className="space-y-3 rounded border border-brand-ink/10 p-3">
      <div className="text-xs font-semibold text-brand-ink/70">Waarom deze score?</div>
      {cal && (
        <div className="flex items-baseline justify-between gap-3 text-xs text-brand-ink/70">
          <span>
            Beter dan <strong className="text-brand-ink">{pct(cal.percentile)}</strong> van wat de
            afgelopen {cal.days} dagen binnenkwam <span className="text-brand-ink/40">(n={cal.n})</span>
          </span>
          <span className="font-bold text-brand-ink shrink-0">{cal.score}/10</span>
        </div>
      )}
      {detail.quality && (
        <Rubric title={cal ? 'Kwaliteit volgens het model' : 'Kwaliteit'} rubric={detail.quality}
                showScore={!cal} />
      )}
      {detail.interest && (
        <Rubric title="Interesse (jouw profiel)" rubric={detail.interest}
                note={interestCounts ? `telt ${pct(detail.interest_weight!)} mee` : 'telt niet mee'} />
      )}
      {detail.clickbait != null && (
        <div className="text-[11px] text-brand-ink/60">Kans op clickbait/reclame: {pct(detail.clickbait)}</div>
      )}
      <div className="text-[10px] text-brand-ink/35">
        {detail.model}{detail.profile_version && <> · profiel {detail.profile_version}</>}
        {detail.scored_at && <> · {new Date(detail.scored_at).toLocaleString('nl-NL')}</>}
      </div>
    </div>
  );
};

/** Korte samenvatting voor een tooltip op de score. */
export const scoreDetailTooltip = (detail?: QualityScoreDetail | null): string | undefined => {
  if (!detail || detail.error || !detail.quality) return undefined;
  const cal = detail.calibration?.method === 'percentile' ? detail.calibration : null;
  const parts = [cal ? `beter dan ${pct(cal.percentile)} van de laatste ${cal.days} dagen`
                     : `kwaliteit ${detail.quality.score10}/10`];
  if (detail.interest) parts.push(`interesse ${detail.interest.score10}/10`);
  if (detail.clickbait != null) parts.push(`clickbait ${pct(detail.clickbait)}`);
  return parts.join(' · ');
};

export default ScoreDetail;
