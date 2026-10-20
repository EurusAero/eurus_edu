"""Native EurusEdu bytes over TCP or a verified binary WSS connection."""

import re
import select
import socket
import ssl
import threading
import time
from urllib.parse import urlsplit


class SerializedTlsSocket:
    """One TLS object for a listener thread that reads and other threads that send.

    OpenSSL forbids concurrent SSL_read/SSL_write on one connection; under load
    (camera frames + 30 Hz commands) the race made recv report a clean EOF and the
    SDK dropped the link. Reads poll without blocking so senders never wait long.
    """

    POLL_SECONDS = 0.05

    def __init__(self, sock):
        self._sock = sock
        self._lock = threading.Lock()

    def __getattr__(self, name):
        return getattr(self._sock, name)

    def settimeout(self, timeout):
        with self._lock:
            self._sock.settimeout(timeout)

    def recv(self, size):
        timeout = self._sock.gettimeout()
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            try:
                if not self._sock.pending():
                    wait = self.POLL_SECONDS if deadline is None else max(
                        0.0, min(self.POLL_SECONDS, deadline - time.monotonic()))
                    select.select([self._sock], [], [], wait)
                with self._lock:
                    self._sock.settimeout(0)
                    try:
                        return self._sock.recv(size)
                    except (ssl.SSLWantReadError, ssl.SSLWantWriteError, BlockingIOError):
                        pass
                    finally:
                        self._sock.settimeout(timeout)
            except (OSError, ValueError):
                # Closed by another thread (SDK disconnect): report EOF like a blocking recv.
                if self._sock.fileno() == -1:
                    return b""
                raise
            if deadline is not None and time.monotonic() >= deadline:
                raise socket.timeout("timed out")

    def send(self, data):
        with self._lock:
            return self._sock.send(data)


class WssSocket:
    """The sendall/recv/close interface used by both existing SDK listeners."""

    max_message_bytes = 16 * 1024 * 1024

    def __init__(self, connection):
        self.connection = connection
        self.pending = b""
        self.closed = False
        self.close_code = None

    def sendall(self, data):
        import websocket

        if self.closed:
            raise OSError("WSS connection is closed")
        if len(data) > self.max_message_bytes:
            raise OSError("WSS message exceeds SDK limit")
        try:
            self.connection.send_binary(data)
        except websocket.WebSocketTimeoutException as error:
            raise TimeoutError("WSS send timed out") from error
        except websocket.WebSocketException as error:
            raise OSError("WSS send failed") from error

    def recv(self, size):
        import websocket

        if size < 0:
            raise ValueError("Negative receive size")
        if not size or self.closed:
            return b""
        while not self.pending:
            try:
                opcode, data = self.connection.recv_data()
            except websocket.WebSocketTimeoutException as error:
                raise TimeoutError("WSS receive timed out") from error
            except websocket.WebSocketConnectionClosedException:
                self.close()
                return b""
            except websocket.WebSocketException as error:
                self.close()
                raise OSError("WSS receive failed") from error
            if opcode == websocket.ABNF.OPCODE_CLOSE:
                if isinstance(data, (bytes, bytearray)) and len(data) >= 2:
                    self.close_code = int.from_bytes(data[:2], 'big')
                self.close()
                return b""
            if (
                opcode != websocket.ABNF.OPCODE_BINARY
                or len(data) > self.max_message_bytes
            ):
                self.close()
                raise OSError("Expected a binary WSS message within SDK size limit")
            self.pending = data
        chunk, self.pending = self.pending[:size], self.pending[size:]
        return chunk

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.pending = b""
        try:
            # Wake the SDK reader without a second concurrent WebSocket recv.
            self.connection.abort()
        except OSError:
            pass
        finally:
            self.connection.shutdown()


def open_socket(
    ip,
    port,
    timeout,
    *,
    wss_cookie=None,
    wss_headers=None,
    wss_origin=None,
    wss_ca_file=None,
    wss_auth_timeout=120,
):
    """WSS URL controls its own port/path; a plain hostname uses native TCP."""
    if "://" not in ip:
        return socket.create_connection((ip, port), timeout=timeout)
    endpoint = urlsplit(ip)
    if (
        endpoint.scheme != "wss"
        or not endpoint.hostname
        or endpoint.username is not None
        or endpoint.password is not None
        or endpoint.fragment
    ):
        raise ValueError("Expected a WSS URL without userinfo or a fragment")
    # Validate a port before opening a connection; credentials belong in headers.
    tls_port = endpoint.port
    headers = dict(wss_headers or {})
    values = [value for value in (wss_cookie, wss_origin) if value is not None] + list(
        headers.values()
    )
    if any(
        not isinstance(value, str) or "\r" in value or "\n" in value for value in values
    ) or any(
        not isinstance(name, str)
        or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name)
        for name in headers
    ):
        raise ValueError("Invalid WSS header")
    import websocket

    context = ssl.create_default_context(cafile=wss_ca_file)
    authority = (
        f"[{endpoint.hostname}]" if ":" in endpoint.hostname else endpoint.hostname
    )
    if tls_port is not None and tls_port != 443:
        authority += f":{tls_port}"
    origin = wss_origin or "https://" + authority
    session = re.fullmatch(r"/s/([A-Za-z0-9_-]{32})/sdk", endpoint.path)
    automatic = bool(session and not wss_cookie and not headers)
    if session and not endpoint.query:
        channel = {65432: 'control', 8001: 'front', 8002: 'down'}.get(port)
        if not channel:
            raise ValueError("Unknown simulator SDK channel")
        ip += '?channel=' + channel
    if automatic:
        from .browser_auth import cached_cookie
        wss_cookie = cached_cookie("https://" + authority, session[1])
    def connect():
        return websocket.create_connection(
            ip, timeout=timeout, cookie=wss_cookie, header=headers, origin=origin,
            sslopt={"context": context}, enable_multithread=True, redirect_limit=0)
    try:
        connection = connect()
    except websocket.WebSocketBadStatusException as error:
        if automatic and wss_auth_timeout and error.status_code == 403:
            from .browser_auth import approve
            wss_cookie = approve("https://" + authority, session[1], context,
                wss_auth_timeout, invalidate=bool(wss_cookie))
            try:
                connection = connect()
            except websocket.WebSocketException:
                raise ConnectionError("WSS connection failed after browser approval") from None
        else:
            # Never include response headers or credentials in SDK errors.
            raise ConnectionError(f"WSS handshake refused (HTTP {error.status_code})") from None
    except websocket.WebSocketException:
        raise ConnectionError("WSS connection failed") from None
    if connection.getstatus() != 101:
        connection.shutdown()
        raise ConnectionError("WSS handshake did not upgrade; redirects are refused")
    if isinstance(connection.sock, ssl.SSLSocket):
        connection.sock = SerializedTlsSocket(connection.sock)
    return WssSocket(connection)
