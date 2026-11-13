"""Read-only owned-catalog API smoke check on the synthetic loopback stack only."""

import argparse
import json
from pathlib import Path
import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--credentials", type=Path, required=True)
args = parser.parse_args()
credentials = json.loads(args.credentials.read_text())
with httpx.Client(base_url="http://127.0.0.1:18080/api/v1", timeout=30) as client:
    response = client.post("/auth/login", json=credentials)
    response.raise_for_status()
    roots = client.get("/reference/navigation")
    roots.raise_for_status()
    assert roots.json()["total"] == 13 and roots.json()["catalog_version_id"]
    coverage = client.get("/reference/navigation/coverage")
    coverage.raise_for_status()
    assert coverage.json()["parameter_source"] == "owned_catalog"
    found = client.get("/reference/navigation", params={"q": "Laptopok"})
    found.raise_for_status()
    node = next(n for n in found.json()["items"] if n["canonical_emag_id"] == 2000)
    assert node["unified_category_id"] >= 1_000_000_000
    parameters = client.get(f"/reference/navigation/{node['id']}/parameters")
    parameters.raise_for_status()
    assert parameters.json()["total"] == 1
    item = parameters.json()["items"][0]
    assert item["id"] >= 1_000_000_000 and item["parameter_id"] >= 1_000_000_000
    values = client.get(f"/reference/parameters/{item['id']}/values?view=all")
    values.raise_for_status()
    assert {v["value_text"] for v in values.json()["items"]} == {"Fekete", "Ezüst"}
    compatibility = client.get("/reference/parameters/70/values?view=all")
    compatibility.raise_for_status()
    assert compatibility.json()["items"] == values.json()["items"]
    print(
        json.dumps(
            {
                "owned_api": "passed",
                "roots": 13,
                "source_records": coverage.json()["source_record_counts"],
            }
        )
    )
