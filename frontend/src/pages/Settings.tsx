import { Monitor, Moon, Sun } from "lucide-react";
import { PageHeader } from "../components/ui/PageHeader";
import { Panel } from "../components/ui/Panel";
import { cn } from "../components/ui/cn";
import { useSession } from "../lib/auth";
import { formatBytes } from "../lib/format";
import { useTheme } from "../lib/theme";
import type { ThemePreference } from "../lib/theme";
import { useSystem } from "./useSystem";

const OPTIONS: { value: ThemePreference; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

function Row({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <p className="text-sm font-medium text-fg">{label}</p>
        {hint && <p className="text-xs text-fg-muted">{hint}</p>}
      </div>
      {children}
    </div>
  );
}

export function SettingsPage() {
  const { preference, setPreference } = useTheme();
  const { data: me } = useSession();
  const { data: sys } = useSystem();

  return (
    <>
      <PageHeader title="Settings" description="Appearance, account, and system." />
      <div className="flex max-w-3xl flex-col gap-4">
        <Panel title="Appearance">
          <Row label="Theme" hint="System follows your operating system and updates live.">
            <div
              role="radiogroup"
              aria-label="Theme"
              className="inline-flex rounded-control border border-border bg-surface-2 p-0.5"
            >
              {OPTIONS.map(({ value, label, icon: Icon }) => (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={preference === value}
                  onClick={() => setPreference(value)}
                  className={cn(
                    "flex h-7 items-center gap-1.5 rounded-[5px] px-3 text-xs font-medium transition-colors",
                    preference === value
                      ? "bg-surface-1 text-fg shadow-sm"
                      : "text-fg-muted hover:text-fg",
                  )}
                >
                  <Icon size={13} aria-hidden /> {label}
                </button>
              ))}
            </div>
          </Row>
        </Panel>
        <Panel title="Account">
          <Row
            label="Signed in as"
            hint="Accounts are managed on the server with python -m seed_api.users (add, set-password, disable)."
          >
            <span className="font-mono text-sm text-fg">
              {me?.username} · {me?.role}
            </span>
          </Row>
        </Panel>
        <Panel title="System">
          <dl className="divide-y divide-border text-sm">
            {[
              ["API version", sys ? `v${sys.version}` : "—"],
              ["Runtime", sys ? `Python ${sys.python}` : "—"],
              ["Platform", sys?.platform ?? "—"],
              ["Host memory", formatBytes(sys?.memory_total_bytes)],
            ].map(([k, v]) => (
              <div key={k} className="flex items-center justify-between gap-4 px-4 py-2.5">
                <dt className="text-fg-muted">{k}</dt>
                <dd className="truncate font-mono text-xs text-fg">{v}</dd>
              </div>
            ))}
          </dl>
        </Panel>
      </div>
    </>
  );
}
