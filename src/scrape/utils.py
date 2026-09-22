"""HTTP helper — mirrors fa_scraper/src/scraping/utils.py.

Kept self-contained so over15 doesn't depend on fa_scraper's package layout.
"""
from __future__ import annotations

import time

import requests
from requests.exceptions import (
    ConnectionError,
    HTTPError,
    InvalidURL,
    RequestException,
    Timeout,
    TooManyRedirects,
)


UA = "Mozilla/5.0 (X11; Linux x86_64; rv:122.0) Gecko/20100101 Firefox/122.0"


def safe_request(url: str, max_retries: int = 3, retry_delay: float = 2,
                 timeout: int = 15):
    """Fetch a URL with retries. None on unrecoverable errors.

    Handles two failure modes distinctly:
        - Transient network (Timeout/ConnectionError): retry with short delay.
        - Rate-limit / server overload (429, 503): back off *long* (60s) before
          retrying, up to max_retries. If we ignore these, we get soft-banned.
    """
    headers = {"User-Agent": UA}
    retryable = (Timeout, ConnectionError)
    rate_limit_backoff = 60

    for attempt in range(max_retries + 1):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.status_code in (429, 503):
                if attempt < max_retries:
                    print(f"  Rate-limited (HTTP {r.status_code}) — backing off "
                          f"{rate_limit_backoff}s (attempt {attempt + 1}/{max_retries + 1})")
                    time.sleep(rate_limit_backoff)
                    continue
                print(f"  Max retries on rate-limit for {url}")
                return None
            r.raise_for_status()
            return r
        except HTTPError as e:
            print(f"  HTTP error: {e}")
            return None
        except (InvalidURL, TooManyRedirects) as e:
            print(f"  URL/redirect error: {e}")
            return None
        except RequestException as e:
            if isinstance(e, retryable):
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue
                print(f"  Max retries reached: {e}")
                return None
            print(f"  Request failed: {e}")
            return None
    return None
