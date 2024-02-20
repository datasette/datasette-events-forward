import asyncio
from datasette_test import Datasette
import json
from sqlite_utils import Database
import pytest


@pytest.fixture
def non_mocked_hosts():
    return ["localhost"]


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", (True, False))
async def test_events_forward(tmpdir, configured, httpx_mock):
    if configured:
        httpx_mock.add_response(
            url="https://example.com/data/-/create", json={"ok": True}
        )

    db_path = str(tmpdir / "data.db")
    db = Database(db_path)
    db["foo"].insert({"id": 1}, pk="id")
    datasette = Datasette(
        [db_path],
        plugin_config={
            "datasette-events-forward": {
                "api_url": "https://example.com/data/-/create" if configured else "",
                "api_token": "xxx",
                "rate_limit": 5,
                "time_period": 0.2,
            }
        },
    )
    await datasette.invoke_startup()
    # Should have created the internal table
    internal_db = datasette.get_internal_database()
    assert await internal_db.table_exists("datasette_events_to_forward")
    # Now we trigger an event
    token = datasette.create_token("root")
    response = await datasette.client.post(
        "/data/-/create",
        json={"table": "hello", "row": {"id": 1}, "pk": "id"},
        headers={"Authorization": "Bearer {}".format(token)},
    )
    assert response.status_code == 201
    if not configured:
        # Should NOT have added row to table
        count = (
            await internal_db.execute(
                "select count(*) from datasette_events_to_forward"
            )
        ).rows[0][0]
        assert not count
        return

    # Should have added a row to that table
    to_forward = dict(
        (await internal_db.execute("select * from datasette_events_to_forward")).rows[0]
    )
    # Should not have been sent yet
    assert to_forward["event"] == "create-table"
    assert to_forward["database_name"] == "data"
    assert to_forward["table_name"] == "hello"
    # Wait 0.3s to give things time to be delivered
    await asyncio.sleep(0.3)
    # Table should be empty now
    to_forward_count = (
        await internal_db.execute("select count(*) from datasette_events_to_forward")
    ).rows[0][0]
    assert to_forward_count == 0
    # And the request should have been caught
    request = httpx_mock.get_request()
    assert request.url == "https://example.com/data/-/create"
    assert request.headers["authorization"] == "Bearer xxx"
    sent_data = json.loads(request.content)
    assert sent_data["table"] == "datasette_events"
    assert len(sent_data["rows"]) == 2
    assert {row["event"] for row in sent_data["rows"]} == {
        "create-table",
        "insert-rows",
    }
