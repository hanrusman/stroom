import React, { useEffect, useState } from 'react';
import { Check, Loader2, Sparkles, Undo2, AlertTriangle } from 'lucide-react';
import {
  ApiError, DecisionProfile, DecisionScoreStatus,
  fetchDecisionProfile, saveDecisionProfile, rebuildDecisionProfile, fetchDecisionScoreStatus,
} from './api';

const MIN_CHARS = 20;
const MAX_CHARS = 4000;

const fmtDate = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString('nl-NL', { dateStyle: 'medium', timeStyle: 'short' }) : '—';

const errText = (e: unknown) => (e instanceof ApiError ? e.detail : String(e));

/** Het interesseprofiel waar nimble elk item tegen afzet (de interesse-balkjes
 *  bij "Waarom deze score?"), plus de status van de decision-batch. */
export const DecisionProfilePanel = () => {
  const [profile, setProfile] = useState<DecisionProfile | null>(null);
  const [status, setStatus] = useState<DecisionScoreStatus | null>(null);
  const [draft, setDraft] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<'save' | 'rebuild' | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  const apply = (p: DecisionProfile | null) => {
    setProfile(p);
    setDraft(p?.text ?? '');
  };

  useEffect(() => {
    Promise.all([fetchDecisionProfile(), fetchDecisionScoreStatus()])
      .then(([p, s]) => { apply(p.profile); setStatus(s); })
      .catch(e => setErr(errText(e)))
      .finally(() => setLoading(false));
  }, []);

  const trimmed = draft.trim();
  const dirty = trimmed !== (profile?.text ?? '');
  const valid = trimmed.length >= MIN_CHARS && trimmed.length <= MAX_CHARS;

  const onSave = async () => {
    setBusy('save'); setErr(null);
    try {
      apply((await saveDecisionProfile(trimmed)).profile);
      setSavedAt(Date.now());
    } catch (e) {
      setErr(errText(e));
    } finally {
      setBusy(null);
    }
  };

  const onRebuild = async () => {
    const warn = profile?.source === 'manual' || dirty
      ? 'Dit vervangt het profiel (inclusief je aanpassingen) door een nieuw automatisch profiel uit je gelikete lessen. Doorgaan?'
      : 'Een nieuw profiel genereren uit je gelikete lessen? Dit kan een minuut duren.';
    if (!window.confirm(warn)) return;
    setBusy('rebuild'); setErr(null);
    try {
      apply((await rebuildDecisionProfile()).profile);
      setSavedAt(Date.now());
    } catch (e) {
      setErr(errText(e));
    } finally {
      setBusy(null);
    }
  };

  const weight = status?.interest_weight ?? 0;
  const last = status?.last_result;

  return (
    <section className="mb-10 bg-brand-cream rounded-2xl border border-brand-ink/10 p-6 shadow-sm">
      <h2 className="font-display text-2xl text-brand-ink tracking-[-0.01em] mb-1">Interesseprofiel</h2>
      <p className="text-[13px] text-brand-ink/60 mb-4 max-w-3xl">
        De beschrijving van jou waar het decision model ({status?.model ?? 'nimble'}) elk item tegen afzet.
        Dat zie je terug als de interesse-balkjes bij <em>Waarom deze score?</em>.{' '}
        {weight > 0
          ? <>Interesse telt voor {Math.round(weight * 100)}% mee in de score.</>
          : <>Interesse telt nu <strong>niet</strong> mee in de score; aanpassen verandert alleen wat je daar ziet.</>}
        {' '}Een wijziging geldt voor items die daarna gescoord worden.
      </p>

      {loading ? (
        <div className="text-brand-ink/40 italic text-sm">Laden…</div>
      ) : (
        <>
          <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-brand-ink/50 mb-2">
            {profile
              ? <>{profile.source === 'manual'
                    ? 'Handmatig aangepast'
                    : `Automatisch uit ${profile.n_lessons ?? '?'} gelikete lessen`}
                  {' · '}versie {profile.version} · {fmtDate(profile.updated_at)}</>
              : 'Nog geen profiel — de eerstvolgende scoringsronde maakt er automatisch een'}
          </div>
          <textarea
            value={draft}
            onChange={e => setDraft(e.target.value)}
            disabled={busy !== null}
            rows={9}
            placeholder="Beschrijf welke onderwerpen, invalshoeken en soorten content je waardeert — en wat juist niet."
            className="w-full px-4 py-3 rounded-xl bg-brand-surface border border-brand-ink/10 text-sm text-brand-ink leading-relaxed disabled:opacity-50"
          />
          <div className="flex flex-wrap items-center justify-between gap-2 mt-1 text-[11px] text-brand-ink/45">
            <span>Het automatische profiel is Engels, net als de vragen aan het model; Nederlands is niet getest.</span>
            <span className={valid || !trimmed ? '' : 'text-rose-600'}>{trimmed.length} / {MAX_CHARS}</span>
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button onClick={onSave} disabled={busy !== null || !dirty || !valid}
              className="px-4 py-2 rounded-xl bg-brand-accent text-brand-cream text-sm flex items-center gap-2 disabled:opacity-50 hover:opacity-90 transition">
              {busy === 'save' ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
              Opslaan
            </button>
            {dirty && (
              <button onClick={() => apply(profile)} disabled={busy !== null}
                className="px-3 py-2 rounded-xl text-sm text-brand-ink/60 hover:text-brand-ink flex items-center gap-1.5 disabled:opacity-50">
                <Undo2 size={14} /> Terugzetten
              </button>
            )}
            <button onClick={onRebuild} disabled={busy !== null}
              className="px-3 py-2 rounded-xl border border-brand-ink/15 text-sm text-brand-ink flex items-center gap-1.5 disabled:opacity-50 hover:bg-brand-surface transition">
              {busy === 'rebuild' ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
              Opnieuw genereren uit gelikete lessen
            </button>
            {savedAt && !dirty && busy === null && (
              <span className="text-[11px] font-mono uppercase tracking-[0.15em] text-emerald-700">Opgeslagen</span>
            )}
            {err && <span className="text-[12px] text-rose-600">{err}</span>}
          </div>

          {status && (
            <div className="mt-6 pt-4 border-t border-brand-ink/10 text-[12px] text-brand-ink/60 space-y-1">
              <div>
                Scoring: {status.enabled
                  ? <>aan — elke {Math.round(status.interval_sec / 60)} min, items van de laatste {status.max_age_days} dagen</>
                  : <>uit (SCORER_MODE={status.mode}); de oude cloud-scorer wordt gebruikt</>}
              </div>
              {status.enabled && (
                <div>
                  Laatste ronde: {fmtDate(status.last_run_at)}
                  {last && typeof last.selected === 'number' && (
                    <> — {last.scored ?? 0} van {last.selected} gescoord
                      {last.item_errors ? `, ${last.item_errors} fout` : ''}</>
                  )}
                </div>
              )}
              {status.enabled && last?.calibration?.method && (
                <div>
                  Schaal: {last.calibration.method === 'percentile'
                    ? <>geijkt op {last.calibration.n} items — 10 = beste 5%, 9 = de 10% daaronder</>
                    : <>nog lineair (max. ~8); ijken start vanaf {status.calibration_min ?? 200} items, nu {last.calibration.n}</>}
                </div>
              )}
              {status.outage_since && (
                <div className="flex items-center gap-1.5 text-amber-700">
                  <AlertTriangle size={13} />
                  Classificatie lukt sinds {fmtDate(status.outage_since)} niet; de volgende ronde probeert het opnieuw.
                  {last?.error && <span className="text-brand-ink/40"> ({last.error})</span>}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
};

export default DecisionProfilePanel;
