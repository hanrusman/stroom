import React, { createContext, useContext, useState, useCallback, useRef, useEffect } from 'react';

interface Track {
  itemId: string;
  title: string;
  sourceName: string;
  mediaUrl: string;
  format: 'podcast' | 'video';
  thumbnailUrl?: string;
}

interface GlobalAudioState {
  currentTrack: Track | null;
  isPlaying: boolean;
  currentTime: number;
  duration: number;
  playbackRate: number;
}

interface GlobalAudioContextType extends GlobalAudioState {
  loadTrack: (track: Track) => void;
  togglePlay: () => void;
  seek: (time: number) => void;
  skip: (deltaSeconds: number) => void;
  setPlaybackRate: (rate: number) => void;
  close: () => void;
  audioRef: React.RefObject<HTMLAudioElement | null>;
}

const GlobalAudioContext = createContext<GlobalAudioContextType | null>(null);

export const GlobalAudioProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [currentTrack, setCurrentTrack] = useState<Track | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [playbackRate, setPlaybackRateState] = useState(1.7);
  const audioRef = useRef<HTMLAudioElement>(null);

  const loadTrack = useCallback((track: Track) => {
    setCurrentTrack(track);
    setIsPlaying(true);
    setCurrentTime(0);
    // Audio element will load and play via useEffect
  }, []);

  const togglePlay = useCallback(() => {
    setIsPlaying(prev => !prev);
  }, []);

  const seek = useCallback((time: number) => {
    setCurrentTime(Math.max(0, time));
    if (audioRef.current) {
      audioRef.current.currentTime = Math.max(0, time);
    }
  }, []);

  const skip = useCallback((deltaSeconds: number) => {
    const newTime = Math.max(0, currentTime + deltaSeconds);
    setCurrentTime(newTime);
    if (audioRef.current) {
      audioRef.current.currentTime = newTime;
    }
  }, [currentTime]);

  const setPlaybackRate = useCallback((rate: number) => {
    setPlaybackRateState(rate);
    if (audioRef.current) {
      audioRef.current.playbackRate = rate;
    }
  }, []);

  const close = useCallback(() => {
    setIsPlaying(false);
    setCurrentTrack(null);
    setCurrentTime(0);
    setDuration(0);
  }, []);

  // Handle audio element play/pause and src changes
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    // Reset time when track changes
    if (audio.src !== currentTrack?.mediaUrl) {
      audio.src = currentTrack?.mediaUrl || '';
      setCurrentTime(0);
      setDuration(0);
    }

    if (isPlaying && currentTrack) {
      audio.play().catch(() => {});
    } else {
      audio.pause();
    }
  }, [isPlaying, currentTrack]);

  // Handle playback rate
  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.playbackRate = playbackRate;
    }
  }, [playbackRate]);

  // Update current time while playing
  useEffect(() => {
    if (!isPlaying || !audioRef.current) return;

    const interval = setInterval(() => {
      if (audioRef.current) {
        setCurrentTime(audioRef.current.currentTime);
      }
    }, 100);

    return () => clearInterval(interval);
  }, [isPlaying, currentTrack]);

  // Handle track ended and time updates
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const handleEnded = () => {
      setIsPlaying(false);
      setCurrentTime(0);
    };

    const handleTimeUpdate = () => {
      setCurrentTime(audio.currentTime);
      setDuration(audio.duration || 0);
    };

    const handleLoadedMetadata = () => {
      setDuration(audio.duration || 0);
    };

    audio.addEventListener('ended', handleEnded);
    audio.addEventListener('timeupdate', handleTimeUpdate);
    audio.addEventListener('loadedmetadata', handleLoadedMetadata);

    return () => {
      audio.removeEventListener('ended', handleEnded);
      audio.removeEventListener('timeupdate', handleTimeUpdate);
      audio.removeEventListener('loadedmetadata', handleLoadedMetadata);
    };
  }, [currentTrack]);

  const value: GlobalAudioContextType = {
    currentTrack,
    isPlaying,
    currentTime,
    duration,
    playbackRate,
    loadTrack,
    togglePlay,
    seek,
    skip,
    setPlaybackRate,
    close,
    audioRef,
  };

  return (
    <GlobalAudioContext.Provider value={value}>
      {children}
      {/* Hidden global audio element */}
      <audio
        ref={audioRef}
        preload="metadata"
        style={{ display: 'none' }}
      />
    </GlobalAudioContext.Provider>
  );
};

export const useGlobalAudio = (): GlobalAudioContextType => {
  const context = useContext(GlobalAudioContext);
  if (!context) {
    throw new Error('useGlobalAudio must be used within GlobalAudioProvider');
  }
  return context;
};

export default GlobalAudioContext;
