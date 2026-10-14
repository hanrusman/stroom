import React from 'react';
import { cn } from './cn';

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  /** Optional leading icon (e.g. a lucide `<Search />`), positioned inside the field. */
  icon?: React.ReactNode;
}

/**
 * Single-line text field with Stroom's rounded surface styling and accent focus ring.
 * Pass `icon` for a leading adornment (e.g. a search field).
 * @category Primitives
 */
export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ icon, className, ...props }, ref) => {
    const field = (
      <input
        ref={ref}
        className={cn(
          'w-full px-4 py-3 rounded-xl bg-brand-surface border border-brand-ink/10 font-serif text-[14px] text-brand-ink',
          'placeholder:text-brand-ink/30 focus:outline-none focus:border-brand-accent/40 transition disabled:opacity-60',
          icon ? 'pl-11' : '',
          className,
        )}
        {...props}
      />
    );
    if (!icon) return field;
    return (
      <div className="relative">
        <span className="absolute left-4 top-1/2 -translate-y-1/2 text-brand-ink/40 pointer-events-none">
          {icon}
        </span>
        {field}
      </div>
    );
  },
);
Input.displayName = 'Input';
