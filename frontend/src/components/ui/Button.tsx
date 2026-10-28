import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "./cn";

type Variant = "primary" | "secondary" | "ghost";
type Size = "sm" | "md" | "icon";

const variants: Record<Variant, string> = {
  primary:
    "bg-accent text-accent-fg hover:bg-accent-hover shadow-[inset_0_1px_0_oklch(1_0_0/0.15)]",
  secondary:
    "bg-surface-1 text-fg border border-border hover:bg-surface-2 hover:border-border-strong",
  ghost: "text-fg-muted hover:bg-surface-3 hover:text-fg",
};

const sizes: Record<Size, string> = {
  sm: "h-7 px-2.5 text-xs gap-1.5",
  md: "h-8 px-3 text-sm gap-2",
  icon: "h-8 w-8 justify-center",
};

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", className, type = "button", ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        "inline-flex shrink-0 select-none items-center rounded-control font-medium transition-colors duration-150",
        "disabled:pointer-events-none disabled:opacity-50",
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    />
  );
});
