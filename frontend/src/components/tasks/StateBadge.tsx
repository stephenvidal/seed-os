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

/**
 * A task's state as people read it: "needs you" while it waits for approval,
 * "with an agent" while it waits for a task it delegated.
 */
export function StateBadge({ task }: { task: Task }) {
  const delegating = task.state === "waiting" && Boolean(task.awaiting_delegation);
  const label =
    task.state === "running" && task.cancel_requested
      ? "canceling"
      : delegating
        ? "with an agent"
        : task.state === "waiting"
          ? "needs you"
          : task.state;
  return (
    <Badge tone={delegating ? "neutral" : STATE_TONE[task.state]}>
      {task.state === "running" && <Spinner label="Running" />}
      {label}
    </Badge>
  );
}
