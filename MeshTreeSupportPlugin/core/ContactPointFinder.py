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
    def exclude_near_footprint(
        pairs:            "List[ContactPair]",
        mesh_nodes:       list,
        exclusion_radius: float = 30.0,
    ) -> "List[ContactPair]":
        """
        Remove pairs whose B point (XZ) lies within `exclusion_radius` mm
        of any vertex that is on (or near) the build plate of a mesh node.

        "On the build plate" = vertex Y ≤ min_Y_of_node + 0.5 mm after
        world transform.  Only the XZ plane is considered for distance.
        """
        if not pairs or not mesh_nodes:
            return pairs

        # ── Collect footprint vertices (world XZ) across all nodes ─── #
        foot_xz_list = []
        for node in mesh_nodes:
            mesh_data = node.getMeshData()
            if mesh_data is None:
                continue
            verts_raw = mesh_data.getVertices()
            if verts_raw is None or len(verts_raw) == 0:
                continue

            matrix = node.getWorldTransformation().getData()
            ones   = np.ones((len(verts_raw), 1), dtype=np.float64)
            verts  = (matrix @ np.hstack([verts_raw.astype(np.float64), ones]).T).T[:, :3]

            min_y  = float(verts[:, 1].min())
            ground = verts[verts[:, 1] <= min_y + 0.5]   # Y within 0.5 mm of bottom
            if len(ground) > 0:
                foot_xz_list.append(ground[:, [0, 2]])    # keep only X, Z

        if not foot_xz_list:
            return pairs

        foot_xz = np.vstack(foot_xz_list).astype(np.float32)   # (N, 2)
        r2 = exclusion_radius ** 2

        kept = []
        excluded = 0
        for pair in pairs:
            bx, bz  = float(pair.B[0]), float(pair.B[2])
            dx      = foot_xz[:, 0] - bx
            dz      = foot_xz[:, 1] - bz
            min_d2  = float(np.min(dx * dx + dz * dz))
            if min_d2 < r2:
                excluded += 1
            else:
                kept.append(pair)

        Logger.log("d", "[ContactPointFinder] footprint exclusion (r=%.1f mm): "
                   "%d kept, %d excluded", exclusion_radius, len(kept), excluded)
        return kept

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
