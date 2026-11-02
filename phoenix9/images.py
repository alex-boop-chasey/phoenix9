"""Static safety checks for the step-image Dockerfiles (no Docker needed)."""
from __future__ import annotations

import re
from pathlib import Path

FIREWALL = "/usr/local/bin/init-firewall.sh"
DOCKER_WORD = re.compile(r"(?<![\w./-])docker(\.io|-ce|-ce-cli|-cli|-compose-plugin|-buildx-plugin)?(?![\w.-])")
SECRET_ENV = re.compile(r"^\w*(TOKEN|KEY)$", re.IGNORECASE)


def _instructions(path: Path) -> list[tuple[str, str]]:
    """Return (INSTRUCTION, rest) pairs with comments dropped and continued lines joined."""
    out, joined = [], ""
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not joined and (not line or line.startswith("#")):
            continue
        if joined and line.startswith("#"):
            continue
        if line.endswith("\\"):
            joined += line[:-1] + " "
            continue
        full = (joined + line).strip()
        joined = ""
        word, _, rest = full.partition(" ")
        out.append((word.upper(), rest.strip()))
    return out


def _from_problems(rest: str, stages: set[str]) -> list[str]:
    """Problems with one FROM line: it must name an exact tag or digest."""
    parts = [p for p in rest.split() if not p.startswith("--")]
    image = parts[0] if parts else ""
    if len(parts) >= 3 and parts[1].upper() == "AS":
        stages.add(parts[2].lower())
    if image.lower() in stages or image == "scratch":
        return []
    if "@sha256:" in image:
        return []
    name = image.rsplit("/", 1)[-1]
    if ":" not in name:
        return [f"FROM {image} has no tag"]
    tag = name.split(":", 1)[1]
    if tag == "latest" or "$" in tag or not tag:
        return [f"FROM {image} is not pinned"]
    return []


def _env_pairs(rest: str) -> list[tuple[str, str]]:
    """Split an ENV line into (name, value) pairs for both `ENV A=b C=d` and `ENV A b` forms."""
    if "=" not in rest.split()[0] if rest.split() else True:
        name, _, value = rest.partition(" ")
        return [(name, value.strip())]
    pairs = []
    for token in re.findall(r"""(\w+)=("[^"]*"|'[^']*'|\S*)""", rest):
        pairs.append((token[0], token[1].strip("\"'")))
    return pairs


def _sudoers_problems(text: str) -> list[str]:
    """Problems with one RUN line that writes sudoers: only the firewall script may be allowed."""
    problems = []
    for rule in re.findall(r'echo\s+"([^"]*)"\s*>>?\s*/etc/sudoers', text):
        allowed = rule.split("NOPASSWD:", 1)[1].strip() if "NOPASSWD:" in rule else None
        if allowed != FIREWALL:
            problems.append(f"sudoers rule allows more than the firewall script: {rule}")
    if "sudoers" in text and not re.search(r'echo\s+"[^"]*"\s*>>?\s*/etc/sudoers', text) \
            and not re.match(r"chmod\s+0?440", text.split("&&")[-1].strip()):
        problems.append("sudoers is written in a form this check cannot read")
    return problems


def dockerfile_problems(path) -> list[str]:
    """List the safety problems found in one Dockerfile (empty list means it looks safe)."""
    path = Path(path)
    items = _instructions(path)
    problems: list[str] = []
    stages: set[str] = set()
    froms = [rest for word, rest in items if word == "FROM"]
    if not froms:
        problems.append("no FROM line")
    for rest in froms:
        problems += _from_problems(rest, stages)
    text = "\n".join(f"{w} {r}" for w, r in items)
    if not re.search(r"^COPY\b.*\binit-firewall\.sh\b", text, re.MULTILINE):
        problems.append("init-firewall.sh is not copied in")
    sudoers_runs = [r for w, r in items if w == "RUN" and "sudoers" in r]
    if not sudoers_runs:
        problems.append("no sudoers line for the firewall script")
    for run in sudoers_runs:
        problems += _sudoers_problems(run)
    users = [r.split()[0] for w, r in items if w == "USER" and r.split()]
    if not users or users[-1].split(":")[0] in ("root", "0"):
        problems.append("the image does not end as a non-root USER")
    claude = re.findall(r"@anthropic-ai/claude-code@(\S+)", text)
    arg_default = re.search(r"^ARG CLAUDE_CODE_VERSION=(\d+\.\d+\.\d+)\s*$", text, re.MULTILINE)
    if not claude:
        problems.append("Claude Code is not installed with a pinned version")
    for version in claude:
        pinned = re.match(r"\d+\.\d+\.\d+$", version) or (version.startswith("${") and arg_default)
        if not pinned:
            problems.append(f"Claude Code version {version} is not pinned")
    if not re.search(r"\bDISABLE_AUTOUPDATER=1\b", " ".join(r for w, r in items if w == "ENV")):
        problems.append("DISABLE_AUTOUPDATER=1 is not set")
    if "--bare" in text:
        problems.append("uses --bare (hard rule 7)")
    for word, rest in items:
        if word == "ENV":
            for name, value in _env_pairs(rest):
                if SECRET_ENV.match(name) and value:
                    problems.append(f"ENV {name} holds a value")
        if word == "VOLUME" or "docker.sock" in rest:
            if "docker.sock" in rest:
                problems.append("mentions the Docker socket")
        if word == "RUN" and re.search(r"\b(install|add)\b", rest) and DOCKER_WORD.search(rest):
            problems.append("installs docker")
    return problems
