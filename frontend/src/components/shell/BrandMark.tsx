/** SEED mark: an open arc (growth) completed by a single point (the seed of intent). */
export function BrandMark({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden>
      <path
        d="M16 6a10 10 0 1 0 10 10"
        fill="none"
        stroke="currentColor"
        strokeWidth="3.2"
        strokeLinecap="round"
      />
      <circle cx="23.5" cy="8.5" r="2.7" fill="var(--accent)" />
    </svg>
  );
}
