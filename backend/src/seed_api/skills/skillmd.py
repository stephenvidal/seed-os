"""Reading a Hermes Agent SKILL.md (D-033): a YAML header between `---` lines,
then the instructions. SEED keeps the name, the description, the tags (top level
or `metadata.hermes.tags`) and the body. It does not act on the rest (platforms,
conditional activation, settings, files beside SKILL.md), so those keys are
reported back as ignored rather than dropped silently."""

from dataclasses import dataclass
from typing import Any

import yaml

MAX_TEXT = 40_000


class SkillMdError(Exception):
    """The text is not a SKILL.md SEED can read; the message says why."""


@dataclass(frozen=True)
class SkillMd:
    name: Any
    description: Any
    tags: list[Any]
    body: str
    # Header keys SEED does not use, as dotted paths (`metadata.hermes.category`).
    ignored: list[str]


def _paths(value: Any, prefix: str) -> list[str]:
    if isinstance(value, dict) and value:
        return [p for k, v in value.items() for p in _paths(v, f"{prefix}.{k}")]
    return [prefix]


def parse(text: str) -> SkillMd:
    """Raises SkillMdError. The fields it returns are not yet validated."""
    if len(text) > MAX_TEXT:
        raise SkillMdError(f"A SKILL.md can be at most {MAX_TEXT} characters.")
    lines = text.lstrip("﻿").replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        raise SkillMdError("A SKILL.md starts with a YAML header between two --- lines.")
    end = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
    if end is None:
        raise SkillMdError("The YAML header has no closing --- line.")
    try:
        header = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" on line {mark.line + 2}" if mark is not None else ""
        raise SkillMdError(f"The YAML header could not be read{where}.") from None
    if not isinstance(header, dict):
        raise SkillMdError("The YAML header must be a set of key: value lines.")
    tags: Any = header.get("tags")
    metadata = header.get("metadata")
    used = None
    if tags is None and isinstance(metadata, dict):
        hermes = metadata.get("hermes")
        if isinstance(hermes, dict) and "tags" in hermes:
            tags, used = hermes["tags"], "metadata.hermes.tags"
    ignored = [p for p in _paths(metadata, "metadata") if p != used] if metadata else []
    ignored += [str(k) for k in header if k not in ("name", "description", "tags", "metadata")]
    if tags is None:
        tags = []
    elif isinstance(tags, str):  # `tags: a, b` is a common shorthand
        tags = tags.split(",")
    elif not isinstance(tags, list):
        raise SkillMdError("tags must be a list.")
    return SkillMd(
        name=header.get("name"),
        description=header.get("description"),
        tags=tags,
        body="\n".join(lines[end + 1 :]).strip(),
        ignored=sorted(ignored),
    )
