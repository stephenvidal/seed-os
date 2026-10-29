import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "./cn";

/**
 * Renders model output as Markdown (GitHub flavour). Raw HTML in the text is not
 * rendered, and react-markdown drops unsafe link schemes such as javascript:.
 */
export function Markdown({ text, className }: { text: string; className?: string }) {
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
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
