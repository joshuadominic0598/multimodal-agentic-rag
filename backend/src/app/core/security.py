"""Public URL validation shared by imports and visual retrieval."""

import ipaddress
import socket
from urllib.parse import urlparse

def validate_url(url):
    u = urlparse(url)
    if (
        u.scheme not in {"http", "https"}
        or not u.hostname
        or u.username
        or u.password
        or u.port not in {None, 80, 443}
    ):
        raise ValueError("Enter a public HTTP(S) webpage URL.")
    addresses = socket.getaddrinfo(
        u.hostname, u.port or (443 if u.scheme == "https" else 80), type=socket.SOCK_STREAM
    )
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Private/internal URLs cannot be imported.")
