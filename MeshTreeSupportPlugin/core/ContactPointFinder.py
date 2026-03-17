"""
ContactPointFinder – derives contact points A (on overhang) and anchor points B (on build plate / non-overhang surface).
Stub: ready for implementation.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple

import numpy as np

from .OverhangDetector import OverhangFace


@dataclass
class ContactPair:
    A: np.ndarray   # (3,) contact point on overhang surface
    B: np.ndarray   # (3,) anchor point (build plate or support surface)


class ContactPointFinder:
    """
    For each OverhangFace, computes a (A, B) ContactPair.

    A = centroid of overhang face (offset slightly along normal)
    B = projection of A onto build plate (z=0) constrained by branch_angle
    """

    def __init__(self, branch_angle_deg: float = 40.0, cluster_radius: float = 2.0):
        self.branch_angle_deg = branch_angle_deg
        self.cluster_radius   = cluster_radius

    def find(self, overhang_faces: List[OverhangFace], mesh_node=None) -> List[ContactPair]:
        """
        Returns ContactPair list.
        Raises NotImplementedError until implemented.
        """
        raise NotImplementedError("ContactPointFinder.find() not yet implemented")

    @staticmethod
    def _project_to_buildplate(A: np.ndarray, branch_angle_deg: float) -> np.ndarray:
        """
        Simple strategy: B = (Ax, Ay, 0).
        Satisfies angle constraint when Az * tan(branch_angle) >= horizontal offset = 0.
        """
        return np.array([A[0], A[1], 0.0])

    @staticmethod
    def _cluster_points(points: List[np.ndarray], radius: float) -> List[np.ndarray]:
        """Merge points closer than `radius` into their centroid."""
        raise NotImplementedError
