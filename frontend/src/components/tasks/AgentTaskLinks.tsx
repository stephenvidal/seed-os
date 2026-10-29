import { Link } from "react-router-dom";
import { cn } from "../ui/cn";
import type { DelegatedTask } from "../../lib/tasks";

const END: Record<string, string> = {
  completed: "reported back",
  failed: "failed",
  canceled: "canceled",
};

/** Links to the agent tasks a task handed work to, with how each one ended. */
export function AgentTaskLinks({
  agents,
  className,
}: {
  agents: DelegatedTask[];
  className?: string;
}) {
  if (agents.length === 0) return null;
  return (
    <ul aria-label="Agent tasks" className={cn("flex flex-col gap-1 text-xs", className)}>
      {agents.map((a) => (
        <li key={a.id} className="flex flex-wrap items-baseline gap-x-2 text-fg-muted">
          <Link to={`/tasks/${a.taskId}`} className="text-accent hover:underline">
            {a.agent}'s task
          </Link>
          <span>{a.state ? (END[a.state] ?? a.state) : "working"}</span>
        </li>
      ))}
    </ul>
  );
}
