import * as Tooltip from "@radix-ui/react-tooltip";
import { PanelLeftClose, PanelLeftOpen, X } from "lucide-react";
import { NavLink } from "react-router-dom";
import { NAV } from "../../lib/nav";
import type { NavItem } from "../../lib/nav";
import { modLabel } from "../../lib/shortcuts";
import { Button } from "../ui/Button";
import { cn } from "../ui/cn";
import { Kbd } from "../ui/Kbd";
import { BrandMark } from "./BrandMark";

type Props = {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
};

function Item({
  item,
  collapsed,
  onNavigate,
}: {
  item: NavItem;
  collapsed: boolean;
  onNavigate: () => void;
}) {
  const Icon = item.icon;
  const link = (
    <NavLink
      to={item.path}
      end={item.path === "/"}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          "group relative flex h-8 items-center gap-2.5 rounded-control px-2.5 text-sm transition-colors duration-150",
          isActive
            ? "bg-surface-3 font-medium text-fg"
            : "text-fg-muted hover:bg-surface-2 hover:text-fg",
          collapsed && "justify-center px-0",
        )
      }
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span
              aria-hidden
              className="absolute -left-2 top-1.5 bottom-1.5 w-[2px] rounded-full bg-accent"
            />
          )}
          <Icon
            size={16}
            strokeWidth={1.75}
            className={isActive ? "text-accent" : undefined}
            aria-hidden
          />
          <span className={cn("truncate", collapsed && "sr-only")}>{item.label}</span>
        </>
      )}
    </NavLink>
  );
  if (!collapsed) return link;
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>{link}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content
          side="right"
          sideOffset={8}
          className="z-50 flex items-center gap-2 rounded-control border border-border bg-surface-1 px-2 py-1 text-xs text-fg shadow-pop"
        >
          {item.label}
          <span className="flex gap-0.5">
            <Kbd>G</Kbd>
            <Kbd>{item.chord.toUpperCase()}</Kbd>
          </span>
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

function NavGroups({ collapsed, onNavigate }: { collapsed: boolean; onNavigate: () => void }) {
  return (
    <nav aria-label="Primary" className="flex flex-1 flex-col gap-6 overflow-y-auto px-3 py-3">
      {(["workspace", "configure"] as const).map((group) => (
        <div key={group} className="flex flex-col gap-0.5">
          <p
            className={cn(
              "mb-1 px-2.5 text-2xs font-medium uppercase tracking-[0.08em] text-fg-subtle",
              collapsed && "sr-only",
            )}
          >
            {group === "workspace" ? "Workspace" : "Configure"}
          </p>
          {NAV.filter((n) => n.group === group).map((item) => (
            <Item key={item.path} item={item} collapsed={collapsed} onNavigate={onNavigate} />
          ))}
        </div>
      ))}
    </nav>
  );
}

export function Sidebar({ collapsed, onToggleCollapsed, mobileOpen, onCloseMobile }: Props) {
  return (
    <Tooltip.Provider delayDuration={300}>
      {/* Desktop */}
      <aside
        className={cn(
          "hidden shrink-0 flex-col border-r border-border bg-surface-1 transition-[width] duration-200 ease-out-quint md:flex",
          collapsed ? "w-[60px]" : "w-[232px]",
        )}
      >
        <div
          className={cn("flex h-12 items-center gap-2 px-4", collapsed && "justify-center px-0")}
        >
          <span className="text-fg">
            <BrandMark />
          </span>
          {!collapsed && (
            <span className="text-[15px] font-semibold tracking-[0.12em] text-fg">SEED</span>
          )}
        </div>
        <NavGroups collapsed={collapsed} onNavigate={() => {}} />
        <div
          className={cn(
            "flex items-center border-t border-border p-2",
            collapsed ? "justify-center" : "justify-between",
          )}
        >
          {!collapsed && (
            <span className="flex items-center gap-1 pl-1.5 text-2xs text-fg-subtle">
              <Kbd>{modLabel}</Kbd>
              <Kbd>B</Kbd>
              <span className="ml-1">to collapse</span>
            </span>
          )}
          <Button
            variant="ghost"
            size="icon"
            onClick={onToggleCollapsed}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          </Button>
        </div>
      </aside>

      {/* Mobile drawer */}
      <div
        className={cn("fixed inset-0 z-40 md:hidden", mobileOpen ? "visible" : "invisible")}
        aria-hidden={!mobileOpen}
      >
        <div
          className={cn(
            "absolute inset-0 bg-scrim transition-opacity duration-200",
            mobileOpen ? "opacity-100" : "opacity-0",
          )}
          onClick={onCloseMobile}
        />
        <aside
          role="dialog"
          aria-modal="true"
          aria-label="Navigation"
          className={cn(
            "absolute inset-y-0 left-0 flex w-[272px] flex-col border-r border-border bg-surface-1 shadow-pop transition-transform duration-250 ease-out-quint",
            mobileOpen ? "translate-x-0" : "-translate-x-full",
          )}
        >
          <div className="flex h-12 items-center justify-between px-4">
            <span className="flex items-center gap-2">
              <BrandMark />
              <span className="text-[15px] font-semibold tracking-[0.12em]">SEED</span>
            </span>
            <Button
              variant="ghost"
              size="icon"
              onClick={onCloseMobile}
              aria-label="Close navigation"
            >
              <X size={16} />
            </Button>
          </div>
          <NavGroups collapsed={false} onNavigate={onCloseMobile} />
        </aside>
      </div>
    </Tooltip.Provider>
  );
}
