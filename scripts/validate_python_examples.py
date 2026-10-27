#!/usr/bin/env python3
"""Run local checks for the Python examples without contacting Apify."""

from __future__ import annotations

import compileall
import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXAMPLES = REPO_ROOT / "examples" / "python"
TESTS = PYTHON_EXAMPLES / "tests"
REQUIREMENTS = PYTHON_EXAMPLES / "requirements.txt"
EXPECTED_APIFY_CLIENT_VERSION = "3.3.0"


def print_result(name: str, passed: bool, details: str = "") -> bool:
    label = "PASS" if passed else "FAIL"
    suffix = f" — {details}" if details else ""
    print(f"[{label}] {name}{suffix}")
    return passed


def check_environment() -> tuple[bool, str]:
    issues: list[str] = []
    notes: list[str] = []
    if sys.version_info < (3, 11):
        issues.append(f"Python 3.11+ required; found {sys.version.split()[0]}")
    try:
        requirements = REQUIREMENTS.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return False, f"cannot read {REQUIREMENTS}: {exc}"

    expected_pin = f"apify-client=={EXPECTED_APIFY_CLIENT_VERSION}"
    if expected_pin not in {line.strip() for line in requirements}:
        issues.append(f"requirements.txt must contain {expected_pin}")

    for distribution, expected in (("apify-client", EXPECTED_APIFY_CLIENT_VERSION), ("python-dotenv", None)):
        try:
            installed = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            notes.append(f"{distribution} is not installed; offline tests use mocks/stubs")
            continue
        if expected and installed != expected:
            issues.append(f"{distribution} {expected} required; found {installed}")
    if issues:
        return False, "; ".join(issues)
    details = f"Python {sys.version.split()[0]}, requirements pin apify-client {EXPECTED_APIFY_CLIENT_VERSION}"
    if notes:
        details += "; " + "; ".join(notes)
    else:
        details += ", python-dotenv installed"
    return True, details


def main() -> int:
    os.chdir(REPO_ROOT)
    results: list[tuple[str, bool]] = []
    print("Python examples offline validation")

    environment_ok, environment_details = check_environment()
    results.append(("Python/dependency versions", print_result("Python/dependency versions", environment_ok, environment_details)))

    compilation_ok = compileall.compile_dir(str(PYTHON_EXAMPLES), quiet=1, force=True)
    results.append(("Compile examples/python", print_result("Compile examples/python", compilation_ok)))

    test_command = [
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        str(TESTS),
        "-p",
        "test_*.py",
        "-v",
    ]
    print("$ " + " ".join(test_command))
    test_env = os.environ.copy()
    test_env["PYTHONDONTWRITEBYTECODE"] = "1"
    test_run = subprocess.run(test_command, cwd=REPO_ROOT, env=test_env, text=True, capture_output=True, check=False)
    if test_run.stdout:
        print(test_run.stdout, end="")
    if test_run.stderr:
        print(test_run.stderr, end="")
    tests_ok = test_run.returncode == 0
    results.append(("Offline unittest suite", print_result("Offline unittest suite", tests_ok, f"exit {test_run.returncode}")))

    diff_command = ["git", "diff", "--check"]
    print("$ " + " ".join(diff_command))
    diff_run = subprocess.run(diff_command, cwd=REPO_ROOT, text=True, capture_output=True, check=False)
    diff_ok = diff_run.returncode == 0
    diff_details = diff_run.stdout.strip() or diff_run.stderr.strip() or f"exit {diff_run.returncode}"
    results.append(("git diff --check", print_result("git diff --check", diff_ok, diff_details)))

    all_ok = all(passed for _, passed in results)
    print("\nValidation summary:")
    for name, passed in results:
        print(f"  {'PASS' if passed else 'FAIL'} — {name}")
    print(f"Overall: {'PASS' if all_ok else 'FAIL'} (exit {0 if all_ok else 1})")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
