"""The templates menu: loading, pinned recipes, validation."""
import pytest

from phoenix9 import templates


def test_menu_loads_and_recipes_pinned():
    menu = {t["name"]: t for t in templates.load_menu()}
    assert set(menu) == {"python-cli", "research-notes", "astro-tailwind", "nextjs-tailwind", "expo", "tauri"}
    assert templates.load_problems() == []
    assert [menu[n]["profile"] for n in ("astro-tailwind", "nextjs-tailwind", "expo", "tauri")] == \
        ["web", "web", "mobile", "desktop"]
    for t in menu.values():
        if t["kind"] == "recipe":
            assert all("@latest" not in c for c in t["run"])
    assert templates.get("nope") is None and templates.get("expo")["kind"] == "recipe"


@pytest.fixture
def lib(tmp_path, monkeypatch):
    (tmp_path / "templates" / "t").mkdir(parents=True)
    monkeypatch.setenv("PHOENIX_LIBRARY", str(tmp_path))
    return tmp_path / "templates" / "t" / "template.toml"


@pytest.mark.parametrize("run", ['"pnpm create astro@latest ."', '"pnpm create astro ."',
                                 '"pnpm add tailwindcss"', '"pnpm add -D a@1.0.0 b"'])
def test_unpinned_recipe_rejected(lib, run):
    lib.write_text(f'name = "t"\ntitle = "T"\nprofile = "web"\nkind = "recipe"\nrun = [{run}]\n')
    assert templates.load_menu() == []
    assert "exact version" in templates.load_problems()[0]


def test_unknown_key_and_pinned_ok(lib):
    lib.write_text('name = "t"\ntitle = "T"\nprofile = "web"\nkind = "recipe"\nrun = ["pnpm create x@1.2.3 ."]\nbad = 1\n')
    assert "unknown key 'bad'" in templates.load_problems()[0]
    lib.write_text('name = "t"\ntitle = "T"\nprofile = "web"\nkind = "recipe"\nrun = ["pnpm create x@1.2.3 ."]\n')
    assert templates.get("t")


def test_shipped_templates_add_no_playwright():
    """Alex checks pages by hand: no template puts Playwright into a new project."""
    from pathlib import Path
    for t in templates.load_menu():
        assert not any("playwright" in c.lower() for c in t["run"])
        assert not any("playwright" in p.name.lower() for p in (Path(t["folder"]) / "files").rglob("*"))


@pytest.mark.parametrize("run", ['"pnpm add -D @playwright/test@1.64.1"', '"pnpm create playwright@1.0.0 ."'])
def test_recipe_adding_playwright_rejected(lib, run):
    lib.write_text(f'name = "t"\ntitle = "T"\nprofile = "web"\nkind = "recipe"\nrun = [{run}]\n')
    assert templates.load_menu() == []
    assert "may not add Playwright" in templates.load_problems()[0]


@pytest.mark.parametrize("name,body", [("package.json", '{"devDependencies": {"@playwright/test": "1.64.1"}}'),
                                       ("playwright.config.ts", "export default {}\n")])
def test_files_template_adding_playwright_rejected(lib, name, body):
    files = lib.parent / "files"
    files.mkdir()
    (files / name).write_text(body)
    lib.write_text('name = "t"\ntitle = "T"\nprofile = "web"\nkind = "files"\n')
    assert templates.load_menu() == []
    assert "may not add Playwright" in templates.load_problems()[0]
