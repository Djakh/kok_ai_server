import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.common.db.session import engine
from app.modules.trees.models import Tree, TreeStatus
from app.modules.trees.repository import TreeRepository


def test_map_queries_accept_omitted_status_on_postgis() -> None:
    try:
        connection = engine.connect()
    except OperationalError:
        pytest.skip("PostgreSQL is not reachable from this test process")
    if connection.dialect.name != "postgresql":
        connection.close()
        pytest.skip("This regression requires PostgreSQL/PostGIS")

    db = Session(bind=connection)
    try:
        owner_id = db.query(Tree.owner_user_id).first()
        if owner_id is None:
            pytest.skip("PostgreSQL test database has no seeded trees")
        viewer_id = owner_id[0]
        repo = TreeRepository(db)

        bbox_rows = repo.map_bbox(69.0, 41.0, 69.5, 41.5, None, viewer_id)
        assert bbox_rows
        expected_bbox_ids = db.execute(
            text(
                """
                SELECT t.id
                FROM trees t
                JOIN tree_locations tl ON tl.tree_id = t.id
                WHERE t.deleted_at IS NULL
                  AND ST_Intersects(
                    tl.location::geometry,
                    ST_MakeEnvelope(:west, :south, :east, :north, 4326)
                  )
                """
            ),
            {"west": 69.0, "south": 41.0, "east": 69.5, "north": 41.5},
        ).scalars()
        assert {row.id for row in bbox_rows} == set(expected_bbox_ids)

        owned_rows = repo.list_trees(
            None, 200, None, None, None, "newest", viewer_id
        )
        assert all(row.owner_user_id == viewer_id for row in owned_rows)

        named_filter_rows = repo.map_bbox(
            69.0, 41.0, 69.5, 41.5, TreeStatus.VERIFIED.value, viewer_id
        )
        assert named_filter_rows
        assert all(row.status is TreeStatus.VERIFIED for row in named_filter_rows)

        radius_rows = repo.map_center_radius(41.2995, 69.2401, 50_000, None, viewer_id)
        assert radius_rows
    finally:
        db.close()
        connection.close()


def test_map_query_with_unknown_status_is_rejected_by_api(client) -> None:
    response = client.get(
        "/api/v1/trees/map?bbox=69.0,41.0,69.5,41.5&status=unknown"
    )
    assert response.status_code == 422
