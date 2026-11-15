#!/usr/bin/env python3
"""Markdown reports for GitHub Actions job summaries (stdlib only).

Subcommands:
  junit  REPORT.xml...                 test totals, failures and slowest tests
  audit  --pip NAME=FILE... --npm-runtime FILE --npm-all FILE
         dependency vulnerabilities, classified as
           actionable  runtime dependency with a fixed version available
           runtime-nofix  runtime dependency, no fix published yet (assess/monitor)
           dev-only    test/build tooling not shipped in the images
  eslint REPORT.json                   ESLint rule counts (advisory)

The report is printed to stdout; with --summary it is also appended to
$GITHUB_STEP_SUMMARY. Actionable findings are emitted as ::warning::
annotations. The exit code is 0 unless --fail-on-actionable is given and
actionable findings exist, so reporting stays non-blocking by default.
"""

import argparse
import collections
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# Only the "backend" pip report is runtime: since SECURITY-02 it is audited from
# backend/requirements.lock, which holds exactly what the images install. Every
# other pip report (backend-test, browser-tests) is test tooling. No package is
# reclassified by name, so a test tool that slips into the runtime lock is
# reported as runtime, never hidden.
RUNTIME_PIP_LABELS = {"backend"}


def norm(name):
    return name.lower().replace("_", "-").replace(".", "-")


def emit(lines, summary):
    text = "\n".join(lines) + "\n"
    sys.stdout.write(text)
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(text)


def annotate(level, message):
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::{level}::{message}")


# --- junit -----------------------------------------------------------------


def junit(paths, title):
    totals = collections.Counter()
    failures, durations = [], []
    for path in paths:
        if not Path(path).exists():
            failures.append((path, "report missing (tests did not run)"))
            continue
        root = ET.parse(path).getroot()
        for case in root.iter("testcase"):
            name = f"{case.get('classname', '')}::{case.get('name', '')}"
            durations.append((float(case.get("time") or 0), name))
            outcome = "passed"
            for child in case:
                if child.tag in ("failure", "error"):
                    outcome = "failed" if child.tag == "failure" else "errors"
                    message = (child.get("message") or "").strip().splitlines()
                    failures.append((name, message[0][:200] if message else child.tag))
                elif child.tag == "skipped":
                    outcome = "skipped"
            totals[outcome] += 1
    lines = [f"### {title}", ""]
    lines.append(
        "| passed | failed | errors | skipped |\n|---:|---:|---:|---:|\n"
        f"| {totals['passed']} | {totals['failed']} | {totals['errors']} | {totals['skipped']} |"
    )
    if failures:
        lines += ["", "**Failures**", ""]
        lines += [f"- `{name}`: {message}" for name, message in failures[:50]]
    if durations:
        lines += ["", "<details><summary>Slowest tests</summary>", ""]
        lines += [f"- {seconds:.1f}s `{name}`" for seconds, name in sorted(durations, reverse=True)[:10]]
        lines += ["", "</details>"]
    return lines, bool(failures)


# --- dependency audit ------------------------------------------------------


def pip_findings(label, path):
    data = json.loads(Path(path).read_text())
    found = {}
    for dependency in data.get("dependencies", []):
        for vuln in dependency.get("vulns", []):
            key = (norm(dependency["name"]), vuln["id"])
            found[key] = {
                "ecosystem": f"PyPI ({label})",
                "package": dependency["name"],
                "version": dependency.get("version", "?"),
                "id": vuln["id"],
                "aliases": sorted(a for a in vuln.get("aliases", []) if a.startswith(("CVE", "GHSA"))),
                "fix": vuln.get("fix_versions") or [],
                "dev": label not in RUNTIME_PIP_LABELS,
            }
    return list(found.values())


def npm_findings(runtime_path, all_path):
    def load(path):
        if not path or not Path(path).exists():
            return {}
        return json.loads(Path(path).read_text() or "{}").get("vulnerabilities", {})

    runtime = load(runtime_path)
    findings = []
    for name, entry in load(all_path).items():
        advisories = [v for v in entry.get("via", []) if isinstance(v, dict)]
        if not advisories:
            continue  # only pulled in through another vulnerable package
        fix = entry.get("fixAvailable")
        if isinstance(fix, dict):
            fix_text = [f"{fix.get('name')}@{fix.get('version')}" + (" (major)" if fix.get("isSemVerMajor") else "")]
        else:
            fix_text = ["npm audit fix"] if fix else []
        for advisory in advisories:
            findings.append(
                {
                    "ecosystem": "npm (frontend)",
                    "package": name,
                    "version": entry.get("range", "?"),
                    "id": advisory.get("url", "").rsplit("/", 1)[-1] or str(advisory.get("source")),
                    "aliases": [advisory.get("title", "")[:90]],
                    "fix": fix_text,
                    "dev": name not in runtime,
                    "severity": advisory.get("severity", entry.get("severity")),
                }
            )
    return findings


def classify(finding):
    if finding["dev"]:
        return "dev-only"
    return "actionable" if finding["fix"] else "runtime-nofix"


def audit(pip_reports, npm_runtime, npm_all):
    findings = []
    errors = []
    for spec in pip_reports:
        label, _, path = spec.partition("=")
        try:
            findings += pip_findings(label, path)
        except (OSError, ValueError) as error:
            errors.append(f"pip-audit report `{path}` unreadable: {error}")
    try:
        findings += npm_findings(npm_runtime, npm_all)
    except (OSError, ValueError) as error:
        errors.append(f"npm audit report unreadable: {error}")

    groups = collections.defaultdict(list)
    for finding in findings:
        groups[classify(finding)].append(finding)
    lines = ["## Dependency vulnerability report", ""]
    lines.append(
        "| Class | Count | Meaning |\n|---|---:|---|\n"
        f"| **actionable** | {len(groups['actionable'])} | runtime dependency, fixed version exists: upgrade |\n"
        f"| runtime-nofix | {len(groups['runtime-nofix'])} | runtime dependency, no fix yet: assess exposure, monitor |\n"
        f"| dev-only | {len(groups['dev-only'])} | test/build tooling, not on the request path: upgrade when convenient |"
    )
    for error in errors:
        lines += ["", f"> ⚠️ {error}"]
    for group in ("actionable", "runtime-nofix", "dev-only"):
        if not groups[group]:
            continue
        lines += ["", f"### {group}", "", "| Ecosystem | Package | Version | Advisory | Fixed in |", "|---|---|---|---|---|"]
        by_package = collections.defaultdict(list)
        for finding in groups[group]:
            by_package[(finding["ecosystem"], finding["package"], finding["version"])].append(finding)
        for (ecosystem, package, version), items in sorted(by_package.items()):
            ids = ", ".join(sorted({f["id"] for f in items}))
            fixes = sorted({v for f in items for v in f["fix"]}, key=_version_key)
            target = fixes[-1] if fixes else "—"
            if fixes and not ecosystem.startswith("npm") and _major(target) != _major(version):
                target += " (major upgrade)"
            lines.append(f"| {ecosystem} | {package} | {version} | {len(items)}: {ids} | {target} |")
            if group == "actionable":
                annotate("warning", f"{ecosystem} {package} {version}: {len(items)} advisories, upgrade to {target}")
    return lines, bool(groups["actionable"]), errors


def _major(value):
    return value.split(".", 1)[0]


def _version_key(value):
    parts = []
    for piece in value.replace("-", ".").split("."):
        parts.append((0, int(piece)) if piece.isdigit() else (1, piece))
    return parts


# --- eslint ----------------------------------------------------------------


def eslint(path):
    data = json.loads(Path(path).read_text() or "[]")
    rules = collections.Counter()
    files = collections.Counter()
    for result in data:
        for message in result.get("messages", []):
            level = "error" if message.get("severity") == 2 else "warning"
            rules[(message.get("ruleId") or "parse", level)] += 1
            files[Path(result["filePath"]).name] += 1
    lines = ["## ESLint (advisory, not blocking)", ""]
    if not rules:
        return lines + ["No findings."]
    lines += ["| Rule | Level | Count |", "|---|---|---:|"]
    lines += [f"| `{rule}` | {level} | {count} |" for (rule, level), count in rules.most_common()]
    lines += ["", "Files: " + ", ".join(f"{name} ({count})" for name, count in files.most_common())]
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_junit = sub.add_parser("junit")
    p_junit.add_argument("reports", nargs="+")
    p_junit.add_argument("--title", default="Test results")
    p_audit = sub.add_parser("audit")
    p_audit.add_argument("--pip", action="append", default=[], metavar="LABEL=FILE")
    p_audit.add_argument("--npm-runtime")
    p_audit.add_argument("--npm-all")
    p_audit.add_argument("--fail-on-actionable", action="store_true")
    p_eslint = sub.add_parser("eslint")
    p_eslint.add_argument("report")
    for p in (p_junit, p_audit, p_eslint):
        p.add_argument("--summary", action="store_true", help="append to $GITHUB_STEP_SUMMARY")
    args = parser.parse_args(argv)

    if args.command == "junit":
        lines, _ = junit(args.reports, args.title)
        emit(lines, args.summary)
        return 0
    if args.command == "eslint":
        emit(eslint(args.report), args.summary)
        return 0
    lines, actionable, _ = audit(args.pip, args.npm_runtime, args.npm_all)
    emit(lines, args.summary)
    return 1 if actionable and args.fail_on_actionable else 0


if __name__ == "__main__":
    sys.exit(main())
