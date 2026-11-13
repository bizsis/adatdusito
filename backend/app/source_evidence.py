"""Conservative public structured-data evidence, never a name-based crosswalk."""

import json
from html.parser import HTMLParser
from urllib.parse import urlparse


class JsonLd(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.parts = []
        self.documents = []

    def handle_starttag(self, tag, attrs):
        if (
            tag == "script"
            and dict(attrs).get("type", "").lower() == "application/ld+json"
        ):
            self.active = True
            self.parts = []

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.active:
            self.active = False
            try:
                self.documents.append(json.loads("".join(self.parts)))
            except (ValueError, RecursionError):
                pass


def breadcrumb_observations(html):
    if len(html) > 1000000:
        raise ValueError("A bizonyíték túl nagy.")
    parser = JsonLd()
    parser.feed(html)
    pending = list(parser.documents)
    result = []
    visited = 0
    while pending and visited < 10000:
        doc = pending.pop()
        visited += 1
        if isinstance(doc, list):
            pending.extend(doc)
            continue
        if not isinstance(doc, dict):
            continue
        if doc.get("@type") == "BreadcrumbList":
            chain = []
            for item in doc.get("itemListElement", []):
                if not isinstance(item, dict):
                    continue
                value = item.get("item", {})
                url = (
                    value
                    if isinstance(value, str)
                    else value.get("@id")
                    if isinstance(value, dict)
                    else None
                )
                name = item.get("name") or (
                    value.get("name") if isinstance(value, dict) else None
                )
                if not isinstance(name, str) or not isinstance(url, str):
                    continue
                parsed = urlparse(url)
                if (
                    parsed.scheme != "https"
                    or not parsed.hostname
                    or not (
                        parsed.hostname == "emag.hu"
                        or parsed.hostname.endswith(".emag.hu")
                    )
                ):
                    continue
                chain.append(
                    {
                        "name": name,
                        "source_category_id": url,
                        "position": item.get("position"),
                        "canonical_emag_id": None,
                        "mapping_status": "pending",
                    }
                )
            if chain:
                result.append(chain)
        else:
            pending.extend(
                value for value in doc.values() if isinstance(value, (dict, list))
            )
    return result
