"""Location enrichment mapping.

Main entry points:
- get_locations_map(): load YAML-backed mapping (fallback to built-in)
- enrich_location(name): return standardized display string when known

The YAML is optional and loaded lazily; functions are dependency-light.
"""

from pathlib import Path
from typing import Dict, Optional

# Built-in fallback map (kept for compatibility); prefer YAML at config/locations.yaml
ADDRESS_MAP = {
    # Richmond Hill Arenas / Pools
    'Bond Lake Arena': 'Bond Lake Arena (70 Old Colony Rd, Richmond Hill, ON)',
    'Ed Sackfield Arena': 'Ed Sackfield Arena (311 Valleymede Dr, Richmond Hill, ON)',
    'Elgin Barrow Arena': 'Elgin Barrow Arena (43 Church St S, Richmond Hill, ON)',
    'Tom Graham Arena': 'Tom Graham Arena (1300 Elgin Mills Rd E, Richmond Hill, ON)',
    'Bayview Hill Pool': 'Bayview Hill Community Centre (114 Spadina Rd, Richmond Hill, ON)',
    'Elgin West Pool': 'Elgin West Community Centre (11099 Bathurst St, Richmond Hill, ON)',
    'Oak Ridges Pool': 'Oak Ridges Community Centre (12895 Bayview Ave, Richmond Hill, ON)',
    'Richvale Pool': 'Richvale Community Centre (160 Avenue Rd, Richmond Hill, ON)',
    'The Wave Pool': 'Wave Pool (5 Hopkins St, Richmond Hill, ON)',
    # Aurora Pools
    'S.A.R.C.': 'Stronach Aurora Recreation Complex (1400 Wellington St E, Aurora, ON)',
    'S.A.R.C. Pool': 'Stronach Aurora Recreation Complex (1400 Wellington St E, Aurora, ON)',
    'A.F.L.C.': 'Aurora Family Leisure Complex (135 Industrial Pkwy N, Aurora, ON)',
    'A.F.L.C. Pool': 'Aurora Family Leisure Complex (135 Industrial Pkwy N, Aurora, ON)',
}

_CACHED_MAP: Optional[Dict[str, str]] = None


def _default_locations_yaml_paths() -> list[Path]:
    # Check CWD config first, then repo-root-relative to this package
    paths = []
    paths.append(Path.cwd() / 'config' / 'locations.yaml')
    try:
        repo_root = Path(__file__).resolve().parents[1]
        paths.append(repo_root / 'config' / 'locations.yaml')
    except Exception:
        pass  # nosec B110 - fallback to other paths
    return paths


def get_locations_map() -> Dict[str, str]:
    """Return a mapping of short names to standardized location strings.

    Attempts to read `config/locations.yaml` from CWD or repo root; falls
    back to the built-in ADDRESS_MAP. Result is memoized per process.
    """
    global _CACHED_MAP
    if _CACHED_MAP is not None:
        return _CACHED_MAP
    # Try to load YAML lazily; fallback to ADDRESS_MAP
    for p in _default_locations_yaml_paths():
        if p.exists():
            try:
                from calendar_assistant.yamlio import load_config  # lazy import
                data = load_config(str(p))
                # Expect a flat mapping: { 'Name': 'Name (addr, city, ...)' }
                if isinstance(data, dict):
                    # If loaded as {locations: {...}}, unwrap; otherwise require flat str->str map
                    locs = data.get('locations') if 'locations' in data else data
                    if isinstance(locs, dict) and all(isinstance(k, (str, int)) and isinstance(v, str) for k, v in locs.items()):
                        _CACHED_MAP = {str(k): str(v) for k, v in locs.items()}
                        return _CACHED_MAP
            except Exception:
                pass  # nosec B110 - continue to fallback
    _CACHED_MAP = dict(ADDRESS_MAP)
    return _CACHED_MAP


def enrich_location(name: str) -> str:
    """Return the standardized location string for a given short name.

    If the name is unknown, returns the original input unchanged.
    """
    n = (name or '').strip()
    if not n:
        return n
    mapping = get_locations_map()
    return mapping.get(n, n)
