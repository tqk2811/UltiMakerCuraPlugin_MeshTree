"""
BranchBuilder – computes branch segment geometry from A contact points
to B cylinder tops.

For each A point:
  1. A short arm perpendicular to the overhang face (along face normal direction)
  2. A branch line from the arm tip toward the top of the nearest B cylinder
  3. Branches within branch_merge_dist are merged into a shared trunk

Cura coordinate: Y is UP.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from UM.Logger import Logger
from .ContactPointFinder import ContactPair


# ── Legacy dataclass kept for future TreeMeshGenerator use ─────────── #
@dataclass
class BranchNode:
    position: np.ndarray
    radius:   float
    children: List["BranchNode"] = field(default_factory=list)
    parent:   Optional["BranchNode"] = field(default=None, repr=False)
    is_tip:   bool = False
    is_base:  bool = False

    @staticmethod
    def _merged_radius(r1: float, r2: float) -> float:
        return float(np.sqrt(r1 ** 2 + r2 ** 2))


# ── Visualisation segment ───────────────────────────────────────────── #
@dataclass
class BranchSegment:
    start:  np.ndarray   # (3,) start position
    end:    np.ndarray   # (3,) end position
    radius: float        # tube radius in mm


class BranchBuilder:
    """
    Builds visualisation segments (arm + branch lines + merged trunk)
    from ContactPair clusters and their matching B cylinder tops.
    """

    def __init__(
        self,
        tip_arm_length:    float = 2.0,   # mm – arm from A along face normal
        branch_merge_dist: float = 5.0,   # mm – merge branches closer than this
        branch_radius:     float = 0.4,   # mm – individual branch tube radius
        trunk_radius:      float = 0.6,   # mm – merged trunk radius
        # Legacy params (kept so old callers don't break)
        tip_radius:            float = 0.5,
        branch_diameter_angle: float = 5.0,
        layer_height:          float = 0.2,
        merge_threshold:       float = 2.0,
    ):
        self.tip_arm_length    = tip_arm_length
        self.branch_merge_dist = branch_merge_dist
        self.branch_radius     = branch_radius
        self.trunk_radius      = trunk_radius

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def build_segments(
        self,
        pair_clusters: List[List[ContactPair]],
        cluster_tops:  List[np.ndarray],      # (3,) top-center of each B cylinder
    ) -> List[BranchSegment]:
        """
        pair_clusters : list of clusters; each cluster is a list of ContactPair
        cluster_tops  : matching list – cylinder top position for each cluster
        Returns all branch segments (arm + branch lines + trunk).
        """
        all_segs: List[BranchSegment] = []
        for cluster_pairs, cyl_top in zip(pair_clusters, cluster_tops):
            all_segs.extend(self._build_cluster(cluster_pairs, cyl_top))
        Logger.log("d", "[BranchBuilder] %d segments from %d clusters",
                   len(all_segs), len(pair_clusters))
        return all_segs

    # Legacy stub – kept so getModuleStatus() import check passes
    def build(self, pairs: List[ContactPair]) -> List[BranchNode]:
        raise NotImplementedError("Use build_segments() for visualisation")

    # ------------------------------------------------------------------ #
    #  Per-cluster building                                                #
    # ------------------------------------------------------------------ #

    def _build_cluster(
        self,
        pairs:   List[ContactPair],
        cyl_top: np.ndarray,
    ) -> List[BranchSegment]:
        segments: List[BranchSegment] = []

        arm_ends: List[np.ndarray] = []
        for p in pairs:
            n = p.normal if p.normal is not None else np.array([0.0, -1.0, 0.0], dtype=np.float32)
            n_len = float(np.linalg.norm(n))
            if n_len > 1e-6:
                n = n / n_len

            arm_end = (p.A + n * self.tip_arm_length).astype(np.float32)
            arm_ends.append(arm_end)

            # Tip arm: A → arm_end (perpendicular to overhang surface)
            segments.append(BranchSegment(
                start=p.A.copy(), end=arm_end, radius=self.branch_radius
            ))

        # Build tree from arm_ends → cyl_top using greedy merging
        segments.extend(self._greedy_merge_tree(arm_ends, cyl_top))
        return segments

    # ------------------------------------------------------------------ #
    #  Greedy bottom-up merge tree                                         #
    # ------------------------------------------------------------------ #

    def _greedy_merge_tree(
        self,
        nodes:  List[np.ndarray],
        target: np.ndarray,
    ) -> List[BranchSegment]:
        """
        Repeatedly merge the two closest nodes (if within branch_merge_dist)
        into a midpoint merge node (at the lower Y of the two), then connect
        all remaining nodes to the cylinder top.
        """
        if not nodes:
            return []

        segs: List[BranchSegment] = []
        nodes = [n.copy().astype(np.float32) for n in nodes]
        radius = self.branch_radius

        changed = True
        while changed and len(nodes) > 1:
            changed = False
            min_d, mi, mj = float("inf"), 0, 1
            for i in range(len(nodes)):
                for j in range(i + 1, len(nodes)):
                    d = float(np.linalg.norm(nodes[i] - nodes[j]))
                    if d < min_d:
                        min_d, mi, mj = d, i, j

            if min_d <= self.branch_merge_dist:
                # Merge: XZ midpoint, Y = lower of the two
                merge_pt = ((nodes[mi] + nodes[mj]) / 2.0).astype(np.float32)
                merge_pt[1] = min(float(nodes[mi][1]), float(nodes[mj][1]))

                segs.append(BranchSegment(start=nodes[mi].copy(), end=merge_pt, radius=radius))
                segs.append(BranchSegment(start=nodes[mj].copy(), end=merge_pt, radius=radius))

                nodes[mi] = merge_pt
                nodes.pop(mj)
                radius = self.trunk_radius
                changed = True

        # Remaining nodes → cylinder top
        for n in nodes:
            segs.append(BranchSegment(start=n, end=target.copy(), radius=self.trunk_radius))

        return segs
