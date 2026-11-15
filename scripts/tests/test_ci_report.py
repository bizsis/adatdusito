"""QUALITY-01: CI report helper (.github/scripts/ci_report.py)."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("ci_report", ROOT / ".github/scripts/ci_report.py")
ci_report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ci_report)


def write(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content if isinstance(content, str) else json.dumps(content))
    return str(path)


def test_junit_counts_failures_and_missing_reports(tmp_path, capsys):
    report = write(
        tmp_path,
        "r.xml",
        """<testsuites><testsuite>
        <testcase classname="a" name="ok" time="0.5"/>
        <testcase classname="a" name="bad" time="2"><failure message="assert 1 == 2&#10;more"/></testcase>
        <testcase classname="a" name="boom" time="0.1"><error message="ImportError"/></testcase>
        <testcase classname="a" name="skip" time="0"><skipped/></testcase>
        </testsuite></testsuites>""",
    )
    lines, failed = ci_report.junit([report, str(tmp_path / "missing.xml")], "T")
    text = "\n".join(lines)
    assert failed
    assert "| 1 | 1 | 1 | 1 |" in text
    assert "`a::bad`: assert 1 == 2" in text and "more" not in text
    assert "missing.xml" in text and "report missing" in text
    assert text.index("2.0s `a::bad`") < text.index("0.5s `a::ok`")


def pip_report(*deps):
    return {"dependencies": [{"name": n, "version": v, "vulns": vulns} for n, v, vulns in deps]}


def vuln(id, fixes=(), aliases=("CVE-1",)):
    return {"id": id, "fix_versions": list(fixes), "aliases": list(aliases)}


def test_audit_classifies_runtime_nofix_and_dev_only(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    backend = write(
        tmp_path,
        "pip.json",
        pip_report(
            ("PyJWT", "2.10.1", [vuln("A", ["2.12.0"]), vuln("B", ["2.15.0"]), vuln("A", ["2.12.0"])]),
            ("starlette", "0.49.3", [vuln("S", ["1.3.1"])]),
            ("pyjwt", "2.10.1", [vuln("N")]),
            ("redis", "5.2.1", []),
        ),
    )
    browser = write(tmp_path, "browser.json", pip_report(("pyee", "13.0.0", [vuln("E", ["13.1"])])))
    tests = write(tmp_path, "tests.json", pip_report(("pytest", "9.0.1", [vuln("P", ["9.0.3"])])))
    npm_all = write(
        tmp_path,
        "npm-all.json",
        {
            "vulnerabilities": {
                "vite": {
                    "range": "7.0.0 - 7.3.6",
                    "fixAvailable": {"name": "vite", "version": "7.3.8", "isSemVerMajor": False},
                    "via": [{"url": "https://github.com/advisories/GHSA-x", "title": "dev server"}, "esbuild"],
                },
                "react-dom": {
                    "range": "<19.3",
                    "fixAvailable": True,
                    "via": [{"url": "https://github.com/advisories/GHSA-r", "title": "xss"}],
                },
                "transitive": {"range": "*", "fixAvailable": False, "via": ["vite"]},
            }
        },
    )
    npm_runtime = write(tmp_path, "npm-runtime.json", {"vulnerabilities": {"react-dom": {}}})
    lines, actionable, errors = ci_report.audit(
        [f"backend={backend}", f"browser-tests={browser}", f"backend-test={tests}"], npm_runtime, npm_all
    )
    text = "\n".join(lines)
    assert actionable and not errors
    assert "| **actionable** | 4 |" in text  # 2 pyjwt (deduplicated) + starlette + react-dom
    assert "| runtime-nofix | 1 |" in text
    assert "| dev-only | 3 |" in text  # pytest (test lock), pyee (browser tests), vite (devDependency)
    assert "| PyPI (backend-test) | pytest | 9.0.1 |" in text
    assert "| PyPI (backend) | PyJWT | 2.10.1 | 2: A, B | 2.15.0 |" in text
    assert "1.3.1 (major upgrade)" in text
    assert "| npm (frontend) | vite | 7.0.0 - 7.3.6 | 1: GHSA-x | vite@7.3.8 |" in text
    assert "transitive" not in text
    assert text.index("### actionable") < text.index("### runtime-nofix") < text.index("### dev-only")


def test_runtime_lock_findings_are_never_reclassified_by_name(tmp_path):
    """A test tool inside the runtime lock ships in the image: report it as runtime."""
    report = write(tmp_path, "pip.json", pip_report(("pytest", "9.0.1", [vuln("P", ["9.0.3"])])))
    lines, actionable, _ = ci_report.audit([f"backend={report}"], None, None)
    assert actionable and "| **actionable** | 1 |" in "\n".join(lines)


def test_audit_is_non_blocking_unless_requested(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    report = write(tmp_path, "pip.json", pip_report(("starlette", "0.49.3", [vuln("S", ["0.49.4"])])))
    args = ["audit", "--pip", f"backend={report}", "--summary"]
    assert ci_report.main(args) == 0
    assert ci_report.main(args + ["--fail-on-actionable"]) == 1
    out = capsys.readouterr().out
    assert "::warning::PyPI (backend) starlette 0.49.3: 1 advisories, upgrade to 0.49.4" in out
    assert "Dependency vulnerability report" in summary.read_text()


def test_audit_reports_unreadable_input_instead_of_crashing(tmp_path):
    lines, actionable, errors = ci_report.audit([f"backend={tmp_path / 'nope.json'}"], None, None)
    assert not actionable and errors and "unreadable" in "\n".join(lines)


def test_eslint_summary(tmp_path):
    report = write(
        tmp_path,
        "eslint.json",
        [
            {"filePath": "/x/main.tsx", "messages": [{"ruleId": "no-empty", "severity": 2}] * 2},
            {"filePath": "/x/ui.tsx", "messages": [{"ruleId": None, "severity": 2}]},
        ],
    )
    text = "\n".join(ci_report.eslint(report))
    assert "| `no-empty` | error | 2 |" in text and "| `parse` | error | 1 |" in text
    assert "main.tsx (2)" in text
