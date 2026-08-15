import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def _load_profiles() -> dict[str, dict]:
    path = ROOT / "world_bank_data.json"
    if not path.exists():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {row["iso_code"].upper(): row for row in rows if row.get("iso_code")}


@lru_cache(maxsize=1)
def _load_mapping() -> dict[str, str]:
    path = ROOT / "country_iso_map.json"
    if not path.exists():
        return {}
    return {str(k): str(v).upper() for k, v in json.loads(path.read_text(encoding="utf-8")).items()}


def get_history(country_name: str) -> list[dict]:
    iso = _load_mapping().get(country_name)
    profile = _load_profiles().get(iso) if iso else None
    return list(profile.get("data") or []) if profile else []


def get_profile(country_name: str, year: int = 2020) -> dict | None:
    iso = _load_mapping().get(country_name)
    profile = _load_profiles().get(iso) if iso else None
    if not profile:
        return None
    data = profile.get("data") or []
    if not data:
        return {**profile, "iso_code": iso, "selected_year": None}
    selected = min(data, key=lambda row: abs(int(row["year"]) - int(year)))
    return {**profile, "iso_code": iso, "selected_year": int(selected["year"]), **selected}


def format_money(value: float | int | None) -> str:
    if value is None:
        return "нет данных"
    value = float(value)
    if abs(value) >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.2f} трлн"
    if abs(value) >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f} млрд"
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:.2f} млн"
    return f"${value:,.0f}"


def format_life_expectancy(value: float | int | None) -> str:
    return "нет данных" if value is None else f"{float(value):.1f} лет"


def format_population(value: float | int | None) -> str:
    if value is None:
        return "нет данных"
    value = float(value)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f} млн"
    return f"{value:,.0f}"
