"""RC-03: read-only bridge from the UNAS schema registry (UNAS-REF-01) to the TEMPLATE-01
worktable generator. No writes; with an empty registry everything is a no-op, so the
template generator behaves exactly as before."""

from sqlalchemy import select

from app.unas_models import ParameterMapping, UnasFieldDefinition, UnasParameterDefinition


def fold(value):
    from app.product_catalog import fold as catalog_fold

    return catalog_fold(value or "")


class TemplateContext:
    def __init__(self, db):
        self.schema_source = db.scalar(
            select(UnasFieldDefinition.schema_source)
            .where(UnasFieldDefinition.scope == "standard",
                   UnasFieldDefinition.schema_source.like("unas_export/%"))
            .order_by(UnasFieldDefinition.id.desc()).limit(1))
        self.fields = {}
        if self.schema_source:
            for f in db.scalars(select(UnasFieldDefinition).where(
                    UnasFieldDefinition.schema_source == self.schema_source)):
                self.fields.setdefault(f.header, f)
        self.targets = {}
        for m in db.scalars(select(ParameterMapping).where(ParameterMapping.status == "approved")
                            .order_by(ParameterMapping.id)):
            if m.unas_parameter_id:
                target = db.get(UnasParameterDefinition, m.unas_parameter_id)
                header, kind = target.header, "unas_parameter"
            else:
                target = db.get(UnasFieldDefinition, m.unas_field_id)
                header, kind = target.header, "unas_field"
            self.targets.setdefault((m.emag_category_id, m.emag_parameter_id), []).append(
                {"header": header, "kind": kind, "mapping_id": m.id,
                 "unit_factor": str(m.unit_factor) if m.unit_factor is not None else None})

    def annotate(self, column):
        """Registry metadata for an UNAS worktable column (header is never changed)."""
        field = self.fields.get(column["header"])
        column["in_registry"] = field is not None
        if field is not None:
            column.update(unas_field_id=field.id, registry_requirement=field.requirement,
                          registry_requirement_source=field.requirement_source,
                          schema_source=self.schema_source)
        return column

    def target(self, donor, emag_parameter_id):
        """Approved UNAS target of an eMAG parameter: category-specific first, then global."""
        for key in ((donor, emag_parameter_id), (None, emag_parameter_id)):
            if self.targets.get(key):
                return self.targets[key][0]
        return None


def place_parameter(context, columns, column):
    """Add an eMAG parameter column unless an approved mapping points it at a column that is
    already present; returns the column that carries it."""
    target = context.target(column["donor"], column["emag_parameter_id"])
    if not target:
        columns.append(column)
        return column
    existing = next((c for c in columns if fold(c["header"]) == fold(target["header"])), None)
    link = {"key": column["key"], "donor": column["donor"],
            "emag_parameter_id": column["emag_parameter_id"], "mapping_id": target["mapping_id"]}
    if existing is not None:
        existing.setdefault("emag_parameters", []).append(link)
        if existing["kind"] == "parameter":
            existing.setdefault("donors", [existing["donor"]])
            if column["donor"] not in existing["donors"]:
                existing["donors"].append(column["donor"])
        return existing
    column.update(header=target["header"], unas_target=target["kind"],
                  mapping_id=target["mapping_id"], unit_factor=target["unit_factor"],
                  donors=[column["donor"]], emag_parameters=[link])
    columns.append(column)
    return column
