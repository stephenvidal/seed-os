import { useEffect } from "react";

export const isMac = typeof navigator !== "undefined" && /Mac|iP(hone|ad)/.test(navigator.platform);
export const modLabel = isMac ? "⌘" : "Ctrl";

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  return el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName);
}

type Handlers = {
  onPalette: () => void;
  onToggleSidebar: () => void;
  onChord: (key: string) => void;
};

/** Global shortcuts: Mod+K palette, Mod+B sidebar, "G then X" navigation. */
export function useGlobalShortcuts({ onPalette, onToggleSidebar, onChord }: Handlers) {
  useEffect(() => {
    let chordUntil = 0;
    const onKey = (e: KeyboardEvent) => {
      const mod = isMac ? e.metaKey : e.ctrlKey;
      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        onPalette();
        return;
      }
      if (mod && e.key.toLowerCase() === "b") {
        e.preventDefault();
        onToggleSidebar();
        return;
      }
      if (e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target)) return;
      if (Date.now() < chordUntil) {
        chordUntil = 0;
        onChord(e.key.toLowerCase());
        return;
      }
      if (e.key.toLowerCase() === "g") chordUntil = Date.now() + 1200;
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onPalette, onToggleSidebar, onChord]);
}
