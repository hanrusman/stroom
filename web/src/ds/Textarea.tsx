import React from 'react';
import { cn } from './cn';

export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {}

/**
 * Multi-line text field matching {@link Input}'s styling, with the larger 24px radius
 * used for composer/prompt areas. Resizing is disabled by default for a stable layout.
 * @category Primitives
 */
export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        'w-full px-4 py-3 rounded-2xl bg-brand-surface border border-brand-ink/10 font-serif text-[14px] text-brand-ink',
        'placeholder:text-brand-ink/30 focus:outline-none focus:border-brand-accent/40 resize-none transition disabled:opacity-60',
        className,
      )}
      {...props}
    />
  ),
);
Textarea.displayName = 'Textarea';
