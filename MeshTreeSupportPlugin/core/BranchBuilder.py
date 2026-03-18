"""
BranchBuilder – computes branch segment geometry from A contact points
to B cylinder tops.

For each A point:
  1. Short arm perpendicular to the overhang face (along face normal)
  2. Branch from arm tip to nearest point on cylinder rim / wall
     - connects to top RIM if angle requirement is met
     - connects to SIDE WALL (lower) when rim would be too shallow
  3. Branches within branch_merge_dist are merged into a shared trunk

Radius taper: thin (branch_radius) at A, thick (branch_base_radius) at cylinder.

Constraints:
  • min_branch_length    – drop segments shorter than this
  • min_branch_angle_deg – adjust end point downward until angle is satisfied;
                           segments that still fail after adjustment are dropped

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


# ── Cylinder geometry descriptor ───────────────────────────────────── #
@dataclass
class CylinderInfo:
    cx:      float
    cz:      float
    outer_r: float
    height:  float    # top Y of the cylinder

    def rim_point_toward(self, pos: np.ndarray) -> np.ndarray:
        """Nearest point on TOP RIM in the XZ direction toward pos."""
        dx   = float(pos[0]) - self.cx
        dz   = float(pos[2]) - self.cz
        dist = float(np.sqrt(dx * dx + dz * dz))
        if dist < 1e-6:
            return np.array([self.cx + self.outer_r, self.height, self.cz],
                            dtype=np.float32)
        s = self.outer_r / dist
        return np.array([self.cx + dx * s, self.height, self.cz + dz * s],
                        dtype=np.float32)

    def connection_point(self, branch_start: np.ndarray,
                         min_angle_deg: float) -> np.ndarray:
        """
        Preferred connection point: rim.  Falls back to outer-wall point at
        a lower Y if the rim angle would be shallower than min_angle_deg.
        """
        rim = self.rim_point_toward(branch_start)
        d        = rim.astype(np.float64) - branch_start.astype(np.float64)
        dx_horiz = float(np.linalg.norm([d[0], d[2]]))
        dy       = float(d[1])   # negative → going down

        if dx_horiz < 1e-6:
            return rim   # directly above → vertical, always fine

        min_abs_dy = dx_horiz * float(np.tan(np.deg2rad(min_angle_deg)))
        if abs(dy) >= min_abs_dy - 1e-6:
            return rim

        # Rim is too shallow – move connection down the outer wall
        target_y = max(float(branch_start[1]) - min_abs_dy, 0.0)
        dx = float(branch_start[0]) - self.cx
        dz = float(branch_start[2]) - self.cz
        dist = float(np.sqrt(dx * dx + dz * dz))
        if dist < 1e-6:
            return np.array([self.cx + self.outer_r, target_y, self.cz],
                            dtype=np.float32)
        s = self.outer_r / dist
        return np.array([self.cx + dx * s, target_y, self.cz + dz * s],
                        dtype=np.float32)


# ── Visualisation segment (frustum tube) ────────────────────────────── #
@dataclass
class BranchSegment:
    start:        np.ndarray   # (3,)
    end:          np.ndarray   # (3,)
    radius_start: float        # tube radius at start (tip side, thin)
    radius_end:   float        # tube radius at end   (cylinder side, thick)


# ── Main builder ────────────────────────────────────────────────────── #
class BranchBuilder:
    """
    Builds tapered branch segments from ContactPair clusters to B cylinders.
    """

    def __init__(
        self,
        tip_arm_length:       float = 2.0,    # mm – arm from A straight down (-Y)
        branch_merge_dist:    float = 5.0,    # mm – merge branches closer than this
        branch_radius:        float = 0.4,    # mm – radius at A (tip, thin end)
        branch_base_radius:   float = 1.2,    # mm – radius at cylinder connection (thick end)
        min_branch_length:    float = 1.0,    # mm – drop shorter segments
        min_branch_angle_deg: float = 20.0,   # °  – min angle from horizontal
        min_levels:           int   = 4,      # minimum merge iterations (force merge even if far)
        max_levels:           int   = 10,     # maximum merge iterations
        # Legacy params kept for backward compatibility
        trunk_radius:          float = 0.6,
        tip_radius:            float = 0.5,
        branch_diameter_angle: float = 5.0,
        layer_height:          float = 0.2,
        merge_threshold:       float = 2.0,
    ):
        self.tip_arm_length       = tip_arm_length
        self.branch_merge_dist    = branch_merge_dist
        self.branch_radius        = branch_radius
        self.branch_base_radius   = branch_base_radius
        self.min_branch_length    = min_branch_length
        self.min_branch_angle_deg = min_branch_angle_deg
        self.min_levels           = int(min_levels)
        self.max_levels           = int(max_levels)

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def build_segments(
        self,
        pair_clusters:     List[List[ContactPair]],
        cluster_cylinders: List[CylinderInfo],
    ) -> List[BranchSegment]:
        """
        pair_clusters     : one list of ContactPair per B cluster
        cluster_cylinders : matching CylinderInfo for each cluster
        """
        all_segs: List[BranchSegment] = []
        skipped = 0
        for cluster_pairs, cyl in zip(pair_clusters, cluster_cylinders):
            raw = self._build_cluster(cluster_pairs, cyl)
            for seg in raw:
                if self._is_valid(seg):
                    all_segs.append(seg)
                else:
                    skipped += 1
        Logger.log("d",
            "[BranchBuilder] %d valid segments, %d skipped (too short / too shallow)",
            len(all_segs), skipped)
        return all_segs

    # Legacy stub
    def build(self, pairs: List[ContactPair]) -> List[BranchNode]:
        raise NotImplementedError("Use build_segments() for visualisation")

    # ------------------------------------------------------------------ #
    #  Per-cluster building                                                #
    # ------------------------------------------------------------------ #

    def _build_cluster(
        self,
        pairs: List[ContactPair],
        cyl:   CylinderInfo,
    ) -> List[BranchSegment]:
        segments: List[BranchSegment] = []
        arm_ends: List[np.ndarray]    = []

        for p in pairs:
            # Arm goes straight down (-Y) so branch XZ stays aligned with A
            arm_end = np.array(
                [p.A[0], float(p.A[1]) - self.tip_arm_length, p.A[2]],
                dtype=np.float32,
            )
            arm_ends.append(arm_end)

            # Tip arm: A → arm_end, straight down (constant radius, thin)
            segments.append(BranchSegment(
                start=p.A.copy(), end=arm_end,
                radius_start=self.branch_radius,
                radius_end=self.branch_radius,
            ))

        # Top reference Y: highest arm_end in this cluster
        top_y = max(float(ae[1]) for ae in arm_ends) if arm_ends else float(cyl.height)

        segments.extend(self._greedy_merge_tree(arm_ends, cyl, top_y))
        return segments

    # ------------------------------------------------------------------ #
    #  Greedy bottom-up merge tree                                         #
    # ------------------------------------------------------------------ #

    def _greedy_merge_tree(
        self,
        nodes: List[np.ndarray],
        cyl:   CylinderInfo,
        top_y: float,
    ) -> List[BranchSegment]:
        if not nodes:
            return []

        segs   = []
        nodes  = [n.copy().astype(np.float32) for n in nodes]
        dy_ref = max(top_y - cyl.height, 1e-3)   # prevent division by zero

        def _r(y: float) -> float:
            """Taper: thin at top_y, thick at cyl.height."""
            t = float(np.clip((top_y - y) / dy_ref, 0.0, 1.0))
            return self.branch_radius + t * (self.branch_base_radius - self.branch_radius)

        level = 0
        while len(nodes) > 1:
            # Find closest pair
            min_d, mi, mj = float("inf"), 0, 1
            for i in range(len(nodes)):
                for j in range(i + 1, len(nodes)):
                    d = float(np.linalg.norm(nodes[i] - nodes[j]))
                    if d < min_d:
                        min_d, mi, mj = d, i, j

            # Stop if: max levels reached, OR distance too far AND already have min levels
            if level >= self.max_levels:
                break
            if min_d > self.branch_merge_dist and level >= self.min_levels:
                break

            merge_pt = ((nodes[mi] + nodes[mj]) / 2.0).astype(np.float32)
            merge_pt[1] = min(float(nodes[mi][1]), float(nodes[mj][1]))
            merge_pt    = self._enforce_angle(nodes[mi], merge_pt)
            merge_pt    = self._enforce_angle(nodes[mj], merge_pt)
            # Clamp: merge point must not fall below cylinder top
            merge_pt[1] = max(float(merge_pt[1]), cyl.height)

            for n in (nodes[mi], nodes[mj]):
                segs.append(BranchSegment(
                    start=n.copy(), end=merge_pt,
                    radius_start=_r(float(n[1])),
                    radius_end=_r(float(merge_pt[1])),
                ))
            nodes[mi] = merge_pt
            nodes.pop(mj)
            level += 1

        # Remaining nodes → cylinder connection point
        for n in nodes:
            conn = cyl.connection_point(n, self.min_branch_angle_deg)
            segs.append(BranchSegment(
                start=n, end=conn,
                radius_start=_r(float(n[1])),
                radius_end=self.branch_base_radius,
            ))

        return segs

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _enforce_angle(self, start: np.ndarray,
                        end: np.ndarray) -> np.ndarray:
        """Lower end.y until segment meets min_branch_angle_deg from horizontal."""
        d        = end.astype(np.float64) - start.astype(np.float64)
        dx_horiz = float(np.linalg.norm([d[0], d[2]]))
        if dx_horiz < 1e-6:
            return end
        min_abs_dy = dx_horiz * float(np.tan(np.deg2rad(self.min_branch_angle_deg)))
        if abs(float(d[1])) >= min_abs_dy - 1e-6:
            return end
        new_end    = end.copy().astype(np.float32)
        new_end[1] = float(start[1]) - min_abs_dy
        return new_end

    def _is_valid(self, seg: BranchSegment) -> bool:
        d      = seg.end.astype(np.float64) - seg.start.astype(np.float64)
        length = float(np.linalg.norm(d))
        if length < self.min_branch_length:
            return False
        abs_dy = abs(float(d[1]))
        angle  = float(np.degrees(np.arcsin(min(abs_dy / length, 1.0))))
        return angle >= self.min_branch_angle_deg
