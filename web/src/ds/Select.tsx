import React from 'react';
import { cn } from './cn';

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps
  extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, 'children'> {
  /** Options to render. Alternatively pass `<option>` children via `children`. */
  options?: SelectOption[];
  children?: React.ReactNode;
}

/**
 * Styled native `<select>` with Stroom's surface field styling. Generalises the app's
 * model picker — pass `options`, or `<option>` children for full control.
 * @category Primitives
 */
export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ options, className, children, ...props }, ref) => (
    <select
      ref={ref}
      className={cn(
        'w-full px-4 py-2.5 rounded-full bg-brand-surface border border-brand-ink/10 font-mono text-[11px] uppercase tracking-[0.15em] text-brand-ink/70',
        'focus:outline-none focus:border-brand-accent/40 cursor-pointer disabled:opacity-50',
        className,
      )}
      {...props}
    >
      {options
        ? options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))
        : children}
    </select>
  ),
);
Select.displayName = 'Select';
