"""
MarkerInjector – creates small cylinder markers in the Cura scene to
visualise contact points A (on overhang) and anchor points B (build plate).

Marker dimensions (configurable):
  A markers: radius=0.5 mm, height = 3 × layer_height  (default ~0.6 mm)
  B markers: radius=0.8 mm, height = 2 × layer_height  (default ~0.4 mm)

Cylinders are added as regular sliceable CuraSceneNodes (no special mesh
type flag), so they show in the viewport and can simply be deleted later.
"""
from __future__ import annotations
from typing import List, Tuple

import numpy as np

from UM.Logger import Logger
from UM.Mesh.MeshBuilder import MeshBuilder
from UM.Operations.GroupedOperation import GroupedOperation
from UM.Operations.AddSceneNodeOperation import AddSceneNodeOperation
from UM.Operations.RemoveSceneNodeOperation import RemoveSceneNodeOperation

from cura.CuraApplication import CuraApplication
from cura.Scene.CuraSceneNode import CuraSceneNode
from cura.Scene.BuildPlateDecorator import BuildPlateDecorator
from cura.Scene.SliceableObjectDecorator import SliceableObjectDecorator

from ..core.ContactPointFinder import ContactPair

NAME_A = "MeshTree_MarkerA"
NAME_B = "MeshTree_MarkerB"


class MarkerInjector:

    def __init__(self, layer_height: float = 0.2, sides: int = 8):
        self.layer_height = layer_height
        self.sides        = sides

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def inject(self, pairs: List[ContactPair]) -> None:
        if not pairs:
            Logger.log("w", "[MarkerInjector] No contact pairs to inject.")
            return

        self.clear()

        A_verts, A_idx = self._merge_cylinders(
            [p.A for p in pairs],
            radius = 0.5,
            height = 3 * self.layer_height,
        )
        B_verts, B_idx = self._merge_cylinders(
            [p.B for p in pairs],
            radius = 0.8,
            height = 2 * self.layer_height,
        )

        app   = CuraApplication.getInstance()
        scene = app.getController().getScene()
        build_plate = app.getMultiBuildPlateModel().activeBuildPlate

        op = GroupedOperation()
        for name, verts, idx in [(NAME_A, A_verts, A_idx), (NAME_B, B_verts, B_idx)]:
            node = self._make_node(name, verts, idx, build_plate)
            op.addOperation(AddSceneNodeOperation(node, scene.getRoot()))
        op.push()

        scene.sceneChanged.emit(scene.getRoot())
        Logger.log("i", "[MarkerInjector] Injected %d A-markers and %d B-markers.",
                   len(pairs), len(pairs))

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
    #  Internals                                                           #
    # ------------------------------------------------------------------ #

    def _make_node(self, name: str, verts: np.ndarray, idx: np.ndarray, build_plate: int) -> CuraSceneNode:
        builder = MeshBuilder()
        builder.setVertices(verts)
        builder.setIndices(idx)
        builder.calculateNormals()

        node = CuraSceneNode()
        node.setName(name)
        node.setSelectable(True)
        node.setCalculateBoundingBox(True)
        node.setMeshData(builder.build())
        node.calculateBoundingBoxMesh()
        node.addDecorator(BuildPlateDecorator(build_plate))
        node.addDecorator(SliceableObjectDecorator())
        return node

    def _merge_cylinders(
        self,
        centers: List[np.ndarray],
        radius:  float,
        height:  float,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Build one mesh containing all cylinders merged together."""
        all_verts: List[np.ndarray] = []
        all_idx:   List[np.ndarray] = []
        offset = 0

        for c in centers:
            v, idx = self._cylinder(c, radius, height)
            all_verts.append(v)
            all_idx.append(idx + offset)
            offset += len(v)

        return (
            np.vstack(all_verts).astype(np.float32),
            np.vstack(all_idx).astype(np.int32),
        )

    def _cylinder(
        self,
        center: np.ndarray,
        radius: float,
        height: float,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Single cylinder.  center = (cx, cy, cz);  extends  cy → cy+height  (Y-up).
        Returns (vertices (2s+2, 3), indices (4s, 3)).
        """
        s = self.sides
        angles = np.linspace(0, 2 * np.pi, s, endpoint=False)
        cx, cy, cz = float(center[0]), float(center[1]), float(center[2])

        bot = np.column_stack([
            cx + radius * np.cos(angles),
            np.full(s, cy),
            cz + radius * np.sin(angles),
        ])                                          # (s, 3)
        top = bot.copy()
        top[:, 1] = cy + height                    # (s, 3)

        bc  = np.array([[cx, cy,          cz]])    # bottom centre
        tc  = np.array([[cx, cy + height, cz]])    # top    centre

        verts = np.vstack([bot, top, bc, tc])      # (2s+2, 3)

        faces = []
        bc_i, tc_i = 2 * s, 2 * s + 1
        for i in range(s):
            j = (i + 1) % s
            # Side
            faces.append([i,     j,     s + i])
            faces.append([j,     s + j, s + i])
            # Bottom cap (normal down: winding CW from below)
            faces.append([bc_i,  j,     i    ])
            # Top cap
            faces.append([tc_i,  s + i, s + j])

        return verts.astype(np.float32), np.array(faces, dtype=np.int32)
