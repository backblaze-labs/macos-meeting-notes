"""Per-instance SDK transport admission without shared settings mutation."""

from contextlib import contextmanager


@contextmanager
def assemblyai_session(aai, api_key, poll_interval, before_request):
    remaining = before_request()
    settings = aai.types.Settings(
        _env_file=None,
        api_key=api_key,
        base_url="https://api.assemblyai.com",
        http_timeout=remaining,
        sync_http_timeout=remaining,
        polling_interval=max(float(poll_interval), 0.001),
    )
    client = aai.Client(settings=settings)

    def admit(request):
        timeout = before_request()
        request.extensions["timeout"] = dict.fromkeys(("connect", "read", "write", "pool"), timeout)

    client.http_client.event_hooks.setdefault("request", []).append(admit)
    try:
        yield client
    finally:
        client.http_client.close()
