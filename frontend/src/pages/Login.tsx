import { AlertTriangle, ArrowRight } from "lucide-react";
import { useState } from "react";
import type { FormEvent } from "react";
import { BrandMark } from "../components/shell/BrandMark";
import { Button } from "../components/ui/Button";
import { Spinner } from "../components/ui/Spinner";
import { useLogin } from "../lib/auth";

const inputCls =
  "h-9 w-full rounded-control border border-border bg-surface-1 px-3 text-sm text-fg outline-none transition-colors placeholder:text-fg-subtle hover:border-border-strong focus:border-accent focus:ring-2 focus:ring-ring";

export function LoginPage() {
  const login = useLogin();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate({ username: username.trim(), password });
  };

  return (
    <div className="grid min-h-full place-items-center bg-bg px-4 py-12">
      <div className="w-full max-w-[360px]">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <span className="text-fg">
            <BrandMark size={36} />
          </span>
          <div>
            <h1 className="text-lg font-semibold tracking-[0.14em]">SEED</h1>
            <p className="mt-1 text-sm text-fg-muted">From intention to execution.</p>
          </div>
        </div>
        <form
          onSubmit={submit}
          className="rounded-panel border border-border bg-surface-1 p-5 shadow-pop"
          noValidate
        >
          <div className="flex flex-col gap-4">
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-fg-muted">Username</span>
              <input
                className={inputCls}
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-fg-muted">Password</span>
              <input
                className={inputCls}
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoFocus
                required
              />
            </label>
            {login.isError && (
              <p
                role="alert"
                className="flex items-start gap-2 rounded-control bg-danger-soft px-3 py-2 text-xs text-danger"
              >
                <AlertTriangle size={14} className="mt-px shrink-0" aria-hidden />
                {login.error.message}
              </p>
            )}
            <Button
              type="submit"
              variant="primary"
              className="w-full justify-center"
              disabled={login.isPending || !username.trim() || !password}
            >
              {login.isPending ? (
                <Spinner label="Signing in" />
              ) : (
                <>
                  Sign in <ArrowRight size={14} aria-hidden />
                </>
              )}
            </Button>
          </div>
        </form>
        <p className="mt-6 text-center text-xs text-fg-subtle">
          Self-hosted workspace · credentials set by your administrator
        </p>
      </div>
    </div>
  );
}
