from pathlib import Path

import pytest

from phoenix import plan
from phoenix.__main__ import main

SAMPLE = Path(__file__).parent / "data" / "sample-plan.md"

HEADER = """# Plan: Test

Type: new
Repo: me/site

## About
A test site.
"""

STEP1 = """
## Step 1: Set up the project
Scaffold the app.

Done when:
- pnpm build finishes cleanly with no errors
"""


def errors_for(text):
    return plan.check(plan.parse(text))


def one_error(text):
    errors = errors_for(text)
    assert len(errors) == 1, errors
    return errors[0]


# --- the sample plan -------------------------------------------------------

def test_sample_plan_parses_and_passes():
    p = plan.parse(SAMPLE.read_text())
    assert plan.check(p) == []
    assert p.name == "Bakery site"
    assert p.type == "new" and p.repo == "alex-boop-chasey/bakery-site"
    assert p.stack == "Next.js, Tailwind, pnpm"
    assert p.sites == ["api.stripe.com", "fonts.googleapis.com"]
    assert p.about.startswith("A small website")
    assert "British English" in p.every_step
    assert [s.number for s in p.steps] == [1, 2, 3]
    s1, s2, s3 = p.steps
    assert s1.title == "Set up the project" and s1.depends_on == []
    assert len(s1.done_when) == 2 and s1.done_when[0] == "`pnpm build` finishes without errors"
    assert s2.for_you and s2.done_when == [] and s2.depends_on == [1]
    assert s2.description.startswith("Create a Stripe")
    assert s3.depends_on == [1, 2] and not s3.changes_behaviour
    assert "Depends on" not in s3.description


def test_text_hash_is_sha256_of_step_text_and_changes_with_it():
    p = plan.parse(SAMPLE.read_text())
    assert all(len(s.text_hash) == 64 for s in p.steps)
    assert len({s.text_hash for s in p.steps}) == 3
    edited = plan.parse(SAMPLE.read_text().replace("Coming soon\".", "Opening soon\"."))
    assert edited.steps[0].text_hash != p.steps[0].text_hash
    assert edited.steps[1].text_hash == p.steps[1].text_hash


def test_cli_plan_check_ok(capsys):
    assert main(["plan", "check", str(SAMPLE)]) == 0
    assert capsys.readouterr().out.strip() == "Plan OK: 3 steps"


def test_cli_plan_check_errors(tmp_path, capsys):
    bad = tmp_path / "bad.md"
    bad.write_text(HEADER + STEP1 + "\n## Step 3: Gap\nText.\n\nDone when:\n- something checkable here\n")
    assert main(["plan", "check", str(bad)]) == 1
    out = capsys.readouterr().out
    assert "problem" in out and "Step 3" in out


def test_cli_plan_check_missing_file(tmp_path, capsys):
    assert main(["plan", "check", str(tmp_path / "nope.md")]) == 1
    assert "Cannot read" in capsys.readouterr().out


# --- rule 1: numbering -----------------------------------------------------

def test_rule1_gap_in_numbers():
    errors = errors_for(HEADER + STEP1 + "\n## Step 3: Menu\nAdd menu.\n\nDone when:\n- the menu page lists items\n")
    assert errors[0].startswith("Step 3 (line 15)") and "no gaps" in errors[0]


def test_rule1_must_start_at_one():
    text = HEADER.replace("Type: new", "Type: change") + "\n## Step 2: Menu\nAdd.\n\nDone when:\n- the menu page lists items\n"
    errors = errors_for(text)
    assert any(e.startswith("Step 2 (line") and "expected step 1" in e for e in errors)


def test_rule1_too_many_steps():
    body = "".join(f"\n## Step {n}: Thing {n}\nSet up thing {n}.\n\nDone when:\n- thing {n} page renders its heading\n"
                   for n in range(1, 62))
    errors = errors_for(HEADER + body)
    assert len(errors) == 1 and "61 steps" in errors[0] and "60" in errors[0]


def test_duplicate_step_numbers():
    msg = one_error(HEADER + STEP1 + STEP1.replace("Set up the project", "Again"))
    assert msg.startswith("Step 1 (line 15)") and "used twice" in msg and "line 9" in msg


def test_no_steps():
    assert any("no steps" in e for e in errors_for(HEADER))


# --- rule 2: title, description, done when --------------------------------

def test_rule2_missing_title():
    msg = one_error(HEADER + STEP1.replace(": Set up the project", "").replace("Scaffold the app.", "Scaffold the project."))
    assert msg.startswith("Step 1 (line 9)") and "no title" in msg


def test_rule2_missing_description():
    msg = one_error(HEADER + STEP1 + "\n## Step 2: Menu\nDone when:\n- the menu page lists items\n")
    assert msg.startswith("Step 2 (line 15)") and "no description" in msg


def test_rule2_missing_done_when():
    msg = one_error(HEADER + STEP1 + "\n## Step 2: Menu\nAdd a menu page.\n")
    assert msg.startswith("Step 2 (line 15)") and "Done when" in msg


def test_rule2_for_you_needs_no_done_when():
    assert errors_for(HEADER + STEP1 + "\n## Step 2: Keys\nFor you: yes\nGet a Stripe key.\n") == []


# --- rule 3: depends on ----------------------------------------------------

def test_rule3_depends_on_later_step():
    text = HEADER + STEP1 + "\n## Step 2: Menu\nDepends on: 3\nAdd.\n\nDone when:\n- the menu page lists items\n" \
        + "\n## Step 3: Order\nAdd order form.\n\nDone when:\n- the order form posts to /api/order\n"
    msg = one_error(text)
    assert msg.startswith("Step 2 (line 16)") and "step 3" in msg and "earlier" in msg


def test_rule3_depends_on_itself():
    text = HEADER + STEP1 + "\n## Step 2: Menu\nDepends on: 2\nAdd.\n\nDone when:\n- the menu page lists items\n"
    assert one_error(text).startswith("Step 2 (line 16)")


def test_rule3_default_is_previous_step_and_none_allowed():
    text = HEADER + STEP1 + "\n## Step 2: A\nDo A.\n\nDone when:\n- page A shows its heading\n" \
        + "\n## Step 3: B\nDepends on: none\nDo B.\n\nDone when:\n- page B shows its heading\n"
    p = plan.parse(text)
    assert plan.check(p) == []
    assert [s.depends_on for s in p.steps] == [[], [1], []]


def test_rule3_bad_depends_value():
    text = HEADER + STEP1 + "\n## Step 2: Menu\nDepends on: step one\nAdd.\n\nDone when:\n- the menu page lists items\n"
    msg = one_error(text)
    assert msg.startswith("Step 2 (line 16)") and "Depends on" in msg


# --- rule 4: Type new starts with setup -----------------------------------

def test_rule4_new_plan_needs_setup_step():
    msg = one_error(HEADER + STEP1.replace("Set up the project", "Home page").replace("Scaffold the app.", "Make a home page."))
    assert msg.startswith("Step 1 (line 9)") and "set up" in msg


def test_rule4_change_plan_needs_no_setup():
    text = HEADER.replace("Type: new", "Type: change") + STEP1.replace("Set up the project", "Home page").replace("Scaffold the app.", "Make a home page.")
    assert errors_for(text) == []


@pytest.mark.parametrize("words", ["Setup", "create the project", "scaffold"])
def test_rule4_accepted_words(words):
    text = HEADER + STEP1.replace("Set up the project", "Start").replace("Scaffold the app.", f"Please {words} now.")
    assert errors_for(text) == []


# --- rule 5: done when bullets ---------------------------------------------

def test_rule5_short_bullet():
    msg = one_error(HEADER + STEP1 + "- it builds\n")
    assert msg.startswith("Step 1 (line 14)") and "too short" in msg


@pytest.mark.parametrize("ending", ["professional", "nice", "good", "clean", "modern", "works well"])
def test_rule5_vague_ending(ending):
    msg = one_error(HEADER + STEP1 + f"- the home page looks {ending}.\n")
    assert msg.startswith("Step 1 (line 14)") and "vague" in msg and ending in msg


def test_rule5_vague_word_inside_is_fine():
    assert errors_for(HEADER + STEP1 + "- good contrast on every button text\n") == []


# --- header ----------------------------------------------------------------

def test_unknown_header_line():
    msg = one_error(HEADER.replace("Repo: me/site", "Repo: me/site\nBudget: 100") + STEP1)
    assert msg.startswith("Line 5") and "Budget" in msg


def test_free_text_before_first_section_is_an_error():
    msg = one_error(HEADER.replace("Repo: me/site", "Repo: me/site\nsome stray words") + STEP1)
    assert msg.startswith("Line 5")


@pytest.mark.parametrize("host", ["https://api.stripe.com", "localhost", "API.stripe.com", "a..b.com",
                                  "-bad.com", "api.stripe.com:443", "api.stripe.com/v1", ""])
def test_bad_hostname(host):
    text = HEADER.replace("Repo: me/site", f"Repo: me/site\nSites the app may contact: ok.example.com, {host}") + STEP1
    msg = one_error(text)
    assert msg.startswith("Line 5") and "hostname" in msg


def test_missing_type_and_repo():
    errors = errors_for(HEADER.replace("Type: new\nRepo: me/site\n", "") + STEP1)
    assert any("Type" in e for e in errors) and any("Repo" in e for e in errors)


def test_bad_type_and_repo_values():
    errors = errors_for(HEADER.replace("Type: new", "Type: rebuild").replace("me/site", "just-a-name") + STEP1)
    assert len(errors) == 2


def test_first_line_must_be_plan_title():
    assert any(e.startswith("Line 1") for e in errors_for(HEADER.replace("# Plan: Test", "# Test") + STEP1))


def test_unknown_section():
    msg = one_error(HEADER + STEP1 + "\n## Notes\nstuff\n")
    assert "## Notes" in msg


def test_missing_about():
    errors = errors_for(HEADER.replace("## About\nA test site.\n", "") + STEP1)
    assert any("About" in e for e in errors)


def test_text_after_done_when_is_an_error():
    msg = one_error(HEADER + STEP1 + "More description here.\n")
    assert msg.startswith("Step 1 (line 14)")


def test_wrapped_bullet_joins_previous():
    p = plan.parse(HEADER + STEP1 + "- the home page shows the bakery\n  name in the header\n")
    assert plan.check(p) == []
    assert p.steps[0].done_when[-1] == "the home page shows the bakery name in the header"


def test_changes_behaviour_flag():
    p = plan.parse(HEADER + STEP1.replace("Scaffold the app.", "Changes existing behaviour: yes\nScaffold the app."))
    assert p.steps[0].changes_behaviour and plan.check(p) == []


# --- ordering helpers ------------------------------------------------------

def test_plan_order_and_dependents():
    text = HEADER + STEP1 \
        + "\n## Step 3: C\nDepends on: 2\nDo C.\n\nDone when:\n- page C shows its heading\n" \
        + "\n## Step 2: B\nDepends on: 1\nDo B.\n\nDone when:\n- page B shows its heading\n" \
        + "\n## Step 4: D\nDepends on: 1\nDo D.\n\nDone when:\n- page D shows its heading\n" \
        + "\n## Step 5: E\nDepends on: 3, 4\nDo E.\n\nDone when:\n- page E shows its heading\n"
    p = plan.parse(text)
    assert [s.number for s in plan.plan_order(p)] == [1, 2, 3, 4, 5]
    assert [s.number for s in plan.dependents_of(p, 2)] == [3, 5]
    assert [s.number for s in plan.dependents_of(p, 1)] == [2, 3, 4, 5]
    assert plan.dependents_of(p, 5) == []
