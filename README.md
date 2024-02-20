# datasette-events-forward

[![PyPI](https://img.shields.io/pypi/v/datasette-events-forward.svg)](https://pypi.org/project/datasette-events-forward/)
[![Changelog](https://img.shields.io/github/v/release/datasette/datasette-events-forward?include_prereleases&label=changelog)](https://github.com/datasette/datasette-events-forward/releases)
[![Tests](https://github.com/datasette/datasette-events-forward/actions/workflows/test.yml/badge.svg)](https://github.com/datasette/datasette-events-forward/actions/workflows/test.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/datasette/datasette-events-forward/blob/main/LICENSE)

Forward Datasette events to another instance

## Installation

Install this plugin in the same environment as Datasette.
```bash
datasette install datasette-events-forward
```

## Configuration

Configure the plugin like so:

```json
{
    "plugins": {
        "datasette-events-forward": {
            "api_token": "***",
            "api_url": "https://stats.datasette.cloud/data/-/create",
            "instance": "localhost"
        }
    }
}
```
The plugin will then gather all events and forward them to the specified instance, adding them to a table called `datasette_events` which will be created if it does not exist.

The `instance` key can be used to differentiate different instances that report to the same backend. Events are identified with a ULID to ensure they are unique even across different instances.

Events are forwarded in batches of up to 10, no more than once every 10 seconds.

Full list of configuration settings:

- `api_url`: The URL to send the events to. This should be the write API endpoint of a Datasette instance.
- `api_token`: The API token to use when sending events. Use `{"$env": "FORWARD_TOKEN"}` to read the token from the `FORWARD_TOKEN` environment variable.
- `instance`: A string to identify the instance that is sending the events.
- `batch_limit`, defaults to 10: The number of events to send at once. The Datasette write API has a 100 row limit by default so this should be set to a value less than that.

## Development

To set up this plugin locally, first checkout the code. Then create a new virtual environment:
```bash
cd datasette-events-forward
python3 -m venv venv
source venv/bin/activate
```
Now install the dependencies and test dependencies:
```bash
pip install -e '.[test]'
```
To run the tests:
```bash
pytest
```
