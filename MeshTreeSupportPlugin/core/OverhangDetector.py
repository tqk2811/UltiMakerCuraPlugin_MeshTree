"""
OverhangDetector – identifies overhang faces on a mesh node.
Cura coordinate system: Y is UP, build plate is Y=0.
Overhang = face whose normal points downward enough: normal.y < -sin(support_angle_rad)

World-space transform uses the same algorithm as Cura's official
UM.Mesh.MeshData.transformVertices() to avoid coordinate errors:
  data = vertices padded with w=0
  data = data @ M.T          (rotation/scale only)
  data += M[:, 3]            (add translation column)
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List

import numpy as np

from UM.Logger import Logger


@dataclass
class OverhangFace:
    center: np.ndarray   # (3,) world-space centroid [x, y, z]
    normal: np.ndarray   # (3,) unit outward normal
    area:   float


class OverhangDetector:

    def __init__(self, support_angle_deg: float = 50.0):
        self.support_angle_deg = support_angle_deg

    def detect(self, scene_node) -> List[OverhangFace]:
        mesh_data = scene_node.getMeshData()
        if mesh_data is None:
            Logger.log("w", "[OverhangDetector] Node has no mesh data.")
            return []

        verts_raw = mesh_data.getVertices()   # (N, 3) float32 – local space
        indices   = mesh_data.getIndices()    # (M, 3) int32 or None

        if verts_raw is None or len(verts_raw) == 0:
            return []

        if indices is None:
            n = len(verts_raw)
            indices = np.arange(n, dtype=np.int32).reshape(-1, 3)

        # ── Transform to world space (matches Cura's transformVertices) ── #
        #   data = verts padded w=0 then @ M.T, then += M[:,3]
        tf     = scene_node.getWorldTransformation()
        M      = tf.getData().astype(np.float64)          # (4,4) float64
        data   = np.pad(verts_raw.astype(np.float64), ((0,0),(0,1)), constant_values=0.0)
        data   = data.dot(M.T)                            # rotation + scale
        data  += M[:, 3]                                  # add translation
        verts  = data[:, :3]                              # (N, 3)

        # ── Clamp bad indices ─────────────────────────────────────────── #
        n_verts  = len(verts)
        valid_i  = np.all((indices >= 0) & (indices < n_verts), axis=1)
        indices  = indices[valid_i]
        if len(indices) == 0:
            return []

        # ── Compute per-face normals ──────────────────────────────────── #
        v0 = verts[indices[:, 0]]
        v1 = verts[indices[:, 1]]
        v2 = verts[indices[:, 2]]

        cross   = np.cross(v1 - v0, v2 - v0)          # (M, 3)
        lengths = np.linalg.norm(cross, axis=1)        # (M,)
        valid   = lengths > 1e-10
        normals = np.zeros_like(cross)
        normals[valid] = cross[valid] / lengths[valid, np.newaxis]

        # ── Robust bounding box: 1st–99th percentile of vertices + 5 mm  #
        # Using percentiles ignores stray/artifact vertices that would    #
        # otherwise extend min/max and let bad centroids slip through.    #
        bb_min = np.percentile(verts, 1,  axis=0) - 5.0
        bb_max = np.percentile(verts, 99, axis=0) + 5.0

        # ── Filter: normal.y < -sin(support_angle) ───────────────────── #
        threshold = -np.sin(np.deg2rad(self.support_angle_deg))
        mask = (normals[:, 1] < threshold) & valid

        # ── Vectorised: all 3 vertices must be inside robust bbox ─────── #
        # Checking vertices (not centroid) catches faces whose centroid    #
        # appears valid but one vertex is a garbage point far from model.  #
        v0_ok = np.all((v0 >= bb_min) & (v0 <= bb_max), axis=1)
        v1_ok = np.all((v1 >= bb_min) & (v1 <= bb_max), axis=1)
        v2_ok = np.all((v2 >= bb_min) & (v2 <= bb_max), axis=1)
        bbox_ok = v0_ok & v1_ok & v2_ok

        MIN_AREA = 0.01   # mm² – skip degenerate faces
        area_ok  = (0.5 * lengths) >= MIN_AREA

        final_mask = mask & bbox_ok & area_ok

        results: List[OverhangFace] = []
        skipped = int((mask & ~(bbox_ok & area_ok)).sum())
        for i in np.where(final_mask)[0]:
            center = (v0[i] + v1[i] + v2[i]) / 3.0
            results.append(OverhangFace(
                center=center.astype(np.float32),
                normal=normals[i].astype(np.float32),
                area=float(0.5 * lengths[i]),
            ))

        Logger.log("d", "[OverhangDetector] %d overhang faces kept, %d skipped (bbox/area) – angle=%.1f°",
                   len(results), skipped, self.support_angle_deg)

        return results
