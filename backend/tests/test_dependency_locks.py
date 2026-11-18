"""SECURITY-02: runtime vs test dependency separation (offline checks)."""

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("check_requirements", ROOT / "backend/scripts/check_requirements.py")
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


def test_lock_files_are_consistent():
    assert check.static_problems() == []


def test_runtime_lock_has_no_test_tools_and_test_lock_has_patched_pytest():
    runtime, test = check.pins(check.RUNTIME_LOCK), check.pins(check.TEST_LOCK)
    assert not check.TEST_ONLY & set(runtime)
    major, minor, patch = (int(x) for x in test["pytest"].split(".")[:3])
    assert (major, minor, patch) >= (9, 0, 3)  # PYSEC-2026-1845 / CVE-2025-71176
    # TEMPLATE-PREP-01 added xlrd (legacy XLS intake), no transitive dependencies.
    assert runtime["xlrd"] == "2.0.1"
    assert len(runtime) + len(test) == 54


def test_requirements_txt_pins_match_lock_including_cryptography():
    runtime_in, runtime = check.pins(check.RUNTIME_INPUT), check.pins(check.RUNTIME_LOCK)
    assert runtime_in["cryptography"] == runtime["cryptography"] == "50.0.2"
    assert "pytest" not in runtime_in


def test_checker_detects_drift(tmp_path, monkeypatch):
    runtime = tmp_path / "requirements.lock"
    runtime.write_text("fastapi==1.0\npytest==9.0.3\n")
    (tmp_path / "requirements.txt").write_text("fastapi==2.0\n")
    (tmp_path / "requirements-test.lock").write_text("pytest==9.0.3\n")
    (tmp_path / "requirements-test.in").write_text("pytest==9.0.4\n")
    monkeypatch.setattr(check, "RUNTIME_LOCK", runtime)
    monkeypatch.setattr(check, "RUNTIME_INPUT", tmp_path / "requirements.txt")
    monkeypatch.setattr(check, "TEST_LOCK", tmp_path / "requirements-test.lock")
    monkeypatch.setattr(check, "TEST_INPUT", tmp_path / "requirements-test.in")
    problems = "\n".join(check.static_problems())
    assert "fastapi==2.0 != lock 1.0" in problems
    assert "test-only package pytest is in the runtime lock" in problems
    assert "pytest is in both" in problems
    assert "requirements-test.in pytest==9.0.4" in problems


def test_backend_image_installs_only_the_runtime_lock_exactly():
    dockerfile = "\n".join(
        line for line in (ROOT / "backend/Dockerfile").read_text().splitlines() if not line.lstrip().startswith("#")
    )
    installs = re.findall(r"pip install[^\n]*", dockerfile)
    assert installs and all("requirements.lock" in line and "--no-deps" in line for line in installs)
    assert "requirements-test" not in dockerfile and "pytest" not in dockerfile
    ignored = (ROOT / "backend/.dockerignore").read_text().split()
    assert {"tests", "requirements-test.lock", "requirements-test.in"} <= set(ignored)


def test_ci_installs_test_dependencies_from_the_test_lock():
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "backend/requirements-test.lock" in ci
    assert not re.search(r"pytest==\d", ci), "pin pytest only in backend/requirements-test.in"
    audit = (ROOT / ".github/workflows/dependency-audit.yml").read_text()
    assert "backend/requirements-test.lock" in audit
