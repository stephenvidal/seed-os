import { X } from "lucide-react";
import { useEffect, useId, useRef } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";

/**
 * A dialog over the page. Escape or a click on the backdrop closes it, focus moves in
 * and returns to where it was, and the page behind stays put.
 */
export function Modal({
  title,
  actions,
  onClose,
  children,
}: {
  title: string;
  actions?: ReactNode;
  onClose: () => void;
  children: ReactNode;
}) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });

  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close.current();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      before?.focus();
    };
  }, []);

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-2 sm:p-6"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="flex max-h-full w-full max-w-5xl flex-col overflow-hidden rounded-panel border border-border bg-surface-1 shadow-xl outline-none"
      >
        <div className="flex items-center gap-3 border-b border-border px-4 py-2.5">
          <h2 id={titleId} className="min-w-0 flex-1 truncate font-mono text-sm text-fg">
            {title}
          </h2>
          {actions}
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="rounded p-1 text-fg-muted hover:text-fg"
          >
            <X size={16} aria-hidden />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>,
    document.body,
  );
}
