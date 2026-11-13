"""Reviewed semantic donor choices. Profiles never merge flags or allowed values."""

from functools import lru_cache
import json
from pathlib import Path
from app.unified_categories import normalized


@lru_cache(maxsize=1)
def reviewed_bindings():
    return json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "reference_data/reviewed_parameter_bindings.json"
        ).read_text(encoding="utf-8")
    )


def resolve_profiles(nav, tree, matched):
    profiles = {key: [source] for key, source in nav.bindings.items()}
    fixed = nav.nodes
    warnings = []
    for rule in reviewed_bindings()["rules"]:
        key = rule["node_id"]
        if (
            key not in fixed
            or fixed[key]["kind"] != "category"
            or fixed[key].get("structural_only")
        ):
            continue
        if [fixed[p]["name"] for p in nav.path(key)] != rule["path"]:
            raise ValueError(
                "Reviewed parameter rule path differs from approved taxonomy: " + key
            )
        if key in matched.blocked or matched.methods.get(key) in {
            "administrator",
            "administrator_legacy",
        }:
            continue  # Explicit operator decisions remain authoritative.
        donors = []
        for donor in rule["donors"]:
            internal = tree.external.get(donor["emag_category_id"])
            if internal is not None and normalized(
                tree.rows[internal]["name"]
            ) == normalized(donor["expected_name"]):
                donors.append(internal)
            else:
                warnings.append(
                    {
                        "node_id": key,
                        "source_emag_id": donor["emag_category_id"],
                        "reason": "reviewed_source_missing_or_renamed",
                    }
                )
        if not donors:
            # A known reviewed category must not fall back to an unrelated,
            # same-named donor if this source snapshot lacks the reviewed IDs.
            profiles.pop(key, None)
            nav.bindings.pop(key, None)
            nav.methods.pop(key, None)
        if donors:
            profiles[key] = donors
            nav.bindings[key] = donors[0]
            nav.candidates[key] = donors
            nav.methods[key] = (
                "reviewed_profiles" if len(donors) > 1 else "reviewed_semantic"
            )
    nav.parameter_donors, nav.profile_warnings = profiles, warnings


def profile_info(nav, key, targets=None):
    result = []
    for internal in nav.parameter_donors.get(key, []):
        row = nav.reference.rows[internal]
        counts = nav.reference.counts.get(internal, {})
        total = counts.get("total", 0)
        mandatory, optional = counts.get("mandatory", 0), counts.get("optional", 0)
        result.append(
            dict(
                source_category_id=targets[internal]
                if targets is not None
                else internal,
                emag_category_id=row["emag_category_id"],
                name=row["name"],
                parameter_count=total,
                mandatory_parameter_count=mandatory,
                optional_parameter_count=optional,
                unknown_parameter_count=total - mandatory - optional,
            )
        )
    return result


def choose_profile(nav, key, external=None):
    from fastapi import HTTPException

    donors = nav.parameter_donors.get(key, [])
    if key in nav.blocked and not donors:
        raise HTTPException(409, "A paraméter-hozzárendelést korábban visszavonták.")
    if external is not None:
        donor = next(
            (
                c
                for c in donors
                if nav.reference.rows[c]["emag_category_id"] == external
            ),
            None,
        )
        if donor is None:
            raise HTTPException(
                409, "Ez a paraméterprofil nem tartozik a kiválasztott kategóriához."
            )
        return donor
    if len(donors) > 1:
        raise HTTPException(
            409, "Több külön paraméterprofil érhető el. Válassz paraméterprofilt."
        )
    return donors[0] if donors else None
