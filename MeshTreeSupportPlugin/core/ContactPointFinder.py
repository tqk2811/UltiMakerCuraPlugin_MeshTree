"""
ContactPointFinder – derives (A, B) pairs from overhang faces.

A = contact point on overhang surface (slightly offset outward along normal)
B = anchor point on build plate (Y=0), constrained by branch_angle

Cura coordinate: Y is UP, build plate Y=0.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List

import numpy as np

from UM.Logger import Logger
from .OverhangDetector import OverhangFace


@dataclass
class ContactPair:
    A: np.ndarray   # (3,) world-space contact point  (on overhang)
    B: np.ndarray   # (3,) world-space anchor  point  (on build plate, Y≈0)


class ContactPointFinder:

    def __init__(
        self,
        branch_angle_deg: float = 40.0,
        merge_threshold:  float = 2.0,
        max_points:       int   = 300,
        tip_offset:       float = 0.1,   # mm – push A slightly off surface
    ):
        self.branch_angle_deg = branch_angle_deg
        self.merge_threshold  = merge_threshold
        self.max_points       = max_points
        self.tip_offset       = tip_offset

    def find(self, overhang_faces: List[OverhangFace]) -> List[ContactPair]:
        if not overhang_faces:
            return []

        # ── Build raw A points (centroid + offset along normal) ─────── #
        centers = np.array([f.center for f in overhang_faces], dtype=np.float32)
        normals = np.array([f.normal for f in overhang_faces], dtype=np.float32)

        A_points = centers + normals * self.tip_offset

        # ── Grid-based clustering to reduce marker count ─────────────── #
        A_clustered = self._cluster(A_points, self.merge_threshold)

        if len(A_clustered) > self.max_points:
            # Sub-sample evenly
            idx = np.round(np.linspace(0, len(A_clustered) - 1, self.max_points)).astype(int)
            A_clustered = A_clustered[idx]

        Logger.log("d", "[ContactPointFinder] %d → %d contact points after clustering",
                   len(A_points), len(A_clustered))

        # ── Compute B points ─────────────────────────────────────────── #
        pairs: List[ContactPair] = []
        tan_branch = np.tan(np.deg2rad(self.branch_angle_deg))

        for A in A_clustered:
            h = float(A[1])          # height above build plate
            if h <= 0:
                h = 0.01
            # B is directly below A; the straight vertical satisfies any branch angle
            B = np.array([A[0], 0.0, A[2]], dtype=np.float32)
            pairs.append(ContactPair(A=A.astype(np.float32), B=B))

        return pairs

    # ------------------------------------------------------------------ #
    @staticmethod
    def _cluster(points: np.ndarray, cell_size: float) -> np.ndarray:
        """Keep one representative point per grid cell (first encountered)."""
        if len(points) == 0:
            return points
        cells: dict = {}
        for p in points:
            key = (int(p[0] / cell_size), int(p[1] / cell_size), int(p[2] / cell_size))
            if key not in cells:
                cells[key] = p
        return np.array(list(cells.values()), dtype=np.float32)
