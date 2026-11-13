import pytest
from conftest import login


@pytest.fixture
def extra_reference_categories():
    return [
        dict(
            id=100000 + i,
            emag_category_id=200000 + i,
            parent_id=200000 + i - 1 if i else None,
            name=f"Mély ág {i}",
            is_allowed=i == 999,
        )
        for i in range(1000)
    ]


def test_lazy_tree_and_full_deep_path_use_constant_query_count(environment):
    client, _, _, statements = environment
    login(client)
    statements.clear()
    roots = client.get("/api/v1/reference/categories?limit=100")
    assert roots.status_code == 200 and roots.json()["total"] == 4
    assert len(roots.json()["items"]) == 4 and len(roots.content) < 20000
    assert len(statements) == 2
    statements.clear()
    detail = client.get("/api/v1/reference/categories/100999").json()
    assert len(detail["path"]) == 1000
    assert detail["selectable"] and not detail["ancestors"][0]["selectable"]
    assert len(statements) == 2  # metadata plus grouped direct parameter counts
