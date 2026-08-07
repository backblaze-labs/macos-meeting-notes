"""Tests for the Google API HTTP transport."""

from __future__ import annotations

import socket

import httplib2

from meeting_memory.repo.google_http import (
    IPv4PreferredHttp,
    IPv4PreferredHTTPSConnection,
)


def test_https_connection_prefers_ipv4(monkeypatch) -> None:
    addresses = [
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 443, 0, 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
    ]
    created_sockets: list[FakeSocket] = []

    monkeypatch.setattr(socket, "getaddrinfo", lambda *args: addresses)
    monkeypatch.setattr(
        socket,
        "socket",
        lambda family, socktype, proto: _fake_socket(
            created_sockets, family, socktype, proto
        ),
    )
    connection = _connection()

    connection.connect()

    assert [sock.family for sock in created_sockets] == [socket.AF_INET]
    assert created_sockets[0].connected_to == ("127.0.0.1", 443)


def test_https_connection_falls_back_after_connect_error(monkeypatch) -> None:
    addresses = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 443, 0, 0)),
    ]
    created_sockets: list[FakeSocket] = []

    monkeypatch.setattr(socket, "getaddrinfo", lambda *args: addresses)
    monkeypatch.setattr(
        socket,
        "socket",
        lambda family, socktype, proto: _fake_socket(
            created_sockets,
            family,
            socktype,
            proto,
            fail=family == socket.AF_INET,
        ),
    )
    connection = _connection()

    connection.connect()

    assert [sock.family for sock in created_sockets] == [
        socket.AF_INET,
        socket.AF_INET6,
    ]
    assert created_sockets[0].closed is True
    assert created_sockets[1].connected_to == ("::1", 443, 0, 0)


def test_http_selects_ipv4_preferred_connection_for_https(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_request(self, uri, **kwargs):
        del self, uri
        captured.update(kwargs)
        return object(), b""

    monkeypatch.setattr(httplib2.Http, "request", fake_request)

    IPv4PreferredHttp().request("https://www.googleapis.com/calendar/v3")

    assert captured["connection_type"] is IPv4PreferredHTTPSConnection


def _connection() -> IPv4PreferredHTTPSConnection:
    connection = object.__new__(IPv4PreferredHTTPSConnection)
    connection.host = "www.googleapis.com"
    connection.port = 443
    connection.proxy_info = None
    connection.timeout = 1
    connection.sock = None
    connection._context = FakeSslContext()
    return connection


def _fake_socket(
    created_sockets: list[FakeSocket],
    family: int,
    socktype: int,
    proto: int,
    *,
    fail: bool = False,
) -> FakeSocket:
    sock = FakeSocket(family, socktype, proto, fail=fail)
    created_sockets.append(sock)
    return sock


class FakeSocket:
    def __init__(self, family: int, socktype: int, proto: int, *, fail: bool = False):
        self.family = family
        self.socktype = socktype
        self.proto = proto
        self.fail = fail
        self.connected_to: tuple | None = None
        self.closed = False

    def setsockopt(self, *args) -> None:
        pass

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def connect(self, address: tuple) -> None:
        if self.fail:
            raise TimeoutError("unreachable")
        self.connected_to = address

    def close(self) -> None:
        self.closed = True


class FakeSslContext:
    def wrap_socket(self, sock: FakeSocket, *, server_hostname: str) -> FakeSocket:
        assert server_hostname == "www.googleapis.com"
        return sock
