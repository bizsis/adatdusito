#!/usr/bin/env python3
"""Check the backend dependency files against each other (SECURITY-02).

Static checks (offline, also run by backend/tests/test_dependency_locks.py):
  * every pin in requirements.txt equals the pin in requirements.lock
  * requirements.lock (runtime, shipped in images) has no test-only package
  * requirements-test.lock only adds packages that are not in the runtime lock
  * every pin in requirements-test.in equals the pin in requirements-test.lock

With --resolve, pip's resolver must pick exactly the locked set for the
runtime lock and for runtime + test locks (needs a package index; uses the
current interpreter, which must be the image's CPython 3.12).
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
RUNTIME_INPUT = BACKEND / "requirements.txt"
RUNTIME_LOCK = BACKEND / "requirements.lock"
TEST_INPUT = BACKEND / "requirements-test.in"
TEST_LOCK = BACKEND / "requirements-test.lock"
TEST_ONLY = {"pytest", "iniconfig", "pluggy", "pygments", "playwright", "pyee"}
PIN = re.compile(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==([^\s;#]+)")


def canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def pins(path):
    found = {}
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        match = PIN.match(text)
        if not match:
            raise ValueError(f"{Path(path).name}:{number}: not an exact pin: {text}")
        key = canonical(match.group(1))
        if key in found:
            raise ValueError(f"{Path(path).name}:{number}: duplicate {match.group(1)}")
        found[key] = match.group(2)
    return found


def static_problems():
    problems = []
    runtime_in, runtime = pins(RUNTIME_INPUT), pins(RUNTIME_LOCK)
    test_in, test = pins(TEST_INPUT), pins(TEST_LOCK)
    for name, version in runtime_in.items():
        if runtime.get(name) != version:
            problems.append(f"requirements.txt {name}=={version} != lock {runtime.get(name)}")
    for name in sorted(TEST_ONLY & set(runtime)):
        problems.append(f"test-only package {name} is in the runtime lock (shipped in images)")
    for name in sorted(set(test) & set(runtime)):
        problems.append(f"{name} is in both requirements.lock and requirements-test.lock")
    for name, version in test_in.items():
        if test.get(name) != version:
            problems.append(f"requirements-test.in {name}=={version} != test lock {test.get(name)}")
    return problems


def resolved(*requirement_files):
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        command = [sys.executable, "-m", "pip", "install", "--dry-run", "--ignore-installed",
                   "--quiet", "--report", str(report)]
        for path in requirement_files:
            command += ["-r", str(path)]
        subprocess.run(command, check=True)
        data = json.loads(report.read_text())
    return {canonical(item["metadata"]["name"]): item["metadata"]["version"] for item in data["install"]}


def resolver_problems():
    problems = []
    runtime, test = pins(RUNTIME_LOCK), pins(TEST_LOCK)
    for label, files, expected in [
        ("runtime", [RUNTIME_LOCK], runtime),
        ("runtime+test", [RUNTIME_LOCK, TEST_LOCK], {**runtime, **test}),
    ]:
        got = resolved(*files)
        for name in sorted(set(got) | set(expected)):
            if got.get(name) != expected.get(name):
                problems.append(f"{label}: resolver {name}={got.get(name)} lock={expected.get(name)}")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--resolve", action="store_true", help="also check with pip's resolver")
    args = parser.parse_args(argv)
    problems = static_problems() + (resolver_problems() if args.resolve else [])
    for problem in problems:
        print(f"::error::{problem}" if "GITHUB_ACTIONS" in os.environ else problem)
    if not problems:
        runtime, test = pins(RUNTIME_LOCK), pins(TEST_LOCK)
        print(f"OK: {len(runtime)} runtime + {len(test)} test-only pins"
              + (", resolver agrees" if args.resolve else ""))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
