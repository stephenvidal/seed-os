"""The sandbox: where model-generated commands run, never in the API or worker.

It is its own container (ADR-0010) with no network route out, no secrets and
tight resource limits. Each task's workspace belongs to a user id of its own, and
every command and file operation for that task runs as that user, so one task
cannot read another's files or leave processes behind.
"""
