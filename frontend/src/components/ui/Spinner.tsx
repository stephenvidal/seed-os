export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <span
      role="status"
      aria-label={label}
      className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-[1.5px] border-border-strong border-t-accent"
    />
  );
}
