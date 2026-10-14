import React from 'react';
import { cn } from './cn';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost';
export type ButtonSize = 'sm' | 'md';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Visual emphasis. `primary` is the accent-filled call to action; `secondary` is the
   *  surface pill that fills with accent on hover; `ghost` is a low-emphasis text button. */
  variant?: ButtonVariant;
  /** `md` is the standard pill; `sm` is the compact rail/toolbar size. */
  size?: ButtonSize;
  /** Optional leading element, typically a lucide-react icon (e.g. `<Sparkles size={14} />`). */
  icon?: React.ReactNode;
}

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    'bg-brand-accent text-brand-cream hover:opacity-90',
  secondary:
    'bg-brand-surface border border-brand-ink/15 text-brand-ink hover:bg-brand-accent hover:text-brand-cream hover:border-brand-accent',
  ghost:
    'text-brand-ink/60 hover:text-brand-ink',
};

const SIZES: Record<ButtonSize, string> = {
  md: 'px-6 py-3 text-[11px] tracking-[0.22em]',
  sm: 'px-4 py-2 text-[10px] tracking-[0.18em]',
};

/**
 * Stroom's signature pill button: rounded-full with a JetBrains-Mono uppercase label and
 * wide letter-tracking. Use `primary` for the main action on a view, `secondary` for
 * supporting actions, and `ghost` for inline/low-emphasis controls.
 * @category Primitives
 */
export function Button({
  variant = 'primary',
  size = 'md',
  icon,
  className,
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(
        'rounded-full font-mono uppercase inline-flex items-center justify-center gap-2 transition disabled:opacity-50',
        variant === 'ghost' ? '' : SIZES[size],
        variant === 'ghost' && 'px-4 py-2 text-sm normal-case tracking-normal',
        VARIANTS[variant],
        className,
      )}
      {...props}
    >
      {icon}
      {children}
    </button>
  );
}
