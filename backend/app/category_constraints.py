"""Category-specific restrictions; source definitions and values remain immutable."""

from app.unified_categories import normalized

LOADING = {
    "web-item-114-3490": "Elöltöltős",
    "web-item-114-3491": "Felültöltős",
}


def annotate_parameters(node_id, page):
    """Apply a loading restriction only when the source defines that parameter.

    The restriction describes the category's accepted value, not a fabricated
    source value ID. Unknown/missing source definitions never gain parameters.
    """
    expected = LOADING.get(node_id)
    if expected:
        for parameter in page["items"]:
            if normalized(parameter["name"]) in {
                normalized(name)
                for name in (
                    "Betöltés típusa",
                    "Betöltés típusa mosógép",
                    "Töltés típusa",
                    "Betöltés módja",
                    "Töltési mód",
                    "Loading type",
                    "Load type",
                )
            }:
                parameter["category_constraint"] = {
                    "operator": "equals",
                    "value_text": expected,
                    "source_values_unchanged": True,
                }
    return page
