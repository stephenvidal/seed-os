import type { Task, TaskState } from "../../lib/tasks";
import { Badge } from "../ui/Badge";
import { Spinner } from "../ui/Spinner";

const STATE_TONE: Record<TaskState, "neutral" | "accent" | "warning" | "danger"> = {
  queued: "neutral",
  running: "accent",
  waiting: "warning",
  completed: "accent",
  failed: "danger",
  canceled: "neutral",
};

/** A task's state as people read it: "needs you" while it waits for approval. */
export function StateBadge({ task }: { task: Task }) {
  const label =
    task.state === "running" && task.cancel_requested
      ? "canceling"
      : task.state === "waiting"
        ? "needs you"
        : task.state;
  return (
    <Badge tone={STATE_TONE[task.state]}>
      {task.state === "running" && <Spinner label="Running" />}
      {label}
    </Badge>
  );
}
