import { isValidElement, useState } from "react";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { isHtmlDocument, kindForLanguage } from "../../lib/render";
import { cn } from "./cn";
import { HtmlFrame, Rendered, SourceView, ViewSwitch } from "./Rendered";
import type { ViewMode } from "./Rendered";

/** The fenced block's language and text, when `pre`'s child is a `code` element. */
function fence(children: ReactNode): { language?: string; text: string } | null {
  if (!isValidElement<{ className?: string; children?: ReactNode }>(children)) return null;
  const { className, children: text } = children.props;
  if (typeof text !== "string") return null;
  return { language: /language-(\S+)/.exec(className ?? "")?.[1], text: text.replace(/\n$/, "") };
}

function Body({ text, className, live }: { text: string; className?: string; live: boolean }) {
  if (!live && isHtmlDocument(text)) return <HtmlFrame title="Rendered HTML" source={text} />;
  return (
    <div className={cn("markdown text-sm leading-6 text-fg", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer nofollow">
              {children}
            </a>
          ),
          // A fenced html, svg or markdown block is shown rendered, with a switch to its
          // source. Any other block stays code.
          pre: ({ children }) => {
            const f = fence(children);
            const kind = f && kindForLanguage(f.language);
            if (live || !f || !kind) return <pre>{children}</pre>;
            return kind === "html" ? (
              <Rendered
                source={f.text}
                title={f.language!.toUpperCase()}
                render={<HtmlFrame title={`Rendered ${f.language}`} source={f.text} />}
              />
            ) : (
              <Rendered source={f.text} title="Markdown" render={<Markdown text={f.text} />} />
            );
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

/**
 * Renders model output as Markdown (GitHub flavour): tables, lists and code as
 * formatted text, fenced HTML/SVG/Markdown as a rendered view, and an answer that is
 * a whole HTML page as a page. Raw HTML in the text is never injected into SEED's own
 * page, and react-markdown drops unsafe link schemes such as javascript:. HTML only
 * runs inside a sandboxed frame (see Rendered.tsx).
 *
 * With `toggle`, a Rendered / Source switch shows the text as written instead.
 */
export function Markdown({
  text,
  className,
  toggle = false,
  live = false,
}: {
  text: string;
  className?: string;
  toggle?: boolean;
  /** The text is still arriving: show HTML as code until it is complete. */
  live?: boolean;
}) {
  const [mode, setMode] = useState<ViewMode>("rendered");
  if (!toggle) return <Body text={text} className={className} live={live} />;
  return (
    <div className="group/answer flex flex-col gap-1">
      <div className="flex justify-end">
        <ViewSwitch value={mode} onChange={setMode} />
      </div>
      {mode === "rendered" ? (
        <Body text={text} className={className} live={live} />
      ) : (
        <SourceView text={text} />
      )}
    </div>
  );
}
