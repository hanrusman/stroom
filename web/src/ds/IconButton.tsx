import React from 'react';
import { cn } from './cn';

export type IconButtonSize = 'sm' | 'md' | 'lg';

export interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Accessible label — required, since the button has no visible text. */
  'aria-label': string;
  /** The icon to render, typically a lucide-react element (e.g. `<X size={18} />`). */
  children: React.ReactNode;
  /** `sm` = 36px, `md` = 40px, `lg` = 44px circular target. */
  size?: IconButtonSize;
  /** Accent-filled circular button (e.g. a primary play control) instead of the default ghost hover. */
  filled?: boolean;
}

const SIZES: Record<IconButtonSize, string> = {
  sm: 'w-9 h-9',
  md: 'w-10 h-10',
  lg: 'w-11 h-11',
};

/**
 * A circular icon-only button. Default style is a transparent target that tints the
 * brand surface on hover; `filled` renders the accent-filled circle used for primary
 * media controls. Always pass `aria-label`.
 * @category Primitives
 */
export function IconButton({
  size = 'md',
  filled = false,
  className,
  children,
  ...props
}: IconButtonProps) {
  return (
    <button
      className={cn(
        'rounded-full flex items-center justify-center transition disabled:opacity-50',
        SIZES[size],
        filled
          ? 'bg-brand-accent text-brand-cream hover:opacity-90'
          : 'text-brand-ink/65 hover:bg-brand-ink/5',
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}
