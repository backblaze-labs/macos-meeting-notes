"""Google HTTP transport with reliable dual-stack connection fallback."""

from __future__ import annotations

import socket
import ssl

import httplib2
from google_auth_httplib2 import AuthorizedHttp

DEFAULT_GOOGLE_HTTP_TIMEOUT_SECONDS = 15


class IPv4PreferredHTTPSConnection(httplib2.HTTPSConnectionWithTimeout):
    """Try IPv4 before IPv6 and continue after a per-address timeout."""

    def connect(self) -> None:
        if self.proxy_info and self.proxy_info.isgood() and self.proxy_info.applies_to(
            self.host
        ):
            super().connect()
            return

        addresses = socket.getaddrinfo(self.host, self.port, 0, socket.SOCK_STREAM)
        socket_error: OSError | None = None
        for family, socktype, proto, _canonname, sockaddr in _ipv4_first(addresses):
            sock = socket.socket(family, socktype, proto)
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                if self.timeout is not None:
                    sock.settimeout(self.timeout)
                sock.connect(sockaddr)
                self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
                return
            except (ssl.SSLError, ssl.CertificateError):
                sock.close()
                self.sock = None
                raise
            except OSError as exc:
                socket_error = exc
                sock.close()
                self.sock = None

        if socket_error is not None:
            raise socket_error
        raise OSError(f"No network addresses found for {self.host}")


class IPv4PreferredHttp(httplib2.Http):
    """Route HTTPS requests through the dual-stack-safe connection class."""

    def request(
        self,
        uri,
        method="GET",
        body=None,
        headers=None,
        redirections=httplib2.DEFAULT_MAX_REDIRECTS,
        connection_type=None,
        **kwargs,
    ):
        if connection_type is None and str(uri).lower().startswith("https://"):
            connection_type = IPv4PreferredHTTPSConnection
        return super().request(
            uri,
            method=method,
            body=body,
            headers=headers,
            redirections=redirections,
            connection_type=connection_type,
            **kwargs,
        )


def authorized_google_http(credentials) -> AuthorizedHttp:
    """Return an authorized Google transport with a bounded socket timeout."""
    return AuthorizedHttp(
        credentials,
        http=IPv4PreferredHttp(timeout=DEFAULT_GOOGLE_HTTP_TIMEOUT_SECONDS),
    )


def _ipv4_first(addresses: list[tuple]) -> list[tuple]:
    return sorted(addresses, key=lambda address: address[0] != socket.AF_INET)
