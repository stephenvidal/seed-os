import { useMutation } from "@tanstack/react-query";
import { Check, ShieldAlert, X } from "lucide-react";
import { tasksApi } from "../../lib/tasks";
import type { ToolCallInfo } from "../../lib/tasks";
import { Button } from "../ui/Button";

/** Asks the person to approve or deny the one tool call a task is waiting on. */
export function ApprovalPrompt({
  taskId,
  call,
  onDecided,
}: {
  taskId: string;
  call: ToolCallInfo;
  onDecided?: () => void;
}) {
  const decide = useMutation({
    mutationFn: (approve: boolean) => tasksApi.decide(taskId, call.id, approve),
    onSuccess: () => onDecided?.(),
  });
  const command = call.name === "run_command" ? call.arguments.command : undefined;
  return (
    <section
      aria-label="Approval needed"
      className="flex flex-col gap-2.5 rounded-control border border-warning bg-warning-soft px-3.5 py-3"
    >
      <p className="flex items-center gap-2 text-sm font-medium text-fg">
        <ShieldAlert size={15} className="text-warning" aria-hidden />
        {command !== undefined ? "SEED wants to run a command" : `SEED wants to use ${call.name}`}
      </p>
      <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded-control bg-surface-1 px-3 py-2 font-mono text-xs text-fg">
        {command !== undefined ? String(command) : JSON.stringify(call.arguments, null, 2)}
      </pre>
      <p className="text-xs text-fg-muted">
        It runs in the sandbox for this workspace, with no network access. Nothing happens until you
        choose.
      </p>
      <div className="flex gap-2">
        <Button
          size="sm"
          variant="primary"
          onClick={() => decide.mutate(true)}
          disabled={decide.isPending || decide.isSuccess}
        >
          <Check size={13} aria-hidden /> Approve
        </Button>
        <Button
          size="sm"
          onClick={() => decide.mutate(false)}
          disabled={decide.isPending || decide.isSuccess}
        >
          <X size={13} aria-hidden /> Deny
        </Button>
      </div>
      {decide.isError && (
        <p role="alert" className="text-xs text-danger">
          {decide.error.message}
        </p>
      )}
    </section>
  );
}
