"""
SceneNodeInjector – injects a support mesh into the Cura scene.
Stub: ready for implementation.
"""
from __future__ import annotations
from typing import Optional

import numpy as np

from UM.Logger import Logger
from UM.Operations.GroupedOperation import GroupedOperation

try:
    from cura.CuraApplication import CuraApplication
    from cura.Scene.CuraSceneNode import CuraSceneNode
    from cura.Scene.BuildPlateDecorator import BuildPlateDecorator
    from cura.Scene.SliceableObjectDecorator import SliceableObjectDecorator
    from UM.Scene.SceneNode import SceneNode
    from UM.Mesh.MeshBuilder import MeshBuilder
    from UM.Operations.AddSceneNodeOperation import AddSceneNodeOperation
    from UM.Operations.RemoveSceneNodeOperation import RemoveSceneNodeOperation
    from UM.Settings.SettingInstance import SettingInstance
    _CURA_AVAILABLE = True
except ImportError:
    _CURA_AVAILABLE = False


NODE_NAME = "MeshTreeSupport"


class SceneNodeInjector:
    """
    Creates a CuraSceneNode with support_mesh=True and injects it into the scene.
    Uses GroupedOperation so the action is undoable.
    """

    def inject(self, vertices: np.ndarray, indices: np.ndarray) -> Optional[object]:
        """
        Build a MeshData from vertices/indices and add it to the scene.
        Returns the created CuraSceneNode, or None on failure.
        """
        if not _CURA_AVAILABLE:
            Logger.log("e", "[SceneNodeInjector] Cura API not available.")
            return None

        app   = CuraApplication.getInstance()
        scene = app.getController().getScene()

        # Build mesh
        builder = MeshBuilder()
        builder.setVertices(vertices)
        builder.setIndices(indices)
        builder.calculateNormals(fast=True)
        mesh_data = builder.build()

        # Create node
        node = CuraSceneNode()
        node.setName(NODE_NAME)
        node.setMeshData(mesh_data)
        node.addDecorator(BuildPlateDecorator(app.getMultiBuildPlateModel().activeBuildPlate))
        node.addDecorator(SliceableObjectDecorator())

        # Set support_mesh = True
        stack    = node.callDecoration("getStack")
        settings = stack.getTop()
        defn     = stack.getSettingDefinition("support_mesh")
        instance = SettingInstance(defn, settings)
        instance.setProperty("value", True)
        instance.resetState()
        settings.addInstance(instance)

        # Commit via operation (undo-able)
        op = GroupedOperation()
        op.addOperation(AddSceneNodeOperation(node, scene.getRoot()))
        op.push()

        scene.sceneChanged.emit(node)
        Logger.log("i", "[SceneNodeInjector] Support mesh node injected.")
        return node

    def clear(self) -> None:
        """Remove all MeshTreeSupport nodes from the scene."""
        if not _CURA_AVAILABLE:
            return

        app   = CuraApplication.getInstance()
        scene = app.getController().getScene()
        root  = scene.getRoot()

        op = GroupedOperation()
        for node in root.getChildren():
            if node.getName() == NODE_NAME:
                op.addOperation(RemoveSceneNodeOperation(node))
        op.push()
        scene.sceneChanged.emit(root)
        Logger.log("i", "[SceneNodeInjector] Support mesh nodes cleared.")
