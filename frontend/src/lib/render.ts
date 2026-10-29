/** Helpers for showing model output rendered: which fenced blocks have a view, and
 *  how inline HTML is made safe and mobile-responsive before it goes in a frame. */

export type RenderKind = "html" | "markdown";

/** Fence languages that render. SVG is HTML to a browser, so it shares the frame. */
const LANGUAGES: Record<string, RenderKind> = {
  html: "html",
  htm: "html",
  svg: "html",
  markdown: "markdown",
  md: "markdown",
};

export function kindForLanguage(language: string | undefined): RenderKind | null {
  return (language && LANGUAGES[language.toLowerCase()]) || null;
}

/** Tags a model opens an answer with when it writes a page or a fragment of one. */
const HTML_START =
  /^\s*<(?:!doctype\s+html|html|head|body|style|div|main|article|section|header|nav|table|svg|h[1-6]|p)[\s>/]/i;

/** True when the whole text is HTML: a page, or a fragment that opens with a tag. */
export function isHtmlDocument(text: string): boolean {
  return HTML_START.test(text);
}

/**
 * Prose followed by a page: the text before the first line that opens a whole HTML
 * document, and the document from there. Without this the Markdown renderer, which
 * drops raw HTML, shows the page as nothing.
 */
export function splitHtmlPage(text: string): { prose: string; html: string } | null {
  const m = /^[ \t]*<(?:!doctype\s+html|html[\s>])/im.exec(text);
  if (!m) return null;
  // A page inside a code fence is already shown as a block.
  if (/^```/m.test(text.slice(0, m.index))) return null;
  return { prose: text.slice(0, m.index).trimEnd(), html: text.slice(m.index) };
}

/**
 * Inline HTML has no network and no scripts: it can only show what it contains.
 * Styles and data: images are allowed because generated pages need both.
 */
const INLINE_CSP =
  "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; media-src data:";

/** Low-specificity defaults so a page that forgot to be responsive still fits a phone. */
const BASE_STYLE =
  ":where(*,*::before,*::after){box-sizing:border-box}" +
  ":where(html){-webkit-text-size-adjust:100%}" +
  ":where(body){margin:0;padding:12px;font-family:system-ui,sans-serif;line-height:1.5;overflow-wrap:anywhere}" +
  ":where(img,svg,video,canvas,iframe){max-width:100%;height:auto}" +
  ":where(table){display:block;max-width:100%;overflow-x:auto}" +
  ":where(pre){max-width:100%;overflow-x:auto}";

const HEAD =
  `<meta http-equiv="Content-Security-Policy" content="${INLINE_CSP}">` +
  `<meta name="viewport" content="width=device-width, initial-scale=1">` +
  `<style>${BASE_STYLE}</style>`;

/**
 * The document to put in a sandboxed frame's srcdoc. The policy meta comes first so
 * nothing in the model's HTML can run before it; the viewport meta and base style
 * make the page responsive.
 */
export function prepareHtml(source: string): string {
  const head = /<head[^>]*>/i.exec(source);
  if (head) return source.replace(head[0], head[0] + HEAD);
  const html = /<html[^>]*>/i.exec(source);
  if (html) return source.replace(html[0], `${html[0]}<head>${HEAD}</head>`);
  const doctype = /^\s*<!doctype[^>]*>/i.exec(source);
  const body = `<head>${HEAD}</head><body>`;
  if (doctype) return doctype[0] + body + source.slice(doctype[0].length) + "</body>";
  return `<!doctype html><html>${body}${source}</body></html>`;
}

/** Width of the phone view, and of the virtual window the desktop view lays out in. */
export const PHONE_WIDTH = 390;
export const DESKTOP_WIDTH = 1024;

/** The frame's layout width and the scale that fits it in `available` pixels. */
export function frameLayout(view: "phone" | "desktop", available: number) {
  const width = view === "phone" ? Math.min(PHONE_WIDTH, available) : DESKTOP_WIDTH;
  const scale = Math.min(1, available / width);
  return { width, scale };
}
