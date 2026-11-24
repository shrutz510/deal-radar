"""The single HTTP helper every reader uses: honest User-Agent, timeout, raises on HTTP errors."""
import urllib.request

from config import USER_AGENT


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()
