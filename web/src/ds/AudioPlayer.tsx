import React from 'react';
import { Play, Pause, X } from 'lucide-react';
import { cn } from './cn';

export interface AudioTrack {
  title: string;
  /** Source/show name shown under the title. */
  sourceName?: string;
  /** Optional artwork URL. Falls back to a headphones glyph. */
  thumbnailUrl?: string;
}

export interface AudioPlayerProps {
  /** The track currently loaded. When omitted the player renders nothing. */
  track?: AudioTrack;
  isPlaying?: boolean;
  /** Current position in seconds. */
  currentTime?: number;
  /** Total duration in seconds. */
  duration?: number;
  /** Playback speed multiplier (e.g. 1.0, 1.5). */
  playbackRate?: number;
  onTogglePlay?: () => void;
  /** Skip by a signed number of seconds (e.g. -15, +30). */
  onSkip?: (seconds: number) => void;
  /** Seek to an absolute position in seconds. */
  onSeek?: (seconds: number) => void;
  onClose?: () => void;
  /** Render inline (in flow) instead of fixed to the viewport bottom. Useful for previews. */
  inline?: boolean;
  className?: string;
}

function formatTime(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return '0:00';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

/**
 * Stroom's sticky podcast player bar: a draggable progress track over artwork, title,
 * skip/-play/+skip controls and a speed toggle. Presentational — wire the callbacks to
 * your audio engine. By default it fixes to the bottom of the viewport; pass `inline`
 * to render it in normal flow.
 * @category Composites
 */
export function AudioPlayer({
  track,
  isPlaying = false,
  currentTime = 0,
  duration = 0,
  playbackRate = 1.0,
  onTogglePlay,
  onSkip,
  onSeek,
  onClose,
  inline = false,
  className,
}: AudioPlayerProps) {
  const progressRef = React.useRef<HTMLDivElement>(null);
  if (!track) return null;

  const pct = duration > 0 ? (currentTime / duration) * 100 : 0;

  const seekFromClientX = (clientX: number) => {
    const el = progressRef.current;
    if (!el || !onSeek) return;
    const rect = el.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    onSeek(ratio * duration);
  };

  return (
    <div
      className={cn(
        inline ? 'relative' : 'fixed bottom-0 left-0 right-0 z-50',
        'bg-brand-cream border-t border-brand-ink/10 shadow-[0_-4px_20px_rgba(0,0,0,0.1)]',
        className,
      )}
    >
      <div
        ref={progressRef}
        role="slider"
        aria-label="Voortgang"
        aria-valuemin={0}
        aria-valuemax={Math.round(duration)}
        aria-valuenow={Math.round(currentTime)}
        className="h-3 bg-brand-ink/10 cursor-pointer relative group"
        onMouseDown={(e) => seekFromClientX(e.clientX)}
      >
        <div
          className="absolute inset-y-0 left-0 bg-brand-accent transition-all duration-75"
          style={{ width: `${pct}%` }}
        />
        <div
          className="absolute top-1/2 -translate-y-1/2 w-4 h-4 bg-brand-accent rounded-full shadow-md opacity-0 group-hover:opacity-100 transition-opacity"
          style={{ left: `calc(${pct}% - 8px)` }}
        />
      </div>

      <div className="max-w-screen-2xl mx-auto px-2 md:px-6 py-2 md:py-3 flex items-center gap-2 md:gap-4">
        <div className="w-9 h-9 md:w-12 md:h-12 rounded-lg bg-gradient-to-br from-brand-blue/30 to-brand-accent/30 flex-shrink-0 flex items-center justify-center overflow-hidden">
          {track.thumbnailUrl ? (
            <img src={track.thumbnailUrl} alt="" className="w-full h-full object-cover" />
          ) : (
            <span className="text-lg md:text-xl">🎧</span>
          )}
        </div>

        <div className="flex-1 min-w-0">
          <div className="font-medium text-xs md:text-sm text-brand-ink truncate">{track.title}</div>
          <div className="text-[10px] md:text-xs text-brand-ink/60 truncate">
            {track.sourceName ? `${track.sourceName} • ` : ''}
            {formatTime(currentTime)} / {formatTime(duration)}
          </div>
        </div>

        <div className="flex items-center gap-0.5 md:gap-1">
          <button
            onClick={() => onSkip?.(-15)}
            className="h-9 px-1.5 md:px-2 rounded-full bg-brand-surface hover:bg-brand-surface-low text-brand-ink/70"
            title="-15s"
          >
            <span className="text-[10px] font-bold">-15s</span>
          </button>
          <button
            onClick={onTogglePlay}
            aria-label={isPlaying ? 'Pauzeren' : 'Afspelen'}
            className="w-11 h-11 rounded-full bg-brand-accent text-brand-cream flex items-center justify-center hover:opacity-90"
          >
            {isPlaying ? <Pause size={18} fill="currentColor" /> : <Play size={18} fill="currentColor" />}
          </button>
          <button
            onClick={() => onSkip?.(30)}
            className="h-9 px-1.5 md:px-2 rounded-full bg-brand-surface hover:bg-brand-surface-low text-brand-ink/70"
            title="+30s"
          >
            <span className="text-[10px] font-bold">+30s</span>
          </button>
          <span className="w-10 md:w-12 h-9 rounded-full bg-brand-surface font-mono text-[11px] md:text-xs font-semibold text-brand-accent flex items-center justify-center select-none">
            {playbackRate.toFixed(1)}×
          </span>
          {onClose && (
            <button
              onClick={onClose}
              aria-label="Sluiten"
              className="w-9 h-9 rounded-full hover:bg-brand-ink/5 flex items-center justify-center text-brand-ink/50 ml-1 md:ml-2"
            >
              <X size={18} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
