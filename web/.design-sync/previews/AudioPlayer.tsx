import React from 'react';
import { AudioPlayer } from 'stroom-ds';

const track = {
  title: 'Acquired — De geschiedenis van TSMC',
  sourceName: 'Acquired',
};

export const Playing = () => (
  <div className="w-[640px] max-w-full rounded-2xl overflow-hidden border border-brand-ink/10">
    <AudioPlayer
      inline
      track={track}
      isPlaying
      currentTime={1245}
      duration={5400}
      playbackRate={1.5}
    />
  </div>
);

export const Paused = () => (
  <div className="w-[640px] max-w-full rounded-2xl overflow-hidden border border-brand-ink/10">
    <AudioPlayer
      inline
      track={{ title: 'Huygens digest — week 25', sourceName: 'Stroom' }}
      isPlaying={false}
      currentTime={0}
      duration={612}
      playbackRate={1.0}
    />
  </div>
);
