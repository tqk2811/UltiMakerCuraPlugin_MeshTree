"""
TreeMeshGenerator – converts a BranchNode tree into a solid 3-D mesh.
Stub: ready for implementation.
"""
from __future__ import annotations
from typing import List, Tuple

import numpy as np

from .BranchBuilder import BranchNode


class TreeMeshGenerator:
    """
    Generates a printable support mesh from the BranchNode tree.

    Each branch segment becomes a frustum (truncated cone).
    Tips get a hemisphere cap; bases get a flat disc.
    All frustums are concatenated into one vertex/index array.
    """

    def __init__(self, sides: int = 8):
        self.sides = sides   # polygon sides per cross-section circle

    def generate(self, roots: List[BranchNode]) -> Tuple[np.ndarray, np.ndarray]:
        """
        Returns (vertices, indices) as numpy arrays suitable for MeshBuilder.
          vertices : (N, 3) float32
          indices  : (M, 3) int32
        Raises NotImplementedError until implemented.
        """
        raise NotImplementedError("TreeMeshGenerator.generate() not yet implemented")

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    def _frustum(
        self,
        center_bottom: np.ndarray, r_bottom: float,
        center_top:    np.ndarray, r_top:    float,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Return vertices and indices for one frustum segment."""
        raise NotImplementedError

    @staticmethod
    def _circle_vertices(center: np.ndarray, radius: float, sides: int) -> np.ndarray:
        """Return (sides, 3) array of vertices evenly spaced on a horizontal circle."""
        angles = np.linspace(0, 2 * np.pi, sides, endpoint=False)
        verts  = np.stack([
            center[0] + radius * np.cos(angles),
            center[1] + radius * np.sin(angles),
            np.full(sides, center[2]),
        ], axis=1)
        return verts.astype(np.float32)
