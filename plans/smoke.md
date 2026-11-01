# Smoke test: a tiny hello script
Project: smoke
Preset: simple

## About
A tiny Python script project that proves Phoenix can build, check, commit and merge from a spec.

## Task 1: Hello script
Write a script called hello.py in the project root. When run it prints the word hello.
Depends on: none
For you: no
Done when:
- `python3 hello.py`

## Task 2: Test for the script
Add tests/test_hello.py with a pytest test that runs hello.py and checks it prints hello.
Depends on: none
For you: no
Done when:
- `python3 -m pytest -q`

## Task 3: A name flag
Add a --name flag to hello.py so that `python3 hello.py --name Ann` prints hello Ann.
Depends on: 1, 2
For you: no
Done when:
- `python3 hello.py --name Ann`
- `python3 -m pytest -q`
