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

from ..core.ContactPointFinder import ContactPair

NAME_A = "MeshTree_MarkerA"
NAME_B = "MeshTree_MarkerB"

class MarkerInjector:

    def __init__(
        self,
        layer_height:  float = 0.2,
        sides:         int   = 12,
        b_cluster_dist: float = 5.0,
        b_gap_to_a:    float = 200.0,   # mm – cylinder top stays this far below min A in cluster
        max_base_area: float = 150.0,
        wall_mm:       float = 1.2,
        min_outer_r:   float = 1.5,
    ):
        self.layer_height  = layer_height
        self.sides         = sides
        self.b_cluster_dist = b_cluster_dist
        self.b_gap_to_a    = b_gap_to_a
        self.max_base_area = max_base_area
        self.wall_mm       = wall_mm
        self.min_outer_r   = min_outer_r

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

        # ── B markers: cluster pairs by proximity of B (XZ), keep A links #
        pair_clusters = self._cluster_pairs(pairs, self.b_cluster_dist)
        Logger.log("d", "[MarkerInjector] %d B points → %d clusters", len(pairs), len(pair_clusters))

        B_verts_list: List[np.ndarray] = []
        B_idx_list:   List[np.ndarray] = []
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

            inner_r = max(outer_r - self.wall_mm, 0.3)

            # Height: reach up to min(A.y) minus gap; if gap > A.y, go to 90% of A.y
            min_a_y  = float(min(p.A[1] for p in cluster_pairs))
            if min_a_y > self.b_gap_to_a:
                b_height = min_a_y - self.b_gap_to_a
            else:
                b_height = min_a_y * 0.9
            b_height = max(b_height, self.layer_height)

            v, idx = self._hollow_cylinder(center, outer_r, inner_r, b_height)
            B_verts_list.append(v)
            B_idx_list.append(idx + b_offset)
            b_offset += len(v)

        B_verts = np.vstack(B_verts_list).astype(np.float32)
        B_idx   = np.vstack(B_idx_list).astype(np.int32)

        # ── Inject into scene ─────────────────────────────────────────── #
        app   = CuraApplication.getInstance()
        scene = app.getController().getScene()

        op = GroupedOperation()
        for name, verts, idx in [(NAME_A, A_verts, A_idx), (NAME_B, B_verts, B_idx)]:
            node = self._make_node(name, verts, idx)
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
            if n.getName() in (NAME_A, NAME_B)
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

    def _make_node(self, name: str, verts: np.ndarray, idx: np.ndarray) -> SceneNode:
        builder = MeshBuilder()
        builder.setVertices(verts)
        builder.setIndices(idx)
        builder.calculateNormals()

        # Plain SceneNode: visible in viewport, NOT sliceable, NOT snapped to build plate
        node = SceneNode()
        node.setName(name)
        node.setSelectable(True)
        node.setCalculateBoundingBox(True)
        node.setMeshData(builder.build())
        return node

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
