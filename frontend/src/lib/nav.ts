import {
  Activity,
  Bot,
  Boxes,
  CalendarClock,
  Cpu,
  FolderKanban,
  LayoutDashboard,
  ListChecks,
  MessageSquare,
  Settings,
  Wrench,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type NavItem = {
  path: string;
  label: string;
  icon: LucideIcon;
  /** Second key of the "G then X" navigation chord. */
  chord: string;
  group: "workspace" | "configure";
  description: string;
};

/** Single source of truth for navigation, routing, and the command palette. */
export const NAV: NavItem[] = [
  {
    path: "/",
    label: "Command Center",
    icon: LayoutDashboard,
    chord: "h",
    group: "workspace",
    description: "What is happening, what needs attention, what is done",
  },
  {
    path: "/chat",
    label: "Chat",
    icon: MessageSquare,
    chord: "c",
    group: "workspace",
    description: "Talk to SEED",
  },
  {
    path: "/tasks",
    label: "Tasks",
    icon: ListChecks,
    chord: "t",
    group: "workspace",
    description: "Durable work and its lifecycle",
  },
  {
    path: "/agents",
    label: "Agents",
    icon: Bot,
    chord: "a",
    group: "workspace",
    description: "Orchestrator and specialists",
  },
  {
    path: "/schedules",
    label: "Schedules",
    icon: CalendarClock,
    chord: "e",
    group: "workspace",
    description: "Tasks that start on a timetable",
  },
  {
    path: "/projects",
    label: "Projects",
    icon: FolderKanban,
    chord: "p",
    group: "workspace",
    description: "Related work, knowledge, and files",
  },
  {
    path: "/studio",
    label: "Studio",
    icon: Boxes,
    chord: "s",
    group: "workspace",
    description: "Artifacts, previews, and versions",
  },
  {
    path: "/inspector",
    label: "Inspector",
    icon: Activity,
    chord: "i",
    group: "workspace",
    description: "Execution traces and evidence",
  },
  {
    path: "/models",
    label: "Models",
    icon: Cpu,
    chord: "m",
    group: "configure",
    description: "Providers, routing, and budgets",
  },
  {
    path: "/tools",
    label: "Tools & Skills",
    icon: Wrench,
    chord: "k",
    group: "configure",
    description: "Capabilities and permissions",
  },
  {
    path: "/settings",
    label: "Settings",
    icon: Settings,
    chord: ",",
    group: "configure",
    description: "Appearance, security, and system",
  },
];

export function navForPath(pathname: string): NavItem | undefined {
  return NAV.find((n) => (n.path === "/" ? pathname === "/" : pathname.startsWith(n.path)));
}
