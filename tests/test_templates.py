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
