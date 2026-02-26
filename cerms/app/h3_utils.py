import h3
from typing import List, Set
from app.config import H3_RESOLUTION


def lat_lng_to_h3(lat: float, lng: float, resolution: int = H3_RESOLUTION) -> str:
    return h3.geo_to_h3(lat, lng, resolution)


def h3_to_center(h3_index: str) -> tuple[float, float]:
    return h3.h3_to_geo(h3_index)


def get_k_ring(h3_index: str, k: int = 1) -> Set[str]:
    return h3.k_ring(h3_index, k)


def get_h3_neighbors(h3_index: str, k: int = 1) -> List[str]:
    ring = h3.k_ring(h3_index, k)
    ring.discard(h3_index)
    return list(ring)


def h3_resolution_info(resolution: int = H3_RESOLUTION) -> dict:
    avg_area_km2 = {
        0: 4_250_546.85,
        1: 607_220.98,
        2: 86_745.85,
        3: 12_392.26,
        4: 1_770.32,
        5: 252.90,
        6: 36.13,
        7: 5.16,
        8: 0.74,
        9: 0.105,
        10: 0.015,
    }
    return {
        "resolution": resolution,
        "avg_hex_area_km2": avg_area_km2.get(resolution, "unknown"),
        "description": f"H3 resolution {resolution} → ~{avg_area_km2.get(resolution, '?')} km² per hex",
    }


def is_valid_h3(h3_index: str) -> bool:
    return h3.h3_is_valid(h3_index)
