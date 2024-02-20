from aiolimiter import AsyncLimiter
import asyncio
from datasette import hookimpl
import datetime
import httpx
from ulid import ULID
import json


CREATE_TABLE_SQL = """
create table if not exists datasette_events_to_forward (
    id text primary key,
    event text,
    created text,
    actor_id text,
    database_name text,
    table_name text,
    properties text, -- JSON other properties
    sent_at text
)
"""

# Allow 1 every 10s
rate_limit = AsyncLimiter(max_rate=1, time_period=3)

# Send this many events at a time
LIMIT = 10

async def send_events(datasette):
    db = datasette.get_internal_database()
    config = datasette.plugin_config("datasette-events-forward") or {}
    instance = config.get("instance")
    api_url = config.get("api_url")
    api_token = config.get("api_token")
    if not api_url:
        return
    rows = list((await db.execute("select * from datasette_events_to_forward where sent_at is null order by id limit {}".format(LIMIT + 1))).rows)
    if not rows:
        return
    should_run_again = False
    if len(rows) > LIMIT:
        rows = rows[:LIMIT]
        should_run_again = True

    # send the rows to the external service
    rows = [dict(row, instance=instance) for row in rows]
    # HTTPX async POST that to api_url
    async with httpx.AsyncClient() as client:
        response = await client.post(api_url, json={
            "table": "datasette_events",
            "rows": rows,
            "ignore": True,
            "pk": "id",
        }, headers={
            "Authorization": "Bearer {}".format(api_token)
        })
        if str(response.status_code).startswith("2"):
            # It worked! Mark the rows as sent
            await db.execute_write(
                "update datasette_events_to_forward set sent_at = ? where id in ({})".format(
                    ",".join(["?"] * len(rows))
                ),
                [datetime.datetime.utcnow().isoformat()] + [row["id"] for row in rows],
            )
        else:
            # Schedule a retry task
            should_run_again = True
    if should_run_again:
        asyncio.create_task(rate_limited_send_events(datasette))


async def rate_limited_send_events(datasette):
    async with rate_limit:
        await send_events(datasette)


@hookimpl
def startup(datasette):
    async def inner():
        db = datasette.get_internal_database()
        await db.execute_write(CREATE_TABLE_SQL)
        asyncio.create_task(rate_limited_send_events(datasette))

    return inner


@hookimpl
def track_event(datasette, event):
    async def inner():
        db = datasette.get_internal_database()
        properties = event.properties()
        # pop off the database and table properties if they exist
        database_name = properties.pop("database", None)
        table_name = properties.pop("table", None)
        placeholders = []
        values = []
        # A ? for each value that is not None, null for the others
        placeholders.append("?")
        values.append(str(ULID()))
        placeholders.append("?")
        values.append(event.name)
        placeholders.append("?")
        values.append(event.created.isoformat())
        if event.actor:
            placeholders.append("?")
            values.append(event.actor.get("id"))
        else:
            placeholders.append("null")
        if database_name:
            placeholders.append("?")
            values.append(database_name)
        else:
            placeholders.append("null")
        if table_name:
            placeholders.append("?")
            values.append(table_name)
        else:
            placeholders.append("null")
        placeholders.append("?")
        values.append(json.dumps(properties))
        await db.execute_write(
            "insert into datasette_events_to_forward (id, event, created, actor_id, database_name, table_name, properties) values ({})".format(
                ",".join(placeholders)
            ),
            values,
        )
        asyncio.create_task(rate_limited_send_events(datasette))

    return inner