"""
MarkerInjector – creates marker meshes in the Cura scene to visualise
contact points A (on overhang) and anchor points B (build plate).

A markers : small solid cylinder,  r=0.5 mm,  h = 3 × layer_height
B markers : hollow cylinder,        h = 10 × layer_height
  • Isolated B point  → small hollow cylinder, outer_r = 1.5 mm
  • Cluster of B pts  → hollow cylinder sized to enclose the cluster,
                        outer_r = max(dist_from_centroid) + wall + 1 mm
  Wall thickness is fixed at WALL_MM (default 1.2 mm).

Cura coordinate: Y is UP.  Build plate is at Y = 0.
"""
from __future__ import annotations
from typing import List, Tuple

import numpy as np

from UM.Logger import Logger
from UM.Mesh.MeshBuilder import MeshBuilder
from UM.Operations.GroupedOperation import GroupedOperation
from UM.Operations.AddSceneNodeOperation import AddSceneNodeOperation
from UM.Operations.RemoveSceneNodeOperation import RemoveSceneNodeOperation

from UM.Scene.SceneNode import SceneNode

from cura.CuraApplication import CuraApplication
from cura.Scene.CuraSceneNode import CuraSceneNode
from cura.Scene.SliceableObjectDecorator import SliceableObjectDecorator
from cura.Scene.BuildPlateDecorator import BuildPlateDecorator

from ..core.ContactPointFinder import ContactPair
from ..core.BranchBuilder import BranchBuilder, BranchSegment, CylinderInfo

NAME_A       = "MeshTree_MarkerA"
NAME_B       = "MeshTree_MarkerB"
NAME_B_DOT   = "MeshTree_MarkerBDot"    # flat disc per B point, visual only
NAME_BRANCH  = "MeshTree_MarkerBranch"  # branch lines from A to cylinder tops

class MarkerInjector:

    def __init__(
        self,
        layer_height:      float = 0.2,
        sides:             int   = 12,
        b_cluster_dist:    float = 5.0,
        b_gap_to_a:        float = 20.0,    # mm – cylinder top stays this far below nearest A
        max_base_area:     float = 150.0,
        wall_mm:           float = 1.2,
        min_wall_mm:       float = 0.4,     # minimum printable wall (≥ 1 line width)
        min_outer_r:          float = 1.5,
        tip_arm_length:       float = 2.0,
        branch_merge_dist:    float = 5.0,
        branch_radius:        float = 0.4,   # mm – radius at A (tip end)
        branch_base_radius:   float = 1.2,   # mm – radius at cylinder (base end)
        min_branch_length:    float = 1.0,   # mm – drop shorter segments
        min_branch_angle_deg: float = 20.0,  # °  – min angle from horizontal
        min_levels:           int   = 4,     # minimum merge iterations
        max_levels:           int   = 10,    # maximum merge iterations
    ):
        self.layer_height         = layer_height
        self.sides                = sides
        self.b_cluster_dist       = b_cluster_dist
        self.b_gap_to_a           = b_gap_to_a
        self.max_base_area        = max_base_area
        self.wall_mm              = wall_mm
        self.min_wall_mm          = min_wall_mm
        self.min_outer_r          = min_outer_r
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

    def inject(self, pairs: List[ContactPair]) -> None:
        if not pairs:
            Logger.log("w", "[MarkerInjector] No contact pairs to inject.")
            return

        self.clear()

        # ── A markers: one small solid cylinder per contact point ─────── #
        A_verts, A_idx = self._build_solid_cylinders(
            centers=[p.A for p in pairs],
            radius=0.5,
            height=3 * self.layer_height,
        )

        # ── B dot markers: flat disc at each B point on build plate ───── #
        Bdot_verts, Bdot_idx = self._build_flat_discs(
            centers=[p.B for p in pairs],
            radius=self.min_outer_r,
        )

        # ── B markers: cluster pairs by proximity of B (XZ), keep A links #
        pair_clusters = self._cluster_pairs(pairs, self.b_cluster_dist)
        Logger.log("d", "[MarkerInjector] %d B points → %d clusters", len(pairs), len(pair_clusters))

        B_verts_list:  List[np.ndarray]   = []
        B_idx_list:    List[np.ndarray]   = []
        cluster_cyls:  List[CylinderInfo] = []
        b_offset = 0

        for cluster_pairs in pair_clusters:
            b_pts  = np.array([p.B for p in cluster_pairs], dtype=np.float32)
            cx     = float(b_pts[:, 0].mean())
            cz     = float(b_pts[:, 2].mean())
            center = np.array([cx, 0.0, cz], dtype=np.float32)

            # outer radius = spread of cluster + 1 mm margin, min min_outer_r
            if len(b_pts) == 1:
                outer_r = self.min_outer_r
            else:
                dists   = np.sqrt((b_pts[:, 0] - cx) ** 2 + (b_pts[:, 2] - cz) ** 2)
                outer_r = max(float(dists.max()) + self.wall_mm + 1.0, self.min_outer_r)

            # Cap so footprint area π·outer_r² ≤ max_base_area
            max_r   = float(np.sqrt(self.max_base_area / np.pi))
            outer_r = min(outer_r, max_r)

            # Wall thickness: respect minimum printable wall (≥ line_width)
            actual_wall = max(self.wall_mm, self.min_wall_mm)
            inner_r = max(outer_r - actual_wall, self.min_wall_mm)

            # Height: find nearest A point to cylinder center (XZ), use its Y minus gap
            a_pts  = np.array([p.A for p in cluster_pairs], dtype=np.float32)
            dx     = a_pts[:, 0] - cx
            dz     = a_pts[:, 2] - cz
            nearest_idx = int(np.argmin(dx * dx + dz * dz))
            nearest_a_y = float(a_pts[nearest_idx, 1])
            b_height    = max(nearest_a_y - self.b_gap_to_a, self.layer_height)

            v, idx = self._hollow_cylinder(center, outer_r, inner_r, b_height)
            B_verts_list.append(v)
            B_idx_list.append(idx + b_offset)
            b_offset += len(v)
            cluster_cyls.append(CylinderInfo(cx=cx, cz=cz, outer_r=outer_r, height=b_height))

        B_verts = np.vstack(B_verts_list).astype(np.float32)
        B_idx   = np.vstack(B_idx_list).astype(np.int32)

        # ── Branch lines: A → cylinder connection points ─────────────── #
        builder = BranchBuilder(
            tip_arm_length       = self.tip_arm_length,
            branch_merge_dist    = self.branch_merge_dist,
            branch_radius        = self.branch_radius,
            branch_base_radius   = self.branch_base_radius,
            min_branch_length    = self.min_branch_length,
            min_branch_angle_deg = self.min_branch_angle_deg,
            min_levels           = self.min_levels,
            max_levels           = self.max_levels,
        )
        branch_segs = builder.build_segments(pair_clusters, cluster_cyls)
        Br_verts, Br_idx = self._build_tubes(branch_segs)

        # ── Merge branch mesh into cylinder mesh (same sliceable object) ─ #
        # Cura auto-drops any CuraSceneNode whose min-Y > 0.
        # B cylinder always has min-Y = 0, so combining keeps position correct.
        combined_verts = np.vstack([B_verts, Br_verts]).astype(np.float32)
        combined_idx   = np.vstack([
            B_idx,
            Br_idx + len(B_verts),
        ]).astype(np.int32)

        # ── Inject into scene ─────────────────────────────────────────── #
        app   = CuraApplication.getInstance()
        scene = app.getController().getScene()

        op = GroupedOperation()
        for name, verts, idx, sliceable in [
            (NAME_A,     A_verts,        A_idx,        False),
            (NAME_B_DOT, Bdot_verts,     Bdot_idx,     False),
            (NAME_B,     combined_verts, combined_idx, True),
        ]:
            node = self._make_node(name, verts, idx, sliceable=sliceable)
            op.addOperation(AddSceneNodeOperation(node, scene.getRoot()))
        op.push()

        scene.sceneChanged.emit(scene.getRoot())
        Logger.log("i", "[MarkerInjector] A=%d pts  B=%d clusters  (layer_h=%.2f)",
                   len(pairs), len(pair_clusters), self.layer_height)

    def clear(self) -> None:
        app   = CuraApplication.getInstance()
        scene = app.getController().getScene()
        root  = scene.getRoot()

        nodes_to_remove = [
            n for n in root.getChildren()
            if n.getName() in (NAME_A, NAME_B, NAME_B_DOT, NAME_BRANCH)
            # NAME_BRANCH kept for backward compat (old scenes may have it)
        ]
        if not nodes_to_remove:
            return

        op = GroupedOperation()
        for n in nodes_to_remove:
            op.addOperation(RemoveSceneNodeOperation(n))
        op.push()
        scene.sceneChanged.emit(root)

    # ------------------------------------------------------------------ #
    #  Scene node factory                                                  #
    # ------------------------------------------------------------------ #

    def _make_node(self, name: str, verts: np.ndarray, idx: np.ndarray,
                   sliceable: bool = False) -> SceneNode:
        builder = MeshBuilder()
        builder.setVertices(verts)
        builder.setIndices(idx)
        builder.calculateNormals()

        if sliceable:
            # CuraSceneNode: sliceable printable object, grounded at Y=0
            node = CuraSceneNode()
            node.addDecorator(SliceableObjectDecorator())
            node.addDecorator(BuildPlateDecorator(0))
        else:
            # Plain SceneNode: visual marker only, NOT sliceable
            node = SceneNode()
        node.setName(name)
        node.setSelectable(True)
        node.setCalculateBoundingBox(True)
        node.setMeshData(builder.build())
        return node

    # ------------------------------------------------------------------ #
    #  Branch tube helpers                                                 #
    # ------------------------------------------------------------------ #

    def _build_tubes(
        self,
        segments: "List[BranchSegment]",
    ) -> "Tuple[np.ndarray, np.ndarray]":
        """Build one merged mesh from a list of BranchSegments (tapered frustums)."""
        _empty = (np.zeros((3, 3), dtype=np.float32), np.array([[0, 1, 2]], dtype=np.int32))
        if not segments:
            return _empty
        all_v, all_i = [], []
        offset = 0
        for seg in segments:
            v, idx = self._frustum_segment(seg.start, seg.end,
                                           seg.radius_start, seg.radius_end)
            if len(v) == 0:
                continue
            all_v.append(v)
            all_i.append(idx + offset)
            offset += len(v)
        if not all_v:
            return _empty
        return np.vstack(all_v).astype(np.float32), np.vstack(all_i).astype(np.int32)

    def _frustum_segment(
        self,
        start:        np.ndarray,
        end:          np.ndarray,
        radius_start: float,
        radius_end:   float,
    ) -> "Tuple[np.ndarray, np.ndarray]":
        """
        Open frustum (truncated cone) between two arbitrary 3D points.
        radius_start at start, radius_end at end.  No end caps.
        """
        s = self.sides
        d = (end - start).astype(np.float64)
        length = float(np.linalg.norm(d))
        if length < 1e-4:
            return np.zeros((0, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.int32)

        d_hat = d / length

        # Orthonormal frame perpendicular to d_hat
        ref = np.array([0.0, 1.0, 0.0])
        if abs(float(np.dot(d_hat, ref))) > 0.99:
            ref = np.array([1.0, 0.0, 0.0])
        u = np.cross(d_hat, ref);  u /= np.linalg.norm(u)
        v = np.cross(d_hat, u)

        angles = np.linspace(0, 2 * np.pi, s, endpoint=False)
        cos_a  = np.cos(angles)
        sin_a  = np.sin(angles)
        dir_u  = np.outer(cos_a, u)   # (s, 3)
        dir_v  = np.outer(sin_a, v)   # (s, 3)

        bot = (start.astype(np.float64) + radius_start * (dir_u + dir_v)).astype(np.float32)
        top = (end.astype(np.float64)   + radius_end   * (dir_u + dir_v)).astype(np.float32)
        verts = np.vstack([bot, top])   # (2s, 3)

        faces = []
        for i in range(s):
            j = (i + 1) % s
            faces += [[i, j, s + i], [j, s + j, s + i]]

        return verts, np.array(faces, dtype=np.int32)

    # ------------------------------------------------------------------ #
    #  Clustering                                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _cluster_pairs(pairs: "List[ContactPair]", max_dist: float) -> "List[List[ContactPair]]":
        """
        Union-Find clustering of ContactPairs by B-point XZ distance.
        Returns list of clusters, each cluster is a list of ContactPair.
        """
        n = len(pairs)
        parent = list(range(n))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        pts = np.array([p.B for p in pairs], dtype=np.float32)
        for i in range(n):
            for j in range(i + 1, n):
                dx = pts[i, 0] - pts[j, 0]
                dz = pts[i, 2] - pts[j, 2]
                if dx * dx + dz * dz <= max_dist * max_dist:
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        parent[ri] = rj

        groups: dict = {}
        for i in range(n):
            r = find(i)
            groups.setdefault(r, []).append(pairs[i])
        return list(groups.values())

    # ------------------------------------------------------------------ #
    #  Mesh builders                                                       #
    # ------------------------------------------------------------------ #

    def _build_flat_discs(
        self,
        centers: List[np.ndarray],
        radius:  float,
    ) -> Tuple[np.ndarray, np.ndarray]:
        all_v, all_i = [], []
        offset = 0
        for c in centers:
            v, idx = self._flat_disc(c, radius)
            all_v.append(v)
            all_i.append(idx + offset)
            offset += len(v)
        return np.vstack(all_v).astype(np.float32), np.vstack(all_i).astype(np.int32)

    def _flat_disc(
        self,
        center: np.ndarray,
        radius: float,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Flat polygon disc at Y = center[1] (build plate, Y=0).
        Double-sided: top face + bottom face so it's visible from both sides."""
        s  = self.sides
        cx, cy, cz = float(center[0]), float(center[1]), float(center[2])
        angles = np.linspace(0, 2 * np.pi, s, endpoint=False)
        ring   = np.column_stack([cx + radius * np.cos(angles),
                                  np.full(s, cy),
                                  cz + radius * np.sin(angles)])
        ctr    = np.array([[cx, cy, cz]])
        verts  = np.vstack([ring, ctr])   # s+1 vertices, index s = center
        ci     = s
        faces  = []
        for i in range(s):
            j = (i + 1) % s
            faces.append([ci, i,  j ])   # top face (CCW from above)
            faces.append([ci, j,  i ])   # bottom face (CW from above = visible below)
        return verts.astype(np.float32), np.array(faces, dtype=np.int32)

    def _build_solid_cylinders(
        self,
        centers: List[np.ndarray],
        radius:  float,
        height:  float,
    ) -> Tuple[np.ndarray, np.ndarray]:
        all_v, all_i = [], []
        offset = 0
        for c in centers:
            v, idx = self._solid_cylinder(c, radius, height)
            all_v.append(v)
            all_i.append(idx + offset)
            offset += len(v)
        return np.vstack(all_v).astype(np.float32), np.vstack(all_i).astype(np.int32)

    def _solid_cylinder(
        self,
        center: np.ndarray,
        radius: float,
        height: float,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Solid cylinder.  center Y → center Y + height."""
        s  = self.sides
        cx, cy, cz = float(center[0]), float(center[1]), float(center[2])
        angles = np.linspace(0, 2 * np.pi, s, endpoint=False)

        bot = np.column_stack([cx + radius * np.cos(angles), np.full(s, cy),          cz + radius * np.sin(angles)])
        top = np.column_stack([cx + radius * np.cos(angles), np.full(s, cy + height), cz + radius * np.sin(angles)])
        bc  = np.array([[cx, cy,          cz]])
        tc  = np.array([[cx, cy + height, cz]])
        verts = np.vstack([bot, top, bc, tc])   # 2s+2

        bc_i, tc_i = 2 * s, 2 * s + 1
        faces = []
        for i in range(s):
            j = (i + 1) % s
            faces += [[i, j, s+i], [j, s+j, s+i]]          # sides
            faces.append([bc_i, j,   i   ])                  # bottom cap
            faces.append([tc_i, s+i, s+j ])                  # top cap

        return verts.astype(np.float32), np.array(faces, dtype=np.int32)

    def _hollow_cylinder(
        self,
        center:  np.ndarray,
        outer_r: float,
        inner_r: float,
        height:  float,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Hollow cylinder (tube).  Y = center[1] → center[1] + height.

        Vertex layout (s = sides):
          [0  .. s-1 ]  outer bottom
          [s  .. 2s-1]  outer top
          [2s .. 3s-1]  inner bottom
          [3s .. 4s-1]  inner top
        Total: 4s vertices, 8s triangles.
        """
        s  = self.sides
        cx, cy, cz = float(center[0]), float(center[1]), float(center[2])
        angles = np.linspace(0, 2 * np.pi, s, endpoint=False)

        ob = np.column_stack([cx + outer_r * np.cos(angles), np.full(s, cy),          cz + outer_r * np.sin(angles)])
        ot = np.column_stack([cx + outer_r * np.cos(angles), np.full(s, cy + height), cz + outer_r * np.sin(angles)])
        ib = np.column_stack([cx + inner_r * np.cos(angles), np.full(s, cy),          cz + inner_r * np.sin(angles)])
        it = np.column_stack([cx + inner_r * np.cos(angles), np.full(s, cy + height), cz + inner_r * np.sin(angles)])

        verts = np.vstack([ob, ot, ib, it]).astype(np.float32)  # (4s, 3)
        # index offsets
        OB, OT, IB, IT = 0, s, 2*s, 3*s

        faces = []
        for i in range(s):
            j = (i + 1) % s
            # Outer wall (normal outward)
            faces += [[OB+i, OB+j, OT+i], [OB+j, OT+j, OT+i]]
            # Inner wall (normal inward → reversed winding)
            faces += [[IB+i, IT+i, IB+j], [IB+j, IT+i, IT+j]]
            # Top annulus
            faces += [[OT+i, OT+j, IT+i], [OT+j, IT+j, IT+i]]
            # Bottom annulus
            faces += [[OB+i, IB+i, OB+j], [OB+j, IB+i, IB+j]]

        return verts, np.array(faces, dtype=np.int32)
