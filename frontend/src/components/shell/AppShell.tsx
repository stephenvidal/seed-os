import { useCallback, useState } from "react";
import { Outlet, useNavigate } from "react-router-dom";
import { NAV } from "../../lib/nav";
import { useGlobalShortcuts } from "../../lib/shortcuts";
import { CommandPalette } from "./CommandPalette";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

const COLLAPSE_KEY = "seed.sidebar.collapsed";

export function AppShell() {
  const navigate = useNavigate();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === "1";
    } catch {
      return false;
    }
  });

  const toggleSidebar = useCallback(() => {
    setCollapsed((c) => {
      try {
        localStorage.setItem(COLLAPSE_KEY, c ? "0" : "1");
      } catch {
        // Non-persistent in private mode.
      }
      return !c;
    });
  }, []);

  const onChord = useCallback(
    (key: string) => {
      const target = NAV.find((n) => n.chord === key);
      if (target) navigate(target.path);
    },
    [navigate],
  );
  const openPalette = useCallback(() => setPaletteOpen((o) => !o), []);
  useGlobalShortcuts({ onPalette: openPalette, onToggleSidebar: toggleSidebar, onChord });

  return (
    <div className="flex h-full">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-control focus:bg-surface-1 focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <Sidebar
        collapsed={collapsed}
        onToggleCollapsed={toggleSidebar}
        mobileOpen={mobileOpen}
        onCloseMobile={() => setMobileOpen(false)}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar
          onOpenPalette={() => setPaletteOpen(true)}
          onOpenMobileNav={() => setMobileOpen(true)}
        />
        <main id="main" className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1200px] px-4 py-6 sm:px-8 sm:py-8">
            <Outlet />
          </div>
        </main>
      </div>
      <CommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        onToggleSidebar={toggleSidebar}
      />
    </div>
  );
}
