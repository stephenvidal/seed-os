import { Menu, Moon, Search, Sun } from "lucide-react";
import { useLocation } from "react-router-dom";
import { navForPath } from "../../lib/nav";
import { modLabel } from "../../lib/shortcuts";
import { useTheme } from "../../lib/theme";
import { Button } from "../ui/Button";
import { Kbd } from "../ui/Kbd";
import { UserMenu } from "./UserMenu";

export function Topbar({
  onOpenPalette,
  onOpenMobileNav,
}: {
  onOpenPalette: () => void;
  onOpenMobileNav: () => void;
}) {
  const { pathname } = useLocation();
  const current = navForPath(pathname);
  const { resolved, toggle } = useTheme();

  return (
    <header className="sticky top-0 z-30 flex h-12 shrink-0 items-center gap-2 border-b border-border bg-bg/85 px-3 backdrop-blur-md sm:px-4">
      <Button
        variant="ghost"
        size="icon"
        className="md:hidden"
        onClick={onOpenMobileNav}
        aria-label="Open navigation"
      >
        <Menu size={16} />
      </Button>
      <div className="flex min-w-0 items-center gap-1.5 text-sm">
        <span className="hidden text-fg-subtle sm:inline">Workspace</span>
        <span className="hidden text-fg-subtle sm:inline" aria-hidden>
          /
        </span>
        <span className="truncate font-medium text-fg">{current?.label ?? "Not found"}</span>
      </div>
      <div className="ml-auto flex items-center gap-1.5">
        <button
          type="button"
          onClick={onOpenPalette}
          className="hidden h-8 w-64 items-center gap-2 rounded-control border border-border bg-surface-1 px-2.5 text-sm text-fg-subtle transition-colors hover:border-border-strong hover:text-fg-muted sm:flex"
        >
          <Search size={14} aria-hidden />
          <span className="truncate whitespace-nowrap">Search or jump to…</span>
          <span className="ml-auto flex gap-0.5">
            <Kbd>{modLabel}</Kbd>
            <Kbd>K</Kbd>
          </span>
        </button>
        <Button
          variant="ghost"
          size="icon"
          className="sm:hidden"
          onClick={onOpenPalette}
          aria-label="Open command palette"
        >
          <Search size={16} />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={toggle}
          aria-label={resolved === "dark" ? "Switch to light theme" : "Switch to dark theme"}
        >
          {resolved === "dark" ? <Sun size={16} /> : <Moon size={16} />}
        </Button>
        <UserMenu />
      </div>
    </header>
  );
}
