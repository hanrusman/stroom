import React from 'react';
import { useGlobalAudio } from './GlobalAudioContext';
import { Play, Pause, X } from 'lucide-react';

const StickyPlayer: React.FC = () => {
  const {
    currentTrack,
    isPlaying,
    currentTime,
    duration,
    playbackRate,
    togglePlay,
    skip,
    seek,
    setPlaybackRate,
    close,
  } = useGlobalAudio();

  if (!currentTrack) return null;

  const formatTime = (seconds: number): string => {
    if (!isFinite(seconds) || seconds < 0) return '0:00';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${String(s).padStart(2, '0')}`;
  };

  const [isDragging, setIsDragging] = React.useState(false);
  const progressRef = React.useRef<HTMLDivElement>(null);

  const calculateSeek = (clientX: number) => {
    if (!progressRef.current) return;
    const rect = progressRef.current.getBoundingClientRect();
    const x = clientX - rect.left;
    const pct = Math.max(0, Math.min(1, x / rect.width));
    seek(pct * duration);
  };

  const handleStart = (clientX: number) => {
    setIsDragging(true);
    calculateSeek(clientX);
  };

  const handleMove = React.useCallback(
    (clientX: number) => {
      if (isDragging) {
        calculateSeek(clientX);
      }
    },
    [isDragging, duration]
  );

  const handleEnd = React.useCallback(() => {
    setIsDragging(false);
  }, []);

  // Mouse events
  const handleMouseDown = (e: React.MouseEvent) => handleStart(e.clientX);
  const handleMouseMove = React.useCallback(
    (e: MouseEvent) => handleMove(e.clientX),
    [handleMove]
  );
  const handleMouseUp = handleEnd;

  // Touch events
  const handleTouchStart = (e: React.TouchEvent) => handleStart(e.touches[0].clientX);
  const handleTouchMove = React.useCallback(
    (e: TouchEvent) => {
      e.preventDefault();
      handleMove(e.touches[0].clientX);
    },
    [handleMove]
  );
  const handleTouchEnd = handleEnd;

  React.useEffect(() => {
    if (isDragging) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
      document.addEventListener('touchmove', handleTouchMove, { passive: false });
      document.addEventListener('touchend', handleTouchEnd);
    }
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.removeEventListener('touchmove', handleTouchMove);
      document.removeEventListener('touchend', handleTouchEnd);
    };
  }, [isDragging, handleMouseMove, handleMouseUp, handleTouchMove, handleTouchEnd]);

  const cycleRate = (direction: 'up' | 'down' = 'up') => {
    if (direction === 'down') {
      const next = playbackRate <= 1.0 ? 2.5 : Math.round((playbackRate - 0.1) * 10) / 10;
      setPlaybackRate(next);
    } else {
      const next = playbackRate >= 2.5 ? 1.0 : Math.round((playbackRate + 0.1) * 10) / 10;
      setPlaybackRate(next);
    }
  };

  // Long-press voor mobile: snelheid omlaag
  const longPressTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const isLongPressRef = React.useRef(false);

  const handleRateTouchStart = () => {
    isLongPressRef.current = false;
    longPressTimer.current = setTimeout(() => {
      isLongPressRef.current = true;
      cycleRate('down');
    }, 500);
  };

  const handleRateTouchEnd = (e: React.TouchEvent | React.MouseEvent) => {
    if (longPressTimer.current) {
      clearTimeout(longPressTimer.current);
      longPressTimer.current = null;
    }
    // Alleen klik als het geen long-press was
    if (!isLongPressRef.current) {
      const altKey = 'altKey' in e && e.altKey;
      cycleRate(altKey ? 'down' : 'up');
    }
    isLongPressRef.current = false;
  };

  const pct = duration > 0 ? (currentTime / duration) * 100 : 0;

  return (
    <div className="fixed bottom-0 left-0 right-0 bg-brand-cream border-t border-brand-ink/10 shadow-[0_-4px_20px_rgba(0,0,0,0.1)] z-50">
      {/* Progress bar */}
      <div
        ref={progressRef}
        role="slider"
        aria-label="Voortgang"
        aria-valuemin={0}
        aria-valuemax={Math.round(duration)}
        aria-valuenow={Math.round(currentTime)}
        aria-valuetext={`${formatTime(currentTime)} van ${formatTime(duration)}`}
        className="h-3 bg-brand-ink/10 cursor-pointer relative group"
        onMouseDown={handleMouseDown}
        onTouchStart={handleTouchStart}
      >
        {/* Background track */}
        <div className="absolute inset-0 h-full" />
        {/* Filled progress */}
        <div
          className="absolute inset-y-0 left-0 bg-brand-accent transition-all duration-75"
          style={{ width: `${pct}%` }}
        />
        {/* Scrubber handle - always visible when dragging, on hover otherwise */}
        <div
          className={`absolute top-1/2 -translate-y-1/2 w-4 h-4 bg-brand-accent rounded-full shadow-md transition-opacity duration-150 ${
            isDragging ? 'opacity-100 scale-110' : 'opacity-0 group-hover:opacity-100'
          }`}
          style={{ left: `calc(${pct}% - 8px)` }}
        />
      </div>

      <div className="max-w-screen-2xl mx-auto px-4 md:px-6 py-3 flex items-center gap-4">
        {/* Artwork */}
        <div className="w-12 h-12 rounded-lg bg-gradient-to-br from-brand-blue/30 to-brand-accent/30 flex-shrink-0 flex items-center justify-center">
          {currentTrack.thumbnailUrl ? (
            <img
              src={currentTrack.thumbnailUrl}
              alt=""
              className="w-full h-full object-cover rounded-lg"
            />
          ) : (
            <span className="text-xl">🎧</span>
          )}
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div className="font-medium text-sm text-brand-ink truncate">
            {currentTrack.title}
          </div>
          <div className="text-xs text-brand-ink/60">
            {currentTrack.sourceName} • {formatTime(currentTime)} / {formatTime(duration)}
          </div>
        </div>

        {/* Controls */}
        <div className="flex items-center gap-1">
          <button
            onClick={() => skip(-15)}
            className="h-9 px-2 rounded-full bg-brand-surface hover:bg-brand-surface-low flex flex-col items-center justify-center text-brand-ink/70 leading-none"
            title="-15s"
          >
            <span className="text-[10px] font-bold">-15s</span>
          </button>

          <button
            onClick={togglePlay}
            aria-label={isPlaying ? 'Pauzeren' : 'Afspelen'}
            className="w-11 h-11 rounded-full bg-brand-accent text-brand-cream flex items-center justify-center hover:opacity-90"
          >
            {isPlaying ? <Pause size={18} fill="currentColor" /> : <Play size={18} fill="currentColor" />}
          </button>

          <button
            onClick={() => skip(30)}
            className="h-9 px-2 rounded-full bg-brand-surface hover:bg-brand-surface-low flex flex-col items-center justify-center text-brand-ink/70 leading-none"
            title="+30s"
          >
            <span className="text-[10px] font-bold">+30s</span>
          </button>

          <button
            onMouseDown={handleRateTouchStart}
            onMouseUp={handleRateTouchEnd}
            onMouseLeave={() => {
              if (longPressTimer.current) {
                clearTimeout(longPressTimer.current);
                longPressTimer.current = null;
              }
              isLongPressRef.current = false;
            }}
            onTouchStart={handleRateTouchStart}
            onTouchEnd={(e) => { e.preventDefault(); handleRateTouchEnd(e); }}
            className="w-12 h-9 rounded-full bg-brand-surface hover:bg-brand-surface-low font-mono text-xs font-semibold text-brand-accent select-none"
            title="Klik voor omhoog, Alt+klik/lang-press voor omlaag"
          >
            {playbackRate.toFixed(1)}×
          </button>

          <button
            onClick={close}
            className="w-9 h-9 rounded-full hover:bg-brand-ink/5 flex items-center justify-center text-brand-ink/50 ml-2"
            title="Sluiten"
          >
            <X size={18} />
          </button>
        </div>
      </div>
    </div>
  );
};

export default StickyPlayer;
