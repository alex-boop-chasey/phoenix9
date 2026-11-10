"""Boundary tests: agentkit and phoenix9 stay apart, and the key, dependencies and pins stay tidy."""
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".venv", "__pycache__", "node_modules", ".git"}


def source_files(folder, suffix=".py"):
    """List the files with this ending under a folder, skipping virtual environments and caches."""
    base = ROOT / folder
    if not base.exists():
        return []
    return [p for p in sorted(base.rglob(f"*{suffix}"))
            if p.is_file() and not SKIP_DIRS & set(p.relative_to(ROOT).parts)]


def imported_names(path):
    """Return every module name a Python file imports."""
    names = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


def imports_package(path, package):
    """Say whether a Python file imports the given top-level package."""
    return any(n == package or n.startswith(package + ".") for n in imported_names(path))


def test_phoenix9_never_imports_agentkit():
    """No phoenix9 module imports agentkit."""
    assert source_files("phoenix9")
    assert [str(p) for p in source_files("phoenix9") if imports_package(p, "agentkit")] == []


def test_agentkit_never_imports_phoenix9():
    """No agentkit module imports phoenix9."""
    files = source_files("agentkit")
    assert files
    assert [str(p) for p in files if imports_package(p, "phoenix9")] == []


def test_api_key_is_named_only_inside_agentkit():
    """Outside agentkit, nothing mentions the API key variable or the key file."""
    bad = []
    for folder in ("phoenix9", "steps", "image", "deploy", "bin"):
        base = ROOT / folder
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            rel = p.relative_to(ROOT)
            if not p.is_file() or p.is_symlink() or SKIP_DIRS & set(rel.parts):
                continue
            if rel.parts[:2] == ("deploy", "agentkit"):
                continue
            text = p.read_bytes().decode("utf-8", errors="ignore")
            if "ANTHROPIC_API_KEY" in text or "agentkit/api-key" in text:
                bad.append(str(rel))
    assert bad == []


def test_root_pyproject_has_no_dependencies():
    """The root pyproject.toml keeps dependencies = []."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r"^dependencies\s*=\s*\[\s*\]\s*$", text, re.M)


def test_lock_file_lines_are_pinned():
    """Every line of agentkit/requirements.lock is name==version."""
    lines = (ROOT / "agentkit" / "requirements.lock").read_text(encoding="utf-8").splitlines()
    lines = [ln for ln in lines if ln.strip()]
    assert lines
    pattern = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*==[0-9][A-Za-z0-9._+!-]*$")
    assert [ln for ln in lines if not pattern.match(ln)] == []


def test_web_package_versions_are_exact():
    """Every version in web/package.json is an exact number, no ranges or tags."""
    data = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))
    exact = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")
    bad = []
    for section in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        for name, version in data.get(section, {}).items():
            if not exact.match(version):
                bad.append(f"{section}: {name} {version}")
    assert bad == []


def forbidden_process_use(path):
    """List the ways a Python file starts programs: subprocess imports and os.system, popen or exec calls."""
    found = [n for n in imported_names(path) if n == "subprocess" or n.startswith("subprocess.")]
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os":
            if node.attr in ("system", "popen") or node.attr.startswith("exec"):
                found.append(f"os.{node.attr}")
        if isinstance(node, ast.ImportFrom) and node.module == "os":
            found += [f"os.{a.name}" for a in node.names
                      if a.name in ("system", "popen") or a.name.startswith("exec")]
    return found


def test_agentkit_starts_no_programs():
    """No agentkit source file imports subprocess or calls os.system, os.popen or os.exec*."""
    files = source_files("agentkit")
    assert files
    bad = {str(p.relative_to(ROOT)): forbidden_process_use(p) for p in files if forbidden_process_use(p)}
    assert bad == {}
