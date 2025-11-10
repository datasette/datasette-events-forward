import asyncio
from datasette.app import Datasette
import httpx
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
        # Allow multiple POST requests to the same URL
        def custom_response(request):
            return httpx.Response(200, json={"ok": True})

        httpx_mock.add_callback(
            custom_response, url="https://example.com/data/-/create"
        )

    db_path = str(tmpdir / "data.db")
    db = Database(db_path)
    db["foo"].insert({"id": 1}, pk="id")
    datasette = Datasette(
        [db_path],
        config={
            "plugins": {
                "datasette-events-forward": {
                    "api_url": (
                        "https://example.com/data/-/create" if configured else ""
                    ),
                    "api_token": "xxx",
                    "max_rate": 5,
                    "time_period": 0.2,
                }
            }
        },
    )
    datasette.root_enabled = True
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


@pytest.mark.asyncio
async def test_multiple_instances_no_interference(tmpdir):
    """Test that multiple datasette instances don't share state."""
    db_path1 = str(tmpdir / "data1.db")
    db1 = Database(db_path1)
    db1["foo"].insert({"id": 1}, pk="id")

    db_path2 = str(tmpdir / "data2.db")
    db2 = Database(db_path2)
    db2["foo"].insert({"id": 1}, pk="id")

    datasette1 = Datasette(
        [db_path1],
        config={
            "plugins": {
                "datasette-events-forward": {
                    "api_url": "https://example.com/data/-/create",
                    "api_token": "token1",
                    "max_rate": 10,
                    "time_period": 0.1,
                }
            }
        },
    )

    datasette2 = Datasette(
        [db_path2],
        config={
            "plugins": {
                "datasette-events-forward": {
                    "api_url": "https://example.com/data/-/create",
                    "api_token": "token2",
                    "max_rate": 20,
                    "time_period": 0.2,
                }
            }
        },
    )

    # Both should start up without issues
    await datasette1.invoke_startup()
    await datasette2.invoke_startup()

    # Verify they have separate state
    state1 = datasette1._datasette_events_forward_state
    state2 = datasette2._datasette_events_forward_state

    assert state1["rate_limit"] is not state2["rate_limit"]
    assert state1["lock"] is not state2["lock"]
    assert state1["tasks"] is not state2["tasks"]

    # Verify configs were applied separately
    assert state1["rate_limit"].max_rate == 10
    assert state2["rate_limit"].max_rate == 20
