from conftest import login


def observation(**kwargs):
    return {
        "source_key": "emag_webshop",
        "evidence_url": "https://www.emag.hu/",
        "outcome": "blocked",
        "summary": "A forrás elérése nem ellenőrizhető; teljesség nem állítható.",
        **kwargs,
    }


def test_source_observation_is_global_audited_and_not_a_category(environment):
    client, *_ = environment
    login(client)
    response = client.post(
        "/api/v1/reference/sources/observations",
        json=observation(source_category_id="web-123"),
    )
    assert (
        response.status_code == 201 and response.json()["mapping_status"] == "pending"
    )
    assert client.get("/api/v1/reference/sources/observations").json()["total"] == 1
    assert client.get("/api/v1/reference/coverage").json()["reference_total"] == 6
    assert client.get("/api/v1/reference/sources").json()["automatic_mapping"] is False
    assert any(
        e["action"] == "reference.source_observation"
        for e in client.get("/api/v1/audit").json()["items"]
    )
    login(client, "processor@example.hu")
    assert client.get("/api/v1/reference/sources").status_code == 200
    assert (
        client.post(
            "/api/v1/reference/sources/observations", json=observation()
        ).status_code
        == 403
    )


def test_name_match_cannot_confirm_mapping_and_source_urls_are_constrained(environment):
    client, *_ = environment
    login(client)
    assert (
        client.post(
            "/api/v1/reference/sources/observations",
            json=observation(mapping_status="confirmed", canonical_emag_id=2000),
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/reference/sources/observations",
            json=observation(evidence_url="http://localhost/"),
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/reference/sources/observations",
            json=observation(evidence_url="https://www.emag.hu/?token=secret"),
        ).status_code
        == 422
    )
    verified = observation(
        outcome="available",
        source_category_id="explicit-2000",
        canonical_emag_id=2000,
        mapping_status="confirmed",
        evidence_kind="explicit_marketplace_id",
        content_sha256="a" * 64,
    )
    assert (
        client.post("/api/v1/reference/sources/observations", json=verified).status_code
        == 201
    )
    verified["canonical_emag_id"] = 987654
    assert (
        client.post("/api/v1/reference/sources/observations", json=verified).status_code
        == 409
    )
