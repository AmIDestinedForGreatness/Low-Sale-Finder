"""Conservative boundaries for URLs that do not come from trusted code.

This blocks the demonstrated arbitrary-host and redirect-to-private-network
paths. DNS is validated before each request/navigation, but ordinary client
libraries resolve again while connecting; this is therefore defense in depth,
not a claim of DNS-rebinding-proof transport pinning.
"""
from dataclasses import dataclass
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import requests


MARKETPLACE_ROOTS = (
    "carousell.com", "carousell.ph", "carousell.sg", "carousell.my",
    "carousell.hk", "carousell.tw", "carousell.com.au",
    "carousell.co.nz", "carousell.ca", "facebook.com", "fb.com",
    "fb.watch",
)
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class UnsafeUrl(ValueError):
    """The URL is unsupported or could target a non-public network."""


class ResponseTooLarge(UnsafeUrl):
    """A bounded remote fetch exceeded its byte budget."""


@dataclass(frozen=True)
class FetchedBytes:
    status_code: int
    content: bytes
    url: str
    headers: dict


def _host_matches(host, roots):
    return any(host == root or host.endswith("." + root) for root in roots)


def _public_addresses(host, port, resolver=None):
    resolver = resolver or socket.getaddrinfo
    try:
        answers = resolver(host, port, type=socket.SOCK_STREAM)
    except (OSError, socket.gaierror) as exc:
        raise UnsafeUrl("hostname could not be resolved") from exc
    addresses = {str(answer[4][0]).split("%", 1)[0] for answer in answers
                 if answer and len(answer) >= 5 and answer[4]}
    if not addresses:
        raise UnsafeUrl("hostname had no usable addresses")
    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as exc:
            raise UnsafeUrl("hostname returned an invalid address") from exc
        if not parsed.is_global:
            raise UnsafeUrl("hostname resolves outside the public internet")
    return addresses


def validate_public_url(url, *, allowed_roots=None, resolver=None):
    """Validate one HTTPS URL and return its stripped form.

    All DNS answers must be globally routable. Rejecting a host with mixed
    public/private answers is deliberate: the caller cannot control which
    address a downstream client will choose.
    """
    value = str(url or "").strip()
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeUrl("malformed URL") from exc
    if parsed.scheme.lower() != "https":
        raise UnsafeUrl("HTTPS is required")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeUrl("URL credentials are not allowed")
    host = str(parsed.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeUrl("URL hostname is required")
    if port not in (None, 443):
        raise UnsafeUrl("non-standard URL ports are not allowed")
    if allowed_roots and not _host_matches(host, allowed_roots):
        raise UnsafeUrl("URL hostname is not allowlisted")
    _public_addresses(host, 443, resolver=resolver)
    return value


def validate_marketplace_url(url, *, resolver=None):
    return validate_public_url(
        url, allowed_roots=MARKETPLACE_ROOTS, resolver=resolver)


def guard_marketplace_navigation(route, main_frame):
    """Abort a disallowed top-level Playwright navigation before it is sent."""
    req = route.request
    if req.is_navigation_request() and req.frame == main_frame:
        try:
            validate_marketplace_url(req.url)
        except UnsafeUrl:
            route.abort("blockedbyclient")
            return
    route.continue_()


def fetch_public_bytes(url, *, headers=None, timeout=30, max_bytes=12_000_000,
                       max_redirects=4, allowed_roots=None, resolver=None,
                       requester=None):
    """Fetch bounded bytes while validating every redirect destination."""
    requester = requester or requests.get
    current = validate_public_url(
        url, allowed_roots=allowed_roots, resolver=resolver)
    for redirect_number in range(max_redirects + 1):
        response = requester(current, headers=headers or {}, timeout=timeout,
                             allow_redirects=False, stream=True)
        try:
            status = int(response.status_code)
            if status in _REDIRECT_STATUSES:
                location = str((response.headers or {}).get("Location") or "")
                if not location:
                    raise UnsafeUrl("redirect response had no Location")
                if redirect_number >= max_redirects:
                    raise UnsafeUrl("too many redirects")
                current = validate_public_url(
                    urljoin(current, location), allowed_roots=allowed_roots,
                    resolver=resolver)
                continue
            content_length = str((response.headers or {}).get("Content-Length") or "")
            if content_length.isdigit() and int(content_length) > max_bytes:
                raise ResponseTooLarge("remote response exceeds byte budget")
            response_headers = {str(key).lower(): value
                                for key, value in (response.headers or {}).items()}
            if status < 200 or status >= 300:
                return FetchedBytes(status, b"", current, response_headers)
            chunks, total = [], 0
            iterator = (response.iter_content(chunk_size=64 * 1024)
                        if hasattr(response, "iter_content")
                        else (getattr(response, "content", b""),))
            for chunk in iterator:
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise ResponseTooLarge("remote response exceeds byte budget")
                chunks.append(chunk)
            return FetchedBytes(status, b"".join(chunks), current,
                                response_headers)
        finally:
            close = getattr(response, "close", None)
            if close:
                close()
    raise UnsafeUrl("too many redirects")
