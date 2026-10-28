import * as Menu from "@radix-ui/react-dropdown-menu";
import { Check, LogOut, Monitor, Moon, Sun } from "lucide-react";
import { useLogout, useSession } from "../../lib/auth";
import { useTheme } from "../../lib/theme";
import type { ThemePreference } from "../../lib/theme";

const itemCls =
  "flex h-8 cursor-default select-none items-center gap-2 rounded-[5px] px-2 text-sm text-fg outline-none data-[highlighted]:bg-surface-3";

const THEMES: { value: ThemePreference; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

export function UserMenu() {
  const { data: me } = useSession();
  const logout = useLogout();
  const { preference, setPreference } = useTheme();
  const initial = me?.username.slice(0, 1).toUpperCase() ?? "?";

  return (
    <Menu.Root>
      <Menu.Trigger
        aria-label="Account menu"
        className="grid h-7 w-7 place-items-center rounded-full bg-accent-soft text-xs font-semibold text-accent-soft-fg outline-none ring-offset-2 ring-offset-bg focus-visible:ring-2 focus-visible:ring-ring"
      >
        {initial}
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content
          align="end"
          sideOffset={6}
          className="z-50 w-56 rounded-panel border border-border bg-surface-1 p-1 shadow-pop"
        >
          <div className="px-2 py-1.5">
            <p className="text-sm font-medium text-fg">{me?.username}</p>
            <p className="text-xs capitalize text-fg-subtle">{me?.role}</p>
          </div>
          <Menu.Separator className="my-1 h-px bg-border" />
          <Menu.Label className="px-2 py-1 text-2xs font-medium uppercase tracking-[0.08em] text-fg-subtle">
            Theme
          </Menu.Label>
          {THEMES.map(({ value, label, icon: Icon }) => (
            <Menu.Item key={value} className={itemCls} onSelect={() => setPreference(value)}>
              <Icon size={14} className="text-fg-muted" aria-hidden />
              {label}
              {preference === value && (
                <Check size={14} className="ml-auto text-accent" aria-label="Selected" />
              )}
            </Menu.Item>
          ))}
          <Menu.Separator className="my-1 h-px bg-border" />
          <Menu.Item className={itemCls} onSelect={() => logout.mutate()}>
            <LogOut size={14} className="text-fg-muted" aria-hidden />
            Sign out
          </Menu.Item>
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  );
}
