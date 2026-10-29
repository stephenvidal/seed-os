import { Code, Eye, Monitor, Smartphone } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { frameLayout, prepareHtml } from "../../lib/render";
import { cn } from "./cn";

const PHONE_QUERY = "(max-width: 640px)";
const FRAME_HEIGHT = 480;

type Option<T extends string> = { value: T; label: string; icon: ReactNode };

/** A small two-way switch. Each side is a button whose pressed state is announced. */
function Switch<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: [Option<T>, Option<T>];
  onChange: (v: T) => void;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="inline-flex rounded-control border border-border"
    >
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "inline-flex h-6 items-center gap-1 px-2 text-2xs font-medium first:rounded-l-control last:rounded-r-control",
            value === o.value ? "bg-surface-3 text-fg" : "text-fg-muted hover:text-fg",
          )}
        >
          {o.icon}
          {o.label}
        </button>
      ))}
    </div>
  );
}

export type ViewMode = "rendered" | "source";

/** Rendered / Source switch shared by every place that shows model output. */
export function ViewSwitch({
  value,
  onChange,
}: {
  value: ViewMode;
  onChange: (v: ViewMode) => void;
}) {
  return (
    <Switch
      label="View"
      value={value}
      onChange={onChange}
      options={[
        { value: "rendered", label: "Rendered", icon: <Eye size={11} aria-hidden /> },
        { value: "source", label: "Source", icon: <Code size={11} aria-hidden /> },
      ]}
    />
  );
}

export function SourceView({ text, className }: { text: string; className?: string }) {
  return (
    <pre
      className={cn(
        "max-h-[32rem] overflow-auto font-mono text-xs leading-relaxed whitespace-pre-wrap break-words text-fg",
        className,
      )}
    >
      {text}
    </pre>
  );
}

/**
 * HTML in a sandboxed frame, shown at the viewer's device width first: the phone
 * layout on a phone, the desktop layout elsewhere, with a switch for the other.
 * Give it `source` (inline HTML, no scripts, no network) or `src` (a Studio preview,
 * which carries its own policy). The frame never gets allow-same-origin.
 */
export function HtmlFrame({
  title,
  source,
  src,
}: {
  title: string;
  source?: string;
  src?: string;
}) {
  const [view, setView] = useState<"phone" | "desktop">(() =>
    matchMedia(PHONE_QUERY).matches ? "phone" : "desktop",
  );
  const box = useRef<HTMLDivElement>(null);
  const [available, setAvailable] = useState(DEFAULT_AVAILABLE);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => setAvailable(el.clientWidth || DEFAULT_AVAILABLE);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const { width, scale } = frameLayout(view, available);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex justify-end">
        <Switch
          label="Device view"
          value={view}
          onChange={setView}
          options={[
            { value: "phone", label: "Phone", icon: <Smartphone size={11} aria-hidden /> },
            { value: "desktop", label: "Desktop", icon: <Monitor size={11} aria-hidden /> },
          ]}
        />
      </div>
      <div ref={box} className="w-full">
        <div
          className="mx-auto overflow-hidden rounded-control border border-border bg-white"
          style={{ width: width * scale, height: FRAME_HEIGHT }}
        >
          <iframe
            title={title}
            {...(src !== undefined
              ? { src, sandbox: "allow-scripts allow-modals" }
              : { srcDoc: prepareHtml(source ?? ""), sandbox: "" })}
            className="block border-0 bg-white"
            style={{
              width,
              height: FRAME_HEIGHT / scale,
              transform: `scale(${scale})`,
              transformOrigin: "top left",
            }}
          />
        </div>
      </div>
    </div>
  );
}

const DEFAULT_AVAILABLE = 640;

/** One piece of output with its Rendered / Source switch, rendered first. */
export function Rendered({
  source,
  title,
  render,
}: {
  source: string;
  title: string;
  render: ReactNode;
}) {
  const [mode, setMode] = useState<ViewMode>("rendered");
  return (
    <figure className="not-prose my-2 overflow-hidden rounded-control border border-border bg-surface-1">
      <figcaption className="flex items-center justify-between border-b border-border px-2 py-1">
        <span className="text-2xs text-fg-muted">{title}</span>
        <ViewSwitch value={mode} onChange={setMode} />
      </figcaption>
      <div className="p-2">{mode === "rendered" ? render : <SourceView text={source} />}</div>
    </figure>
  );
}
