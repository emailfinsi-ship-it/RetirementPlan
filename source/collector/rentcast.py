"""RentCast property value estimates (https://developers.rentcast.io).

One GET per property to the AVM endpoint, authenticated with the account's
API key in the X-Api-Key header; the answer's `price` is RentCast's
estimated market value. Each call counts against the plan's monthly
request allowance, so the app only calls it when a person presses a
Refresh button -- never automatically.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

AVM_URL = "https://api.rentcast.io/v1/avm/value"


class RentCastError(Exception):
    """A readable failure (bad key, address not found, rate limit, ...)."""


def fetch_value_estimate(address: str, api_key: str, *, urlopen=urllib.request.urlopen, timeout: float = 20.0) -> dict:
    """{"price": float, "low": float | None, "high": float | None} for an
    address. `urlopen` is injectable so tests never touch the network."""
    address = (address or "").strip()
    if not address:
        raise RentCastError("This property has no address yet. Enter one first.")
    request = urllib.request.Request(
        f"{AVM_URL}?{urllib.parse.urlencode({'address': address})}",
        headers={"X-Api-Key": api_key, "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        reasons = {
            401: "RentCast rejected the API key.",
            404: "RentCast couldn't find a value for that address. Check the address spelling.",
            429: "RentCast's request limit was reached. Try again later.",
        }
        raise RentCastError(reasons.get(exc.code, f"RentCast returned an error (HTTP {exc.code}).")) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RentCastError("Couldn't reach RentCast. Check the internet connection.") from exc
    except ValueError as exc:
        raise RentCastError("RentCast sent a response this program couldn't read.") from exc
    price = payload.get("price") if isinstance(payload, dict) else None
    if not isinstance(price, (int, float)) or price <= 0:
        raise RentCastError("RentCast returned no value estimate for that address.")
    low, high = payload.get("priceRangeLow"), payload.get("priceRangeHigh")
    return {
        "price": float(price),
        "low": float(low) if isinstance(low, (int, float)) else None,
        "high": float(high) if isinstance(high, (int, float)) else None,
    }
