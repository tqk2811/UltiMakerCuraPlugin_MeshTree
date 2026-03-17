"""
OverhangDetector – identifies overhang faces on a mesh.
Stub: ready for implementation.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List

import numpy as np


@dataclass
class OverhangFace:
    vertices: np.ndarray   # (3, 3) float – world-space triangle vertices
    center:   np.ndarray   # (3,)   float – centroid
    normal:   np.ndarray   # (3,)   float – outward face normal (unit)
    area:     float


class OverhangDetector:
    """
    Given a SceneNode, returns all faces whose downward-facing angle
    exceeds `support_angle` (degrees from horizontal).
    """

    def __init__(self, support_angle_deg: float = 50.0):
        self.support_angle_deg = support_angle_deg

    def detect(self, scene_node) -> List[OverhangFace]:
        """
        Returns a list of OverhangFace for the given CuraSceneNode.
        Raises NotImplementedError until implemented.
        """
        raise NotImplementedError("OverhangDetector.detect() not yet implemented")

    # ------------------------------------------------------------------ #
    #  Internal helpers (to be implemented)                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _get_world_vertices(node) -> np.ndarray:
        """Transform mesh vertices to world space."""
        raise NotImplementedError

    @staticmethod
    def _compute_face_normals(verts: np.ndarray, indices: np.ndarray) -> np.ndarray:
        """Return per-face unit normals, shape (N, 3)."""
        v0 = verts[indices[:, 0]]
        v1 = verts[indices[:, 1]]
        v2 = verts[indices[:, 2]]
        n = np.cross(v1 - v0, v2 - v0)
        length = np.linalg.norm(n, axis=1, keepdims=True)
        length = np.where(length == 0, 1.0, length)
        return n / length
