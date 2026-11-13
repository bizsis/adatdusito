"""Bounded manual source probe, not a crawler or synchronization service.

Fetches only robots, sitemap manifests, home navigation and documentation.
Never downloads the product catalog, bypasses access denial, or writes a DB.
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import urllib.error
import urllib.request
from urllib.robotparser import RobotFileParser

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
urls = [
    "https://www.emag.hu/robots.txt",
    "https://www.emag.hu/sitemap.xml",
    "https://www.emag.hu/",
    "https://marketplace.emag.hu/infocenter/emag-api/",
]
reports = []
robots = None
for url in urls:
    row = {
        "url": url,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "webshop_completeness": "unverified",
    }
    if (
        url.startswith("https://www.emag.hu/")
        and not url.endswith("/robots.txt")
        and (robots is None or not robots.can_fetch("AdatdusitoReferenceResearch", url))
    ):
        row.update(outcome="not_fetched", reason="robots_not_verified_or_disallowed")
        reports.append(row)
        continue
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "AdatdusitoReferenceResearch/0.1"}
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            content = response.read(1000001)
            if len(content) > 1000000:
                raise ValueError("size_limit_1MB")
            row.update(
                outcome="available",
                status=response.status,
                bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )
            if url.endswith("/robots.txt"):
                robots = RobotFileParser(url)
                robots.parse(content.decode("utf-8", errors="replace").splitlines())
                row["sitemap_manifests"] = robots.site_maps() or []
    except Exception as error:
        row.update(outcome="blocked_or_unavailable", reason=str(error)[:300])
    reports.append(row)
args.output.write_text(
    json.dumps(
        {
            "sources": reports,
            "automatic_mapping": False,
            "reference_database_writes": False,
        },
        ensure_ascii=False,
        indent=2,
    )
)
print("Forrásvizsgálati jelentés:", args.output)
