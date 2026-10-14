import React from 'react';
import { cn } from './cn';

export type CardVariant = 'surface' | 'tint' | 'outline';

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  /** `surface` = filled brand surface, `tint` = soft green-tint panel, `outline` = cream with hairline border. */
  variant?: CardVariant;
  /** Use the larger 32px radius (rounded-3xl) instead of the default 24px (rounded-2xl). */
  large?: boolean;
  /** Add interactive hover elevation + pointer cursor (for clickable cards). */
  interactive?: boolean;
}

const VARIANTS: Record<CardVariant, string> = {
  surface: 'bg-brand-surface border border-brand-ink/5',
  tint: 'bg-brand-green-tint border border-brand-ink/5',
  outline: 'bg-brand-cream border border-brand-ink/10',
};

/**
 * The base rounded surface container used throughout Stroom. Compose headings, text and
 * actions inside it; reach for `interactive` when the whole card is a link/button.
 * @category Primitives
 */
export function Card({
  variant = 'surface',
  large = false,
  interactive = false,
  className,
  children,
  ...props
}: CardProps) {
  return (
    <div
      className={cn(
        'overflow-hidden',
        large ? 'rounded-3xl' : 'rounded-2xl',
        VARIANTS[variant],
        interactive && 'hover:shadow-md transition-all cursor-pointer',
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}
