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
    A:      np.ndarray              # (3,) world-space contact point  (on overhang)
    B:      np.ndarray              # (3,) world-space anchor  point  (on build plate, Y≈0)
    normal: np.ndarray = None       # (3,) outward face normal at A (unit vector, points downward for overhangs)


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

        # ── Remove outliers (points > 3σ from median) ────────────────── #
        A_points, normals = self._remove_outliers(A_points, aux=normals)

        # ── Grid-based clustering to reduce marker count ─────────────── #
        A_clustered, normals_clustered = self._cluster_with_normals(
            A_points, normals, self.merge_threshold
        )

        if len(A_clustered) > self.max_points:
            idx = np.round(np.linspace(0, len(A_clustered) - 1, self.max_points)).astype(int)
            A_clustered        = A_clustered[idx]
            normals_clustered  = normals_clustered[idx]

        Logger.log("d", "[ContactPointFinder] %d → %d contact points after clustering",
                   len(A_points), len(A_clustered))

        # ── Compute B points ─────────────────────────────────────────── #
        pairs: List[ContactPair] = []
        for A, n in zip(A_clustered, normals_clustered):
            h = float(A[1])
            if h <= 0:
                h = 0.01
            B = np.array([A[0], 0.0, A[2]], dtype=np.float32)
            pairs.append(ContactPair(A=A.astype(np.float32), B=B,
                                     normal=n.astype(np.float32)))

        return pairs

    # ------------------------------------------------------------------ #
    @staticmethod
    def _remove_outliers(points: np.ndarray, sigma: float = 3.0,
                         aux: np.ndarray = None):
        """Drop points whose distance from the median exceeds sigma × MAD.
        If aux is provided (same length), it is filtered in sync and returned as second value."""
        if len(points) < 4:
            return (points, aux) if aux is not None else points
        median = np.median(points, axis=0)
        dists  = np.linalg.norm(points - median, axis=1)
        mad    = float(np.median(dists))
        if mad < 1e-6:
            return (points, aux) if aux is not None else points
        keep = dists <= sigma * mad * 1.4826
        n_removed = int((~keep).sum())
        if n_removed:
            Logger.log("d", "[ContactPointFinder] Removed %d outlier A-points (sigma=%.1f)", n_removed, sigma)
        if aux is not None:
            return points[keep], aux[keep]
        return points[keep]

    @staticmethod
    def _cluster_with_normals(points: np.ndarray, normals: np.ndarray,
                               cell_size: float):
        """Grid-based clustering that keeps both the representative point and its normal."""
        if len(points) == 0:
            return (np.zeros((0, 3), dtype=np.float32),
                    np.zeros((0, 3), dtype=np.float32))
        cells: dict = {}
        for p, n in zip(points, normals):
            key = (int(p[0] / cell_size), int(p[1] / cell_size), int(p[2] / cell_size))
            if key not in cells:
                cells[key] = (p.copy(), n.copy())
        pts  = np.array([v[0] for v in cells.values()], dtype=np.float32)
        nrms = np.array([v[1] for v in cells.values()], dtype=np.float32)
        return pts, nrms

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

