# End to end test: loud greetings
Project: e2e
Preset: quick

## About
A tiny Python package used by the end to end tests. Each task adds one small function with its own test.

## Task 1: Shout function
Add src/e2e/shout.py with a function shout(text) that returns the text in capital letters followed by "!".
Add tests/test_shout.py that checks it.
Depends on: none
For you: no
Done when:
- `python3 -m pytest -q tests/test_shout.py`

## Task 2: Whisper function
Add src/e2e/whisper.py with a function whisper(text) that returns the text in small letters.
Add tests/test_whisper.py that checks it.
Depends on: none
For you: no
Done when:
- `python3 -m pytest -q tests/test_whisper.py`

## Task 3: Loud greeting
Add src/e2e/loud.py with a function loud_greet(name) that shouts the greeting from greet(name).
Add tests/test_loud.py that checks it.
Depends on: 1
For you: no
Done when:
- `python3 -m pytest -q tests/test_loud.py`
