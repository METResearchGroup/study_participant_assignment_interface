from datetime import datetime, timezone

CREATED_AT_FORMAT: str = "%Y_%m_%d-%H:%M:%S"


def get_current_timestamp() -> str:
    """Get the current timestamp in the contract format."""

    return datetime.now(tz=timezone.utc).strftime(CREATED_AT_FORMAT)  # noqa
