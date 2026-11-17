"""KNOWLEDGE-02 (migration 0016) on an EMPTY loopback MySQL 8: additive upgrade over KNOWLEDGE-01
data, guarded downgrade (refuses before any DDL), copy-suspicion SQL, merge apply/revert and a
MEDIUMTEXT description variant.

Requires KNOWLEDGE02_FIXTURE_ACK=isolated-knowledge-02. Never use on a VPS, a shared database or
pinfo_db. Synthetic records only; prints no credentials and drops no database.
"""

import os
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def ok(message):
    print(f"OK {message}", flush=True)


def main():
    from sqlalchemy import create_engine, delete, inspect, make_url, select, text, update
    from sqlalchemy.orm import Session

    if os.getenv("KNOWLEDGE02_FIXTURE_ACK") != "isolated-knowledge-02":
        raise SystemExit("Refusing: explicit isolated KNOWLEDGE-02 fixture acknowledgement "
                         "required.")
    url = make_url(os.environ["APP_DATABASE_URL"])
    if (url.get_backend_name() != "mysql" or url.host not in {"127.0.0.1", "localhost", "::1"}
            or url.database != "adatdusito_dev"):
        raise SystemExit("Refusing: expected an empty loopback MySQL adatdusito_dev fixture.")
    engine = create_engine(url, pool_pre_ping=True)
    with engine.connect() as c:
        if inspect(c).get_table_names():
            raise SystemExit("Refusing: fixture schema must be empty.")
        assert c.scalar(text("SELECT VERSION()")).startswith("8.")
    # The reference database must never be contacted by this check.
    os.environ["REFERENCE_DATABASE_URL"] = "mysql+pymysql://blocked:blocked@127.0.0.1:1/pinfo_db"

    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(ROOT / "backend/alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend/migrations"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert heads == ["0016"], heads
    ok("single Alembic head 0016")

    def version():
        with engine.connect() as c:
            return c.scalar(text("SELECT version_num FROM alembic_version"))

    def tables():
        with engine.connect() as c:
            return set(inspect(c).get_table_names())

    command.upgrade(cfg, "0015")
    from app.models import User

    with Session(engine) as db:
        db.add(User(id=1, email="root@example.invalid", name="Synthetic Root",
                    password_hash="not-a-login", superadmin=True))
        db.commit()
    with engine.begin() as c:  # KNOWLEDGE-01 data that must survive
        c.execute(text("INSERT INTO knowledge_products(id,status,created_at,updated_at) "
                       "VALUES (900,'active',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        c.execute(text("INSERT INTO knowledge_values(id,knowledge_product_id,attribute_key,"
                       "attribute_label,value_norm,status,confidence,support_sources,"
                       "observations,rejected_values,updated_at) VALUES (900,900,'brand',"
                       "'Márka','txt:legacy','candidate',0.6,1,1,'[]',CURRENT_TIMESTAMP)"))
    before = tables()
    command.upgrade(cfg, "0016")
    assert version() == "0016"
    new = {"knowledge_source_relations", "knowledge_merges", "knowledge_texts"}
    assert tables() - before == new
    with engine.connect() as c:
        kind = c.scalar(text("SELECT DATA_TYPE FROM information_schema.COLUMNS WHERE "
                             "TABLE_SCHEMA=DATABASE() AND TABLE_NAME='knowledge_texts' AND "
                             "COLUMN_NAME='text'"))
        assert kind == "mediumtext", kind
        legacy = c.execute(text("SELECT value_norm, independent_sources FROM knowledge_values "
                                "WHERE id=900")).one()
        assert tuple(legacy) == ("txt:legacy", 0)
    ok("0015 -> 0016 additive; KNOWLEDGE-01 value kept; knowledge_texts.text is MEDIUMTEXT")
    command.downgrade(cfg, "0015")
    assert version() == "0015" and tables() == before
    command.upgrade(cfg, "0016")
    ok("0016 -> 0015 -> 0016 without decisions")

    from app import knowledge as kb
    from app.knowledge_models import (
        KnowledgeLink,
        KnowledgeObservation,
        KnowledgeProduct,
        KnowledgeSourceRelation,
        KnowledgeText,
        KnowledgeValue,
    )
    from app.system_config import DEFAULTS, store
    from app.unas_models import ReferenceProductSource

    kb.schedule = lambda **kw: None  # no broker here
    with Session(engine) as db:
        store(db, "knowledge", {**DEFAULTS["knowledge"], "copy_min_shared_values": 3,
                                "copy_min_identical_texts": 2})
        sources = []
        for key in ("k2-a", "k2-b"):
            s = ReferenceProductSource(key=key, name=key, kind="unas_export",
                                       usage_status="approved_enrichment", usage_basis="test",
                                       enrichment_enabled=True, contribution="automatic",
                                       excluded_columns=[])
            db.add(s)
            sources.append(s)
        products = [KnowledgeProduct(status="active") for _ in range(3)]
        db.add_all(products)
        db.flush()
        long_text = ("A termék kiváló minőségű és tartós. " * 3000)[:100_000]  # > 64 KB
        member = 0
        for index, (product, src) in enumerate([(products[0], sources[0]),
                                                (products[0], sources[1]),
                                                (products[1], sources[0]),
                                                (products[1], sources[1]),
                                                (products[2], sources[1])]):
            member += 1
            link = KnowledgeLink(member_kind="reference_product", member_id=member,
                                 source_id=src.id, knowledge_product_id=product.id,
                                 method="gtin", confidence=Decimal("1"))
            db.add(link)
            db.flush()
            for key, raw in (("brand", "Acme"), ("unas:szelesseg", "60"),
                             ("unas:magassag", "85")):
                db.add(KnowledgeObservation(
                    knowledge_product_id=product.id, link_id=link.id, source_id=src.id,
                    attribute_key=key, attribute_label=key, value_raw=raw,
                    value_norm=kb.normalize(raw)[0], origin="reference",
                    confidence=Decimal("0.6"), current=True, identity_confidence=Decimal("1")))
            if index < 4:
                db.add(KnowledgeText(
                    knowledge_product_id=product.id, link_id=link.id, source_id=src.id,
                    kind="long_description", text=long_text + str(product.id),
                    text_hash=f"{product.id:064d}", format="plain", language="hu",
                    language_confidence=Decimal("0.9"), language_method="heuristic",
                    verification="unverified", usage="inherited", pii_flags=[], current=True))
        db.commit()
        counters = kb.rebuild(db)
        relation = db.scalar(select(KnowledgeSourceRelation))
        assert relation.state == "suspected" and relation.identical_texts == 2, relation.state
        assert counters["relations_changed"] == 1
        brand = db.scalar(select(KnowledgeValue).where(
            KnowledgeValue.knowledge_product_id == products[0].id,
            KnowledgeValue.attribute_key == "brand"))
        assert brand.independent_sources == 1 and brand.confidence == Decimal("0.6")
        assert brand.status == "candidate"
        ok("copy-suspicion self-join on MySQL: suspected pair counts once, never verified")
        stored = db.scalar(select(KnowledgeText.text).where(
            KnowledgeText.knowledge_product_id == products[0].id))
        assert len(stored) > 65_535
        preview = kb.merge_preview(db, products[0].id, products[2].id)
        record = kb.merge_apply(db, products[0].id, products[2].id, preview["preview_token"],
                                "check", 1, acknowledge_variant_risk=preview["variant_risk"])
        db.commit()
        assert db.get(KnowledgeProduct, products[2].id).status == "merged"
        kb.merge_revert(db, record, 1, "check")
        db.commit()
        assert db.get(KnowledgeProduct, products[2].id).status == "active"
        ok("merge preview/apply/revert on MySQL; >64 KB description variant stored")
        merge_id = record.id

    # A recorded decision blocks the downgrade before any DDL.
    try:
        command.downgrade(cfg, "0015")
    except RuntimeError as exc:
        assert "backup" in str(exc)
    else:
        raise AssertionError("downgrade with decisions must be refused")
    assert version() == "0016" and new <= tables()
    ok("downgrade refused with merge history; schema untouched")
    with Session(engine) as db:
        db.execute(delete(KnowledgeText))
        db.execute(update(KnowledgeSourceRelation).values(decided_by=None))
        db.execute(text("DELETE FROM knowledge_merges WHERE id=:id"), {"id": merge_id})
        db.commit()
    command.downgrade(cfg, "0015")
    assert version() == "0015" and tables() == before
    command.upgrade(cfg, "head")
    assert version() == "0016"
    with engine.connect() as c:
        assert c.scalar(text("SELECT value_norm FROM knowledge_values WHERE id=900")) == \
            "txt:legacy"
    ok("0016 -> 0015 -> head after clean-up; KNOWLEDGE-01 data preserved; pinfo_db untouched")


if __name__ == "__main__":
    main()
