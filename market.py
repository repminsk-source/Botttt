"""Deterministic dynamic prices for the resource market."""
import hashlib
import time
import config


def _multiplier(resource: str, tick: int) -> float:
    seed = f"{resource}:{tick}".encode()
    digest = hashlib.sha256(seed).digest()
    unit = int.from_bytes(digest[:8], "big") / float(2**64 - 1)
    variance = config.MARKET_PRICE_VARIANCE
    return 1.0 - variance + 2.0 * variance * unit


def get_price(resource: str) -> int:
    resource = resource.lower()
    if resource not in config.RESOURCE_BUY_PRICE_GOLD:
        raise KeyError(resource)
    tick = int(time.time()) // config.MARKET_TICK_SECONDS
    base = config.RESOURCE_BUY_PRICE_GOLD[resource]
    return max(1, round(base * _multiplier(resource, tick)))


def get_all_prices() -> dict[str, int]:
    return {resource: get_price(resource) for resource in config.RESOURCE_BUY_PRICE_GOLD}


def seconds_until_next_tick() -> int:
    tick_seconds = max(1, config.MARKET_TICK_SECONDS)
    return tick_seconds - (int(time.time()) % tick_seconds)


RESOURCE_LABELS = {
    "wood": "дерево",
    "iron": "железо",
    "coal": "уголь",
    "oil": "нефть",
    "uranium": "уран",
}


def format_prices() -> str:
    return "\n".join(
        f"{RESOURCE_LABELS.get(resource, resource)}: {price} золота/шт."
        for resource, price in get_all_prices().items()
    )
