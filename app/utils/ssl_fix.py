"""
SSL Certificate fix for Windows Python environments.
Python on Windows often cannot verify SSL certificates from certain CAs.
This patches httpx to use verify=False as a fallback.
"""
import ssl
import certifi


def get_ssl_context() -> ssl.SSLContext:
    """
    Returns an SSL context that works on Windows.
    Uses certifi's CA bundle as the trust store.
    """
    ctx = ssl.create_default_context(cafile=certifi.where())
    return ctx


# Patch httpx globally to use certifi
HTTPX_DEFAULT_KWARGS = {
    "verify": certifi.where(),
    "timeout": 30,
}
