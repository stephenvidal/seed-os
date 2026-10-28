import { Command } from "cmdk";
import { CornerDownLeft, LogOut, Monitor, Moon, PanelLeft, Sun } from "lucide-react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useLogout } from "../../lib/auth";
import { NAV } from "../../lib/nav";
import { useTheme } from "../../lib/theme";
import { Kbd } from "../ui/Kbd";

const itemCls =
  "flex h-9 cursor-default select-none items-center gap-3 rounded-control px-2.5 text-sm text-fg data-[selected=true]:bg-surface-3";
const groupCls =
  "[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:text-2xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.08em] [&_[cmdk-group-heading]]:text-fg-subtle";

export function CommandPalette({
  open,
  onOpenChange,
  onToggleSidebar,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onToggleSidebar: () => void;
}) {
  const navigate = useNavigate();
  const { setPreference } = useTheme();
  const logout = useLogout();

  const run = (fn: () => void) => () => {
    onOpenChange(false);
    fn();
  };

  const action = (label: string, icon: ReactNode, fn: () => void, hint?: ReactNode) => (
    <Command.Item key={label} value={label} onSelect={run(fn)} className={itemCls}>
      <span className="text-fg-muted">{icon}</span>
      {label}
      {hint && <span className="ml-auto flex gap-0.5">{hint}</span>}
    </Command.Item>
  );

  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label="Command palette"
      overlayClassName="fixed inset-0 z-50 bg-scrim"
      contentClassName="fixed left-1/2 top-[14vh] z-50 w-[min(640px,calc(100vw-24px))] -translate-x-1/2 overflow-hidden rounded-panel border border-border bg-surface-1 shadow-pop"
    >
      <Command.Input
        placeholder="Type a command or search…"
        className="h-12 w-full border-b border-border bg-transparent px-4 text-base text-fg outline-none placeholder:text-fg-subtle"
      />
      <Command.List className="max-h-[min(420px,60vh)] overflow-y-auto p-1.5">
        <Command.Empty className="px-3 py-8 text-center text-sm text-fg-muted">
          No results.
        </Command.Empty>
        <Command.Group heading="Navigate" className={groupCls}>
          {NAV.map((n) => (
            <Command.Item
              key={n.path}
              value={`Go to ${n.label} ${n.description}`}
              onSelect={run(() => navigate(n.path))}
              className={itemCls}
            >
              <n.icon size={16} strokeWidth={1.75} className="text-fg-muted" aria-hidden />
              <span>{n.label}</span>
              <span className="hidden truncate text-fg-subtle sm:inline">{n.description}</span>
              <span className="ml-auto flex gap-0.5">
                <Kbd>G</Kbd>
                <Kbd>{n.chord.toUpperCase()}</Kbd>
              </span>
            </Command.Item>
          ))}
        </Command.Group>
        <Command.Group heading="Appearance" className={groupCls}>
          {action("Use light theme", <Sun size={16} />, () => setPreference("light"))}
          {action("Use dark theme", <Moon size={16} />, () => setPreference("dark"))}
          {action("Match system theme", <Monitor size={16} />, () => setPreference("system"))}
          {action("Toggle sidebar", <PanelLeft size={16} />, onToggleSidebar)}
        </Command.Group>
        <Command.Group heading="Account" className={groupCls}>
          {action("Sign out", <LogOut size={16} />, () => logout.mutate())}
        </Command.Group>
      </Command.List>
      <div className="flex h-9 items-center gap-3 border-t border-border px-3 text-2xs text-fg-subtle">
        <span className="flex items-center gap-1">
          <Kbd>↑</Kbd>
          <Kbd>↓</Kbd> navigate
        </span>
        <span className="flex items-center gap-1">
          <Kbd>
            <CornerDownLeft size={10} />
          </Kbd>{" "}
          select
        </span>
        <span className="flex items-center gap-1">
          <Kbd>Esc</Kbd> close
        </span>
      </div>
    </Command.Dialog>
  );
}
