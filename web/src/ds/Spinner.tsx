import React from 'react';
import { Loader2 } from 'lucide-react';
import { cn } from './cn';

export interface SpinnerProps {
  /** Pixel size of the spinner glyph. Defaults to 18. */
  size?: number;
  /** Accessible label announced to screen readers. Defaults to "Bezig met laden". */
  label?: string;
  className?: string;
}

/**
 * Indeterminate loading indicator — the spinning lucide `Loader2` used for in-flight
 * actions. Inherits the current text color, so place it inside accent or ink contexts.
 * @category Primitives
 */
export function Spinner({ size = 18, label = 'Bezig met laden', className }: SpinnerProps) {
  return (
    <span role="status" aria-label={label} className={cn('inline-flex text-brand-accent', className)}>
      <Loader2 size={size} className="animate-spin" />
    </span>
  );
}
