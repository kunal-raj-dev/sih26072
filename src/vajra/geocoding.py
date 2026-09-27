"""High-speed spatial geocoding and administrative join engine for Project Vajra.

Maps atmospheric storm cells and forecast hazard footprints to official Indian
administrative boundaries (State -> District -> Block) with population exposure.

Uses Shapely 2.x STRtree (spatial R-Tree) for sub-millisecond point-in-polygon
and polygon-intersection joins.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from shapely.geometry import Point, Polygon, box, shape
from shapely.strtree import STRtree

from .logsetup import get_logger
from .schemas import Cell

logger = get_logger("vajra.geocoding")


@dataclass(frozen=True)
class AdminEntity:
    """An administrative region (District or Sub-district / Block)."""

    id: str
    name: str
    district: str
    state: str
    full_name: str
    population: int
    area_sqkm: float
    bbox: tuple[float, float, float, float]  # minlon, minlat, maxlon, maxlat
    geometry: Any = field(repr=False)


@dataclass
class AdminIntersection:
    """Intersection result between a storm cell and an administrative unit."""

    entity: AdminEntity
    overlap_area_sqkm: float
    overlap_fraction: float  # fraction of the block area covered by cell
    exposed_population: int  # estimated affected population


class SpatialIndex:
    """In-memory spatial R-Tree index for Indian administrative boundaries."""

    def __init__(
        self,
        districts_path: Path | str | None = None,
        blocks_path: Path | str | None = None,
    ) -> None:
        self.districts: list[AdminEntity] = []
        self.blocks: list[AdminEntity] = []
        self._district_tree: STRtree | None = None
        self._block_tree: STRtree | None = None
        self._district_fc: dict[str, Any] = {"type": "FeatureCollection", "features": []}
        self._block_fc: dict[str, Any] = {"type": "FeatureCollection", "features": []}

        # Resolve paths
        base_dir = Path(__file__).resolve().parents[2] / "data" / "admin"
        d_path = Path(districts_path) if districts_path else base_dir / "india_districts.geojson"
        b_path = Path(blocks_path) if blocks_path else base_dir / "india_blocks.geojson"

        if d_path.exists() and b_path.exists():
            self._load(d_path, b_path)
        else:
            logger.warning(
                "administrative boundaries not found at %s and %s; spatial joins will fallback",
                d_path, b_path,
            )

    def _load(self, districts_path: Path, blocks_path: Path) -> None:
        # 1. Load Districts
        try:
            d_data = json.loads(districts_path.read_text(encoding="utf-8"))
            self._district_fc = d_data
            d_geoms = []
            for feat in d_data.get("features", []):
                props = feat.get("properties", {})
                geom = shape(feat["geometry"])
                bbox = tuple(props.get("bbox", geom.bounds))
                entity = AdminEntity(
                    id=str(feat.get("id", props.get("district", "").lower())),
                    name=props.get("district", "Unknown"),
                    district=props.get("district", "Unknown"),
                    state=props.get("state", "Unknown"),
                    full_name=props.get("fullName", f"{props.get('district')} District"),
                    population=int(props.get("population", 0)),
                    area_sqkm=float(props.get("area_sqkm", 0.0)),
                    bbox=bbox,  # type: ignore[arg-type]
                    geometry=geom,
                )
                self.districts.append(entity)
                d_geoms.append(geom)

            if d_geoms:
                self._district_tree = STRtree(d_geoms)
        except Exception as exc:  # noqa: BLE001
            logger.error("failed loading districts geojson: %s", exc)

        # 2. Load Blocks
        try:
            b_data = json.loads(blocks_path.read_text(encoding="utf-8"))
            self._block_fc = b_data
            b_geoms = []
            for feat in b_data.get("features", []):
                props = feat.get("properties", {})
                geom = shape(feat["geometry"])
                bbox = tuple(props.get("bbox", geom.bounds))
                entity = AdminEntity(
                    id=str(feat.get("id", props.get("block", "").lower())),
                    name=props.get("block", "Unknown"),
                    district=props.get("district", "Unknown"),
                    state=props.get("state", "Unknown"),
                    full_name=props.get("fullName", f"{props.get('block')} Block"),
                    population=int(props.get("population", 0)),
                    area_sqkm=float(props.get("area_sqkm", 0.0)),
                    bbox=bbox,  # type: ignore[arg-type]
                    geometry=geom,
                )
                self.blocks.append(entity)
                b_geoms.append(geom)

            if b_geoms:
                self._block_tree = STRtree(b_geoms)
        except Exception as exc:  # noqa: BLE001
            logger.error("failed loading blocks geojson: %s", exc)

        logger.info(
            "loaded spatial index: %d districts, %d blocks",
            len(self.districts), len(self.blocks),
        )

    def is_ready(self) -> bool:
        return self._block_tree is not None and len(self.blocks) > 0

    def query_point(self, lat: float, lon: float) -> list[AdminEntity]:
        """Find all administrative blocks containing the given (lat, lon) point."""
        if not self._block_tree:
            return []
        pt = Point(lon, lat)
        # R-Tree query for candidate geometries
        candidate_indices = self._block_tree.query(pt)
        matches: list[AdminEntity] = []
        for idx in candidate_indices:
            block = self.blocks[idx]
            if block.geometry.contains(pt) or block.geometry.intersects(pt):
                matches.append(block)
        return matches

    def query_district_for_point(self, lat: float, lon: float) -> AdminEntity | None:
        """Find the district containing the given point."""
        if not self._district_tree:
            return None
        pt = Point(lon, lat)
        candidate_indices = self._district_tree.query(pt)
        for idx in candidate_indices:
            dist = self.districts[idx]
            if dist.geometry.contains(pt) or dist.geometry.intersects(pt):
                return dist
        return None

    def intersect_cell(
        self,
        cell: Cell,
        min_overlap_fraction: float = 0.10,
    ) -> list[AdminIntersection]:
        """Find administrative blocks intersecting a storm cell footprint.

        Considers both:
        1. Overlap area fraction >= min_overlap_fraction (default 10%).
        2. Centroid point containment (even if small footprint).
        """
        if not self._block_tree or not cell.bbox or len(cell.bbox) < 4:
            return []

        min_lon, min_lat, max_lon, max_lat = cell.bbox
        cell_geom = box(min_lon, min_lat, max_lon, max_lat)
        centroid = Point(cell.centroid_lon, cell.centroid_lat)

        candidate_indices = self._block_tree.query(cell_geom)
        intersections: list[AdminIntersection] = []

        for idx in candidate_indices:
            block = self.blocks[idx]
            if not cell_geom.intersects(block.geometry):
                continue

            try:
                inter = cell_geom.intersection(block.geometry)
                if inter.is_empty:
                    continue
                block_area = block.geometry.area
                inter_area = inter.area
                frac = float(inter_area / block_area) if block_area > 0 else 0.0
                sqkm = float(inter_area * 111.32 * 111.32)

                is_contained = block.geometry.contains(centroid)
                if frac >= min_overlap_fraction or is_contained:
                    # Estimate exposed population based on fraction of block area covered
                    exposure_ratio = min(1.0, max(0.15 if is_contained else 0.05, frac))
                    pop_exposed = int(round(block.population * exposure_ratio))
                    intersections.append(
                        AdminIntersection(
                            entity=block,
                            overlap_area_sqkm=round(sqkm, 2),
                            overlap_fraction=round(frac, 3),
                            exposed_population=pop_exposed,
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                logger.debug("geometry intersection error for block %s: %s", block.name, exc)
                continue

        # Sort by overlap fraction descending
        intersections.sort(key=lambda x: x.overlap_fraction, reverse=True)
        return intersections

    def format_region_name(
        self,
        intersections: list[AdminIntersection] | list[AdminEntity],
        fallback: str = "",
    ) -> str:
        """Format matching administrative units into a concise, human-readable hierarchy."""
        if not intersections:
            return fallback

        # Extract entities
        entities = [
            x.entity if isinstance(x, AdminIntersection) else x
            for x in intersections
        ]

        # Single primary match
        top = entities[0]
        block_label = top.name if top.name.endswith("Block") else f"{top.name} Block"
        if len(entities) == 1:
            return f"{top.state} / {top.district} / {block_label}"

        # Multiple blocks in same district
        same_dist = [e for e in entities if e.district == top.district]
        if len(same_dist) == len(entities):
            block_names = ", ".join(e.name for e in entities[:3])
            suffix = f" (+{len(entities) - 3} more)" if len(entities) > 3 else ""
            return f"{top.state} / {top.district} ({block_names}{suffix})"

        # Cross-district alert
        dists = sorted({e.district for e in entities[:3]})
        return f"{top.state} / {' & '.join(dists)} Districts"

    def get_district_geojson(self) -> dict[str, Any]:
        """Return GeoJSON FeatureCollection of districts."""
        return self._district_fc

    def get_blocks_geojson(self, district: str | None = None) -> dict[str, Any]:
        """Return GeoJSON FeatureCollection of blocks, optionally filtered by district."""
        if not district:
            return self._block_fc
        features = [
            f for f in self._block_fc.get("features", [])
            if f.get("properties", {}).get("district", "").lower() == district.lower()
        ]
        return {"type": "FeatureCollection", "features": features}
