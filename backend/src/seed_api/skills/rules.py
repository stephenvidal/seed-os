"""What makes a skill valid (D-033), shared by the API and the agent's skill_manage
tool. Each function returns the cleaned value or raises ValueError saying why."""

import re

MAX_DESCRIPTION = 1024
MAX_BODY = 20_000
MAX_TAGS = 20
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def clean_name(v: str) -> str:
    v = v.strip().lower()
    if not _NAME.match(v):
        raise ValueError(
            "Use 1-64 lower-case letters, digits or hyphens, starting with a letter or digit."
        )
    return v


def clean_description(v: str) -> str:
    v = " ".join(v.split())
    if not v:
        raise ValueError("Say what the skill is for.")
    if len(v) > MAX_DESCRIPTION:
        raise ValueError(f"Keep the description to {MAX_DESCRIPTION} characters.")
    return v


def clean_tags(v: list[str]) -> list[str]:
    tags = list(dict.fromkeys(t for t in (" ".join(x.split()) for x in v) if t))
    if len(tags) > MAX_TAGS:
        raise ValueError(f"Use at most {MAX_TAGS} tags.")
    if any(len(t) > 40 for t in tags):
        raise ValueError("Keep each tag to 40 characters.")
    return tags


def clean_body(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("Write the skill's instructions.")
    if len(v) > MAX_BODY:
        raise ValueError(f"Keep the instructions to {MAX_BODY} characters.")
    return v
