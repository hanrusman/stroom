import React from 'react';
import { cn } from './cn';

export type BadgeTone = 'neutral' | 'accent' | 'tint';

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** `neutral` = surface pill, `accent` = filled brand-accent, `tint` = soft green tint. */
  tone?: BadgeTone;
  /** Optional leading dot (e.g. a live/status indicator). */
  dot?: boolean;
}

const TONES: Record<BadgeTone, string> = {
  neutral: 'bg-brand-surface text-brand-ink/70',
  accent: 'bg-brand-accent text-brand-cream',
  tint: 'bg-brand-green-tint text-brand-ink/75',
};

/**
 * A small uppercase mono label pill, used for topics, formats and statuses across Stroom.
 * Tiny type with wide tracking is intentional — keep the content to one or two words.
 * @category Primitives
 */
export function Badge({ tone = 'neutral', dot = false, className, children, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 px-3 py-1 rounded-full font-mono text-[10px] uppercase tracking-[0.18em] whitespace-nowrap',
        TONES[tone],
        className,
      )}
      {...props}
    >
      {dot && <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />}
      {children}
    </span>
  );
}
