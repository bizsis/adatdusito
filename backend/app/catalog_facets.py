"""Resolve TV navigation filters only against actual contextual allowed values."""

from sqlalchemy import select
from app.models import (
    CatalogNode,
    CatalogLinkEntry,
    CatalogParameter,
    CatalogSourceMapping,
    CatalogValue,
)
from app.catalog_constants import SOURCE
from app.unified_categories import normalized

FILTERS = {
    "LED TV": ({"led"}, {"technologia", "technológia", "típus", "tipus"}),
    "OLED TV": ({"oled"}, {"technológia", "típus"}),
    "QLED TV": ({"qled"}, {"technológia", "típus"}),
    "Ambilight TV": ({"igen", "yes", "true", "ambilight"}, {"ambilight"}),
    "Smart TV": ({"igen", "yes", "true", "smart"}, {"smart"}),
    "HD TV": ({"hd", "hd ready", "1366 x 768"}, {"felbontás"}),
    "Full HD TV": ({"full hd", "1920 x 1080"}, {"felbontás"}),
    "4K Ultra HD": ({"4k", "4k ultra hd", "ultra hd", "3840 x 2160"}, {"felbontás"}),
    "8K": ({"8k", "7680 x 4320"}, {"felbontás"}),
}


def resolve_tv_filters(db, run, data_id):
    node = db.get(CatalogNode, (run.id, "web-item-43-3730"))
    if not node or node.category_id is None:
        return
    entries = list(
        db.execute(
            select(CatalogLinkEntry, CatalogParameter)
            .join(
                CatalogParameter, CatalogParameter.id == CatalogLinkEntry.parameter_id
            )
            .where(
                CatalogLinkEntry.version_id == data_id,
                CatalogLinkEntry.category_id == node.category_id,
            )
        )
    )
    result = []
    for label, (values, hints) in FILTERS.items():
        candidates = []
        accepted = {normalized(v) for v in values}
        for entry, definition in entries:
            if not any(normalized(h) in normalized(definition.name) for h in hints):
                continue
            # SQL restricts by category link and actual value texts; never loads a
            # category's complete allowed-value domain or invents a source ID.
            rows = db.execute(
                select(CatalogValue.id, CatalogValue.value_text)
                .join(
                    CatalogSourceMapping,
                    CatalogSourceMapping.target_id == CatalogValue.id,
                )
                .where(
                    CatalogSourceMapping.version_id == data_id,
                    CatalogSourceMapping.kind == "value",
                    CatalogSourceMapping.source_key == SOURCE,
                    CatalogSourceMapping.context_id == entry.link_id,
                    CatalogValue.value_text.in_(
                        sorted(
                            values
                            | {v.upper() for v in values}
                            | {v.title() for v in values}
                        )
                    ),
                )
                .distinct()
                .limit(20)
            ).all()
            for row in rows:
                if normalized(row.value_text) in accepted:
                    candidates.append(
                        {
                            "link_id": entry.link_id,
                            "parameter_id": definition.id,
                            "parameter_name": definition.name,
                            "value_id": row.id,
                            "value_text": row.value_text,
                        }
                    )
        result.append(
            {
                "name": label,
                "status": "linked"
                if len(candidates) == 1
                else "ambiguous"
                if candidates
                else "unresolved",
                "match": candidates[0] if len(candidates) == 1 else None,
            }
        )
    node.data = {**node.data, "related_parameter_filters": result}
