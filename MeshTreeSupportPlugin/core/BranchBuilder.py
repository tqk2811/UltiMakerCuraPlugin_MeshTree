"""
BranchBuilder – constructs the tree branch data structure from (A, B) contact pairs.
Stub: ready for implementation.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from .ContactPointFinder import ContactPair


@dataclass
class BranchNode:
    position: np.ndarray          # (3,) world space
    radius:   float
    children: List["BranchNode"] = field(default_factory=list)
    parent:   Optional["BranchNode"] = field(default=None, repr=False)
    is_tip:   bool = False         # True at contact point A
    is_base:  bool = False         # True at anchor point B


class BranchBuilder:
    """
    Builds a tree of BranchNodes from a list of ContactPairs.

    Pipeline:
      1. build_single_branch() for each pair → straight chain tip→base
      2. merge_branches()      → merge nearby nodes into shared trunks
    """

    def __init__(
        self,
        tip_radius:            float = 0.5,
        branch_radius:         float = 1.5,
        branch_diameter_angle: float = 5.0,
        layer_height:          float = 0.2,
        merge_threshold:       float = 2.0,
    ):
        self.tip_radius            = tip_radius
        self.branch_radius         = branch_radius
        self.branch_diameter_angle = branch_diameter_angle
        self.layer_height          = layer_height
        self.merge_threshold       = merge_threshold

    def build(self, pairs: List[ContactPair]) -> List[BranchNode]:
        """
        Returns a list of root BranchNodes (bases).
        Raises NotImplementedError until implemented.
        """
        raise NotImplementedError("BranchBuilder.build() not yet implemented")

    def build_single_branch(self, pair: ContactPair) -> List[BranchNode]:
        """Straight chain from A down to B with linearly growing radius."""
        raise NotImplementedError

    def merge_branches(self, roots: List[BranchNode]) -> List[BranchNode]:
        """Merge nodes at the same layer that are within merge_threshold of each other."""
        raise NotImplementedError

    @staticmethod
    def _merged_radius(r1: float, r2: float) -> float:
        """Conserve cross-sectional area: r = sqrt(r1^2 + r2^2)."""
        return float(np.sqrt(r1 ** 2 + r2 ** 2))
