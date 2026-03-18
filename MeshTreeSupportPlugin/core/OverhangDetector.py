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

        # ── Compute per-face normals & edge lengths ───────────────────── #
        v0 = verts[indices[:, 0]]
        v1 = verts[indices[:, 1]]
        v2 = verts[indices[:, 2]]

        cross   = np.cross(v1 - v0, v2 - v0)          # (M, 3)
        lengths = np.linalg.norm(cross, axis=1)        # (M,) – 2× face area
        valid   = lengths > 1e-10
        normals = np.zeros_like(cross)
        normals[valid] = cross[valid] / lengths[valid, np.newaxis]

        # Max edge length per face (vectorised) ─────────────────────── #
        e01 = np.linalg.norm(v1 - v0, axis=1)
        e12 = np.linalg.norm(v2 - v1, axis=1)
        e20 = np.linalg.norm(v0 - v2, axis=1)
        max_edge = np.maximum(np.maximum(e01, e12), e20)

        # Max allowed edge = 10 % of model diagonal, min 5 mm, max 30 mm #
        diag = float(np.linalg.norm(
            np.percentile(verts, 99, axis=0) - np.percentile(verts, 1, axis=0)
        ))
        max_edge_limit = float(np.clip(diag * 0.10, 5.0, 30.0))

        # ── Overhang angle filter ─────────────────────────────────────── #
        threshold = -np.sin(np.deg2rad(self.support_angle_deg))
        mask = (normals[:, 1] < threshold) & valid & (max_edge <= max_edge_limit)

        # ── Collect results ───────────────────────────────────────────── #
        MIN_AREA = 0.01   # mm²
        results: List[OverhangFace] = []
        skipped = 0
        for i in np.where(mask)[0]:
            area = 0.5 * lengths[i]
            if area < MIN_AREA:
                skipped += 1
                continue
            results.append(OverhangFace(
                center=((v0[i] + v1[i] + v2[i]) / 3.0).astype(np.float32),
                normal=normals[i].astype(np.float32),
                area=float(area),
            ))

        Logger.log("d",
            "[OverhangDetector] kept=%d skipped=%d  max_edge_limit=%.1f mm  angle=%.1f°",
            len(results), skipped + int((~mask & valid).sum()),
            max_edge_limit, self.support_angle_deg)

        return results
