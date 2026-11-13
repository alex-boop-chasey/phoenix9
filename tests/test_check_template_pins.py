"""bin/check-template-pins: finding pinned npm versions in templates (fake fetch; no network)."""
import importlib.machinery
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load():
    loader = importlib.machinery.SourceFileLoader("check_template_pins", str(ROOT / "bin/check-template-pins"))
    spec = importlib.util.spec_from_loader("check_template_pins", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_pins_in_command_maps_create_words_to_packages():
    pins = load().pins_in_command
    assert pins("pnpm create astro@5.1.0 . --yes") == [("create-astro", "5.1.0")]
    assert pins("pnpm create next-app@15.1.0 . --ts") == [("create-next-app", "15.1.0")]
    assert pins("pnpm add -D tailwindcss@4.0.0 @tailwindcss/vite@4.0.0") == [
        ("tailwindcss", "4.0.0"), ("@tailwindcss/vite", "4.0.0")]
    assert pins("pnpm create @scope/thing@1.2.3") == [("@scope/create-thing", "1.2.3")]
    assert pins("uv run pytest") == [] and pins("pnpm add left-pad@latest") == []


def test_real_templates_pins_are_found():
    found = load().template_pins(ROOT)
    assert ("astro-tailwind", "create-astro", "5.1.0") in found
    assert ("astro-tailwind", "@tailwindcss/vite", "4.0.0") in found
    assert ("expo", "create-expo-app", "3.2.0") in found
    assert ("tauri", "create-tauri-app", "4.5.9") in found


def test_check_prints_one_line_per_pin_and_fails_on_missing(tmp_path):
    mod = load()
    (tmp_path / "templates/a").mkdir(parents=True)
    (tmp_path / "templates/a/template.toml").write_text(
        'run = ["pnpm create astro@5.1.0 .", "pnpm add -D @tailwindcss/vite@9.9.9"]\n')
    asked, lines = [], []
    fetch = lambda url: asked.append(url) or "9.9.9" not in url
    assert mod.check(tmp_path, fetch, lines.append) == 1
    assert asked == ["https://registry.npmjs.org/create-astro/5.1.0",
                     "https://registry.npmjs.org/@tailwindcss%2Fvite/9.9.9"]
    assert lines[0].startswith("ok") and "a: create-astro 5.1.0" in lines[0]
    assert lines[1].startswith("MISSING") and "@tailwindcss/vite 9.9.9" in lines[1] and len(lines) == 2
    lines.clear()
    assert mod.check(tmp_path, lambda url: True, lines.append) == 0 and lines[-1] == "All pinned versions exist."
    assert mod.check(tmp_path, lambda url: None, lines.append) == 1
