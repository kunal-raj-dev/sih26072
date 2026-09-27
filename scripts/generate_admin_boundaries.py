"""Generate canonical administrative boundaries GeoJSON files for Project Vajra.

Generates:
  - data/admin/india_districts.geojson
  - data/admin/india_blocks.geojson

Applies Douglas-Peucker simplification (epsilon=0.005) to optimize geometry size
while preserving topological validity and boundary containment.
"""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
from shapely.geometry import Polygon, MultiPolygon, mapping
from shapely.ops import unary_union


def create_regular_poly(center_lon: float, center_lat: float, radius_deg: float, n_vertices: int = 12, jitter: float = 0.15, seed: int = 42) -> Polygon:
    """Generate a convex-like pseudo-realistic polygon around a centroid."""
    rng = np.random.default_rng(seed)
    angles = np.linspace(0, 2 * np.pi, n_vertices, endpoint=False)
    angles += rng.uniform(-0.08, 0.08, n_vertices)
    angles.sort()
    radii = radius_deg * (1.0 + rng.uniform(-jitter, jitter, n_vertices))
    
    # Coordinates in (lon, lat)
    lons = center_lon + radii * np.cos(angles)
    lats = center_lat + radii * np.sin(angles)
    coords = list(zip(lons, lats))
    coords.append(coords[0])  # Close ring
    poly = Polygon(coords)
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly


# Define hierarchical administrative units: State -> District -> list of Blocks
# Each block has (name, center_lon, center_lat, radius_deg, population, seed)
ADMIN_HIERARCHY = {
    "Bihar": {
        "Patna": {
            "headquarters": "Patna",
            "population": 5838465,
            "blocks": [
                ("Patna Sadar", 85.15, 25.61, 0.07, 450000, 101),
                ("Danapur", 85.04, 25.63, 0.08, 380000, 102),
                ("Phulwari Sharif", 85.08, 25.57, 0.07, 320000, 103),
                ("Bihta", 84.87, 25.56, 0.09, 290000, 104),
                ("Bakhtiarpur", 85.52, 25.45, 0.08, 240000, 105),
                ("Barh", 85.71, 25.48, 0.09, 280000, 106),
                ("Masaurhi", 85.02, 25.35, 0.09, 260000, 107),
                ("Fatuha", 85.31, 25.51, 0.08, 210000, 108),
                ("Maner", 84.88, 25.65, 0.08, 220000, 109),
            ],
        },
        "Gaya": {
            "headquarters": "Gaya",
            "population": 4391418,
            "blocks": [
                ("Gaya Town", 85.00, 24.80, 0.08, 470000, 201),
                ("Bodhgaya", 84.98, 24.70, 0.09, 390000, 202),
                ("Sherghati", 84.79, 24.57, 0.10, 270000, 203),
                ("Tekari", 84.83, 24.93, 0.09, 280000, 204),
                ("Wazirganj", 85.23, 24.78, 0.09, 250000, 205),
                ("Manpur", 85.04, 24.79, 0.07, 260000, 206),
            ],
        },
        "Muzaffarpur": {
            "headquarters": "Muzaffarpur",
            "population": 4801062,
            "blocks": [
                ("Mushahari", 85.42, 26.12, 0.08, 480000, 301),
                ("Kanti", 85.30, 26.20, 0.09, 360000, 302),
                ("Motipur", 85.18, 26.28, 0.10, 320000, 303),
                ("Sakra", 85.53, 25.98, 0.09, 290000, 304),
                ("Kurhani", 85.44, 26.01, 0.09, 340000, 305),
                ("Marwan", 85.32, 26.13, 0.08, 230000, 306),
            ],
        },
        "Vaishali": {
            "headquarters": "Hajipur",
            "population": 3495058,
            "blocks": [
                ("Hajipur", 85.22, 25.68, 0.08, 440000, 401),
                ("Lalganj", 85.18, 25.86, 0.09, 310000, 402),
                ("Mahua", 85.39, 25.83, 0.09, 330000, 403),
                ("Bidupur", 85.33, 25.65, 0.08, 280000, 404),
                ("Bhagwanpur", 85.29, 25.84, 0.08, 260000, 405),
            ],
        },
        "Bhojpur": {
            "headquarters": "Arrah",
            "population": 2728407,
            "blocks": [
                ("Arrah Sadar", 84.66, 25.56, 0.09, 420000, 501),
                ("Koilwar", 84.80, 25.58, 0.08, 250000, 502),
                ("Jagdishpur", 84.42, 25.48, 0.10, 290000, 503),
                ("Bihiya", 84.46, 25.58, 0.09, 230000, 504),
                ("Sandesh", 84.70, 25.38, 0.09, 210000, 505),
            ],
        },
        "Nalanda": {
            "headquarters": "Bihar Sharif",
            "population": 2874523,
            "blocks": [
                ("Bihar Sharif", 85.52, 25.20, 0.09, 460000, 601),
                ("Rajgir", 85.42, 25.03, 0.09, 260000, 602),
                ("Hilsa", 85.28, 25.32, 0.08, 280000, 603),
                ("Islampur", 85.21, 25.14, 0.09, 250000, 604),
                ("Harnaut", 85.53, 25.37, 0.08, 230000, 605),
            ],
        },
        "Samastipur": {
            "headquarters": "Samastipur",
            "population": 4261566,
            "blocks": [
                ("Samastipur Sadar", 85.78, 25.86, 0.09, 450000, 701),
                ("Dalsinghsarai", 85.83, 25.67, 0.08, 290000, 702),
                ("Rosera", 86.01, 25.75, 0.09, 310000, 703),
                ("Pusa", 85.67, 25.98, 0.08, 240000, 704),
            ],
        },
        "Begusarai": {
            "headquarters": "Begusarai",
            "population": 2970541,
            "blocks": [
                ("Begusarai Sadar", 86.13, 25.42, 0.09, 430000, 801),
                ("Barauni", 85.97, 25.47, 0.09, 350000, 802),
                ("Teghra", 85.91, 25.49, 0.08, 270000, 803),
                ("Bakhri", 86.22, 25.56, 0.09, 240000, 804),
            ],
        },
        "Bhagalpur": {
            "headquarters": "Bhagalpur",
            "population": 3037766,
            "blocks": [
                ("Nathnagar", 86.94, 25.23, 0.08, 380000, 901),
                ("Jagdishpur Bhagalpur", 86.98, 25.18, 0.08, 320000, 902),
                ("Kahalgaon", 87.23, 25.26, 0.10, 340000, 903),
                ("Sultanganj", 86.74, 25.24, 0.09, 280000, 904),
            ],
        },
        "Darbhanga": {
            "headquarters": "Darbhanga",
            "population": 3937385,
            "blocks": [
                ("Darbhanga Sadar", 85.90, 26.15, 0.09, 480000, 1001),
                ("Benipur", 86.13, 26.14, 0.09, 320000, 1002),
                ("Keoti", 85.95, 26.27, 0.09, 290000, 1003),
            ],
        },
        "Saran": {
            "headquarters": "Chhapra",
            "population": 3951862,
            "blocks": [
                ("Chhapra Sadar", 84.75, 25.78, 0.09, 440000, 1101),
                ("Sonpur", 85.18, 25.70, 0.08, 280000, 1102),
                ("Marhaura", 84.87, 25.97, 0.09, 310000, 1103),
            ],
        },
        "Rohtas": {
            "headquarters": "Sasaram",
            "population": 2959918,
            "blocks": [
                ("Sasaram", 84.03, 24.95, 0.10, 420000, 1201),
                ("Dehri", 84.18, 24.91, 0.09, 350000, 1202),
                ("Bikramganj", 84.26, 25.20, 0.09, 270000, 1203),
            ],
        },
    },
    "Uttar Pradesh": {
        "Varanasi": {
            "headquarters": "Varanasi",
            "population": 3676841,
            "blocks": [
                ("Varanasi Sadar", 82.97, 25.32, 0.09, 520000, 1301),
                ("Pindra", 82.85, 25.48, 0.09, 340000, 1302),
            ],
        },
        "Gorakhpur": {
            "headquarters": "Gorakhpur",
            "population": 4440895,
            "blocks": [
                ("Gorakhpur Sadar", 83.37, 26.76, 0.10, 560000, 1401),
                ("Sahjanwa", 83.21, 26.77, 0.09, 310000, 1402),
            ],
        },
        "Ballia": {
            "headquarters": "Ballia",
            "population": 3239774,
            "blocks": [
                ("Ballia Sadar", 84.15, 25.76, 0.09, 410000, 1501),
                ("Rasra", 83.85, 25.85, 0.09, 320000, 1502),
            ],
        },
    },
    "West Bengal": {
        "Kolkata": {
            "headquarters": "Kolkata",
            "population": 4496694,
            "blocks": [
                ("Kolkata Core", 88.36, 22.57, 0.09, 850000, 1601),
                ("Alipore", 88.33, 22.53, 0.08, 620000, 1602),
            ],
        },
        "Howrah": {
            "headquarters": "Howrah",
            "population": 4850029,
            "blocks": [
                ("Howrah Sadar", 88.31, 22.59, 0.08, 680000, 1701),
                ("Bally", 88.34, 22.65, 0.07, 410000, 1702),
            ],
        },
    },
    "Odisha": {
        "Khordha": {
            "headquarters": "Bhubaneswar",
            "population": 2251673,
            "blocks": [
                ("Bhubaneswar Municipal", 85.82, 20.29, 0.09, 650000, 1801),
                ("Jatni", 85.70, 20.17, 0.08, 290000, 1802),
            ],
        },
        "Cuttack": {
            "headquarters": "Cuttack",
            "population": 2624470,
            "blocks": [
                ("Cuttack Sadar", 85.88, 20.46, 0.09, 580000, 1901),
                ("Salepur", 85.99, 20.48, 0.08, 260000, 1902),
            ],
        },
    },
}


def build_boundaries():
    admin_dir = Path("data/admin")
    admin_dir.mkdir(parents=True, exist_ok=True)
    
    district_features = []
    block_features = []
    
    for state_name, districts in ADMIN_HIERARCHY.items():
        for dist_name, dist_info in districts.items():
            dist_polys = []
            dist_pop = dist_info["population"]
            
            for (block_name, lon, lat, radius, pop, seed) in dist_info["blocks"]:
                poly = create_regular_poly(lon, lat, radius, n_vertices=14, seed=seed)
                # Douglas-Peucker simplification with epsilon=0.005
                simplified_poly = poly.simplify(0.005, preserve_topology=True)
                dist_polys.append(simplified_poly)
                
                minx, miny, maxx, maxy = simplified_poly.bounds
                area_sqkm = float(simplified_poly.area * 111.32 * 111.32)
                
                block_feature = {
                    "type": "Feature",
                    "id": f"{dist_name.lower()}_{block_name.lower().replace(' ', '_')}",
                    "properties": {
                        "state": state_name,
                        "district": dist_name,
                        "block": block_name,
                        "fullName": f"{state_name} / {dist_name} / {block_name} Block",
                        "population": pop,
                        "area_sqkm": round(area_sqkm, 1),
                        "centroid": [round(lon, 4), round(lat, 4)],
                        "bbox": [round(minx, 4), round(miny, 4), round(maxx, 4), round(maxy, 4)],
                    },
                    "geometry": mapping(simplified_poly),
                }
                block_features.append(block_feature)
            
            # Combine block polygons to form district polygon
            merged_dist = unary_union(dist_polys)
            simplified_dist = merged_dist.simplify(0.005, preserve_topology=True)
            minx, miny, maxx, maxy = simplified_dist.bounds
            dist_area = float(simplified_dist.area * 111.32 * 111.32)
            
            dist_feature = {
                "type": "Feature",
                "id": dist_name.lower(),
                "properties": {
                    "state": state_name,
                    "district": dist_name,
                    "headquarters": dist_info["headquarters"],
                    "fullName": f"{state_name} / {dist_name} District",
                    "population": dist_pop,
                    "blockCount": len(dist_info["blocks"]),
                    "area_sqkm": round(dist_area, 1),
                    "bbox": [round(minx, 4), round(miny, 4), round(maxx, 4), round(maxy, 4)],
                },
                "geometry": mapping(simplified_dist),
            }
            district_features.append(dist_feature)

    dist_fc = {"type": "FeatureCollection", "features": district_features}
    block_fc = {"type": "FeatureCollection", "features": block_features}
    
    dist_path = admin_dir / "india_districts.geojson"
    block_path = admin_dir / "india_blocks.geojson"
    
    dist_path.write_text(json.dumps(dist_fc, indent=1), encoding="utf-8")
    block_path.write_text(json.dumps(block_fc, indent=1), encoding="utf-8")
    
    print(f"Generated {len(district_features)} districts in {dist_path} ({dist_path.stat().st_size / 1024:.1f} KB)")
    print(f"Generated {len(block_features)} blocks in {block_path} ({block_path.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    build_boundaries()
