import os
import math
import numpy as np
from typing import List, Tuple, Optional

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, pyqtProperty

from UM.Extension import Extension
from UM.Application import Application
from UM.Logger import Logger
from UM.Math.Vector import Vector
from UM.Mesh.MeshBuilder import MeshBuilder
from UM.Scene.SceneNode import SceneNode
from UM.Operations.AddSceneNodeOperation import AddSceneNodeOperation
from UM.Operations.RemoveSceneNodeOperation import RemoveSceneNodeOperation
from UM.Operations.GroupedOperation import GroupedOperation
from UM.i18n import i18nCatalog
from cura.Scene.BuildPlateDecorator import BuildPlateDecorator
from cura.Scene.SliceableObjectDecorator import SliceableObjectDecorator
from cura.Scene.CuraSceneNode import CuraSceneNode

catalog = i18nCatalog("cura")

_SUPPORT_NODE_TAG  = "__overhang_support_point__"
_OVERLAY_NODE_TAG  = "__overhang_overlay__"

_PREF_ANGLE        = "overhang_support_visualizer/overhang_angle"
_PREF_SPACING      = "overhang_support_visualizer/point_spacing"
_PREF_DIAM         = "overhang_support_visualizer/point_diameter"
_PREF_OFFSET       = "overhang_support_visualizer/point_offset"
_PREF_SHOW_OVERLAY = "overhang_support_visualizer/show_overlay"


class OverhangSupportPlugin(QObject, Extension):
    """Extension plugin that detects overhang areas and visualizes support points."""

    overhangAngleChanged = pyqtSignal()
    pointSpacingChanged = pyqtSignal()
    pointDiameterChanged = pyqtSignal()
    pointOffsetChanged = pyqtSignal()
    showOverlayChanged = pyqtSignal()
    statusChanged = pyqtSignal()

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        Extension.__init__(self)

        self._support_point_nodes: List[SceneNode] = []
        self._overlay_nodes: List[SceneNode] = []
        self._status_message = ""
        self._panel = None

        # Register preferences with defaults; Cura persists them automatically.
        prefs = Application.getInstance().getPreferences()
        prefs.addPreference(_PREF_ANGLE,        45)
        prefs.addPreference(_PREF_SPACING,        5)
        prefs.addPreference(_PREF_DIAM,           2)
        prefs.addPreference(_PREF_OFFSET,         0)
        prefs.addPreference(_PREF_SHOW_OVERLAY, True)

        # Load saved values
        self._overhang_angle  = int(prefs.getValue(_PREF_ANGLE))
        self._point_spacing   = round(float(prefs.getValue(_PREF_SPACING)), 2)
        self._point_diameter  = round(float(prefs.getValue(_PREF_DIAM)), 2)
        self._point_offset    = round(float(prefs.getValue(_PREF_OFFSET)), 2)
        self._show_overlay    = bool(prefs.getValue(_PREF_SHOW_OVERLAY))

        self.setMenuName(catalog.i18nc("@item:inmenu", "Overhang Support Visualizer"))
        self.addMenuItem(
            catalog.i18nc("@item:inmenu", "Open Panel"),
            self._openPanel
        )

    # ------------------------------------------------------------------
    # QML properties
    # ------------------------------------------------------------------

    @pyqtProperty(int, notify=overhangAngleChanged)
    def overhangAngle(self) -> int:
        return self._overhang_angle

    @overhangAngle.setter
    def overhangAngle(self, value: int):
        value = max(0, min(90, int(value)))
        if self._overhang_angle != value:
            self._overhang_angle = value
            Application.getInstance().getPreferences().setValue(_PREF_ANGLE, value)
            self.overhangAngleChanged.emit()

    @pyqtProperty(float, notify=pointSpacingChanged)
    def pointSpacing(self) -> float:
        return self._point_spacing

    @pointSpacing.setter
    def pointSpacing(self, value: float):
        value = round(max(0.01, float(value)), 2)
        if self._point_spacing != value:
            self._point_spacing = value
            Application.getInstance().getPreferences().setValue(_PREF_SPACING, value)
            self.pointSpacingChanged.emit()

    @pyqtProperty(float, notify=pointDiameterChanged)
    def pointDiameter(self) -> float:
        return self._point_diameter

    @pointDiameter.setter
    def pointDiameter(self, value: float):
        value = round(max(0.01, float(value)), 2)
        if self._point_diameter != value:
            self._point_diameter = value
            Application.getInstance().getPreferences().setValue(_PREF_DIAM, value)
            self.pointDiameterChanged.emit()

    @pyqtProperty(float, notify=pointOffsetChanged)
    def pointOffset(self) -> float:
        return self._point_offset

    @pointOffset.setter
    def pointOffset(self, value: float):
        value = round(max(0.0, float(value)), 2)
        if self._point_offset != value:
            self._point_offset = value
            Application.getInstance().getPreferences().setValue(_PREF_OFFSET, value)
            self.pointOffsetChanged.emit()

    @pyqtProperty(bool, notify=showOverlayChanged)
    def showOverlay(self) -> bool:
        return self._show_overlay

    @showOverlay.setter
    def showOverlay(self, value: bool):
        value = bool(value)
        if self._show_overlay != value:
            self._show_overlay = value
            Application.getInstance().getPreferences().setValue(_PREF_SHOW_OVERLAY, value)
            for node in self._overlay_nodes:
                node.setVisible(value)
            self.showOverlayChanged.emit()

    @pyqtProperty(str, notify=statusChanged)
    def statusMessage(self) -> str:
        return self._status_message

    # ------------------------------------------------------------------
    # Panel
    # ------------------------------------------------------------------

    def _openPanel(self):
        if self._panel is None:
            qml_path = os.path.join(os.path.dirname(__file__), "OverhangSupportPanel.qml")
            self._panel = Application.getInstance().createQmlSubWindow(
                qml_path, {"manager": self}
            )
        if self._panel:
            self._panel.show()

    # ------------------------------------------------------------------
    # Public slots callable from QML
    # ------------------------------------------------------------------

    @pyqtSlot()
    def detectAndVisualize(self):
        """Detect overhang areas on all scene objects, create overlay + support markers."""
        self.clearSupportPoints()

        scene = Application.getInstance().getController().getScene()

        # Collect only nodes that will actually be printed with plastic:
        #   - have SliceableObjectDecorator  (isSliceable == True)
        #   - are NOT special mesh types (support, anti-overhang, cutting, infill)
        _SPECIAL_MESH_KEYS = ("support_mesh", "anti_overhang_mesh", "cutting_mesh", "infill_mesh")

        all_nodes = []
        for node in scene.getRoot().getAllChildren():
            if node.getMeshData() is None:
                continue
            # Bỏ qua các node do plugin này tạo ra
            if node.getName() in (_SUPPORT_NODE_TAG, _OVERLAY_NODE_TAG):
                continue
            if not node.callDecoration("isSliceable"):
                continue
            # Bỏ qua các loại mesh đặc biệt (không phải object in thật)
            stack = node.callDecoration("getStack")
            if stack is not None:
                if any(stack.getProperty(k, "value") for k in _SPECIAL_MESH_KEYS):
                    continue
            all_nodes.append(node)

        if not all_nodes:
            self._setStatus("No objects in scene.")
            return

        operations = []
        total_points = 0

        # Pre-build sphere mesh (shared across all support points)
        radius = self._point_diameter / 2.0
        sphere_mesh = self._buildSphereMesh(radius)

        for node in all_nodes:
            mesh_data = node.getMeshData()
            if mesh_data is None:
                continue

            self._setStatus(f"Analysing '{node.getName()}'…")

            overhang_faces = self._detectOverhangFaces(mesh_data, node.getWorldTransformation())
            if not overhang_faces:
                continue

            # ── Overlay mesh (tô màu vùng overhang) ──────────────────
            active_plate = Application.getInstance().getMultiBuildPlateModel().activeBuildPlate
            # Dùng CuraSceneNode để SolidView nhận ra và render với màu extruder
            overlay = CuraSceneNode()
            overlay.setName(_OVERLAY_NODE_TAG)
            overlay.setMeshData(self._buildOverhangMesh(overhang_faces, offset=max(0.15, self._point_offset)))
            overlay.setSelectable(False)
            overlay.setVisible(self._show_overlay)
            overlay.addDecorator(BuildPlateDecorator(active_plate))
            overlay.addDecorator(SliceableObjectDecorator())
            # support_mesh = True → ngăn slicer xử lý như object thật
            stack = overlay.callDecoration("getStack")
            if stack:
                from UM.Settings.SettingInstance import SettingInstance
                settings = stack.getTop()
                defn = stack.getSettingDefinition("support_mesh")
                if defn:
                    inst = SettingInstance(defn, settings)
                    inst.setProperty("value", True)
                    inst.resetState()
                    settings.addInstance(inst)
            # Gán sang extruder 1 → SolidView render màu extruder 1 (khác object thật)
            try:
                overlay.callDecoration("setActiveExtruder", "1")
            except Exception:
                pass
            self._overlay_nodes.append(overlay)
            operations.append(AddSceneNodeOperation(overlay, scene.getRoot()))

            # ── Điểm chống đỡ ────────────────────────────────────────
            points = self._sampleSupportPoints(overhang_faces, float(self._point_spacing))
            total_points += len(points)

            for pt in points:
                marker = SceneNode()
                marker.setName(_SUPPORT_NODE_TAG)
                marker.setMeshData(sphere_mesh)
                marker.setSelectable(False)
                # Cura dùng Y là trục đứng; offset dương → hạ điểm xuống (-Y)
                marker.setPosition(Vector(float(pt[0]), float(pt[1]) - self._point_offset, float(pt[2])))

                self._support_point_nodes.append(marker)
                operations.append(AddSceneNodeOperation(marker, scene.getRoot()))

        if operations:
            op = GroupedOperation()
            for o in operations:
                op.addOperation(o)
            op.push()
            self._setStatus(
                f"Detected {total_points} support point(s) on overhang areas "
                f"(angle ≥ {self._overhang_angle}°, spacing {self._point_spacing} mm, "
                f"Ø {self._point_diameter} mm)."
            )
        else:
            self._setStatus(
                f"No overhang areas found with angle ≥ {self._overhang_angle}°. "
                "Try reducing the overhang angle."
            )

    @pyqtSlot()
    def clearSupportPoints(self):
        """Remove all overlay and support-point marker nodes from the scene."""
        all_nodes = self._support_point_nodes + self._overlay_nodes
        if not all_nodes:
            return

        op = GroupedOperation()
        for node in all_nodes:
            if node.getParent() is not None:
                op.addOperation(RemoveSceneNodeOperation(node))
        op.push()
        self._support_point_nodes.clear()
        self._overlay_nodes.clear()
        self._setStatus("Support point markers cleared.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _setStatus(self, msg: str):
        self._status_message = msg
        self.statusChanged.emit()
        Logger.log("d", "[OverhangSupportPlugin] %s", msg)

    def _detectOverhangFaces(self, mesh_data, transform_matrix) -> List[Tuple]:
        """
        Return a list of (v0, v1, v2) world-space triangles whose normals point
        downward beyond the configured overhang angle.

        In Cura the Y axis is UP.  A face is "overhanging" when its outward
        normal has a negative Y component whose magnitude exceeds
        cos(overhang_angle), i.e. normal_y < -cos(overhang_angle_rad).
        """
        vertices = mesh_data.getVertices()
        indices = mesh_data.getIndices()

        if vertices is None:
            return []

        # --- transform all vertices to world space in one numpy op ----------
        mat = transform_matrix.getData()   # 4×4 column-major (OpenGL style)
        ones = np.ones((len(vertices), 1), dtype=np.float32)
        local_h = np.hstack([vertices, ones])   # (N, 4)
        # UM Vector.preMultiply does: result = mat @ [x,y,z,1]
        # so world_row = local_row @ mat.T
        world_h = local_h @ mat.T               # (N, 4)
        world_verts = world_h[:, :3]            # (N, 3)

        # --- gather triangle vertex positions --------------------------------
        if indices is not None:
            idx = indices.reshape(-1, 3).astype(np.int32)
        else:
            n = len(world_verts)
            idx = np.arange(n).reshape(-1, 3)

        v0 = world_verts[idx[:, 0]]   # (M, 3)
        v1 = world_verts[idx[:, 1]]
        v2 = world_verts[idx[:, 2]]

        # --- compute face normals (world space) ------------------------------
        edge1 = v1 - v0
        edge2 = v2 - v0
        normals = np.cross(edge1, edge2)        # (M, 3)
        lengths = np.linalg.norm(normals, axis=1)  # (M,)

        valid = lengths > 1e-10
        normals[valid] /= lengths[valid, np.newaxis]

        # --- overhang test ---------------------------------------------------
        threshold = -math.cos(math.radians(self._overhang_angle))
        overhang_mask = valid & (normals[:, 1] < threshold)

        oi = np.where(overhang_mask)[0]
        return list(zip(v0[oi], v1[oi], v2[oi]))

    def _sampleSupportPoints(
        self,
        overhang_faces: List[Tuple],
        spacing: float
    ) -> List[np.ndarray]:
        """
        Distribute support points on overhang faces using area-weighted random
        sampling with a Poisson-disk minimum-distance filter.

        Faces with a lower centroid Y (thấp hơn trên trục đứng) get higher
        sampling priority so contact points are preferentially placed on the
        lowest overhanging surfaces first.
        """
        rng = np.random.default_rng(seed=0)   # reproducible

        # --- per-face metrics ------------------------------------------------
        areas    = np.empty(len(overhang_faces), dtype=np.float64)
        center_y = np.empty(len(overhang_faces), dtype=np.float64)
        for i, (v0, v1, v2) in enumerate(overhang_faces):
            areas[i]    = 0.5 * np.linalg.norm(np.cross(v1 - v0, v2 - v0))
            center_y[i] = (v0[1] + v1[1] + v2[1]) / 3.0

        total_area = areas.sum()
        if total_area < 1e-6:
            return []

        # target number of points based on area / spacing²
        num_target = max(1, int(total_area / (spacing * spacing)))
        num_target = min(num_target, 1000)   # safety cap

        # --- Z-priority weight ----------------------------------------------
        # Cura dùng Y là trục đứng: Y thấp hơn = gần mặt bàn hơn = ưu tiên cao
        y_min, y_max = center_y.min(), center_y.max()
        if y_max > y_min:
            # lowness ∈ [0, 1]: 1 = vùng thấp nhất, 0 = vùng cao nhất
            lowness = (y_max - center_y) / (y_max - y_min)
        else:
            lowness = np.ones(len(overhang_faces))

        # Kết hợp diện tích × hệ số ưu tiên độ cao (mũ 2 để khuếch đại chênh lệch)
        weights = areas * (lowness ** 2 + 0.05)
        weights /= weights.sum()

        points: List[np.ndarray] = []

        max_attempts = num_target * 30
        for _ in range(max_attempts):
            if len(points) >= num_target:
                break

            # pick a random face (area-weighted)
            fi = rng.choice(len(overhang_faces), p=weights)
            v0, v1, v2 = overhang_faces[fi]

            # uniform random point inside the triangle (barycentric)
            r1 = rng.random()
            r2 = rng.random()
            if r1 + r2 > 1.0:
                r1, r2 = 1.0 - r1, 1.0 - r2
            pt = v0 + r1 * (v1 - v0) + r2 * (v2 - v0)

            # Poisson-disk rejection
            if any(np.linalg.norm(pt - ex) < spacing for ex in points):
                continue

            points.append(pt)

        return points

    @staticmethod
    def _buildOverhangMesh(overhang_faces: List[Tuple], offset: float = 0.15):  # offset tính bằng mm
        """
        Build a double-sided MeshData from overhang triangles (world-space coords).

        Each face is duplicated with reversed winding so it renders from both sides.
        Vertices are shifted slightly along the face normal (outward = downward for
        bottom-facing surfaces) to avoid z-fighting with the original object mesh.
        """
        verts = []
        idxs  = []

        for v0, v1, v2 in overhang_faces:
            # Face normal (already pointing downward for overhang faces)
            edge1 = v1 - v0
            edge2 = v2 - v0
            n = np.cross(edge1, edge2)
            length = np.linalg.norm(n)
            n = (n / length) if length > 1e-10 else np.array([0.0, -1.0, 0.0])

            # Push vertices slightly outward to avoid z-fighting
            dv = n * offset
            ov0, ov1, ov2 = v0 + dv, v1 + dv, v2 + dv

            base = len(verts)
            verts.extend([ov0, ov1, ov2])
            # Front face (normal direction)
            idxs.extend([base, base + 1, base + 2])
            # Back face (reversed winding) — visible from any camera angle
            idxs.extend([base, base + 2, base + 1])

        builder = MeshBuilder()
        builder.setVertices(np.array(verts, dtype=np.float32))
        builder.setIndices(np.array(idxs, dtype=np.int32).reshape(-1, 3))
        builder.calculateNormals()
        return builder.build()

    @staticmethod
    def _buildSphereMesh(radius: float, segments: int = 16, rings: int = 10):
        """Build a UV-sphere MeshData of the given radius."""
        verts = []
        for ring in range(rings + 1):
            phi = math.pi * ring / rings          # 0 … π
            for seg in range(segments):
                theta = 2.0 * math.pi * seg / segments
                x = radius * math.sin(phi) * math.cos(theta)
                y = radius * math.cos(phi)
                z = radius * math.sin(phi) * math.sin(theta)
                verts.append([x, y, z])

        idxs = []
        for ring in range(rings):
            for seg in range(segments):
                a = ring * segments + seg
                b = ring * segments + (seg + 1) % segments
                c = (ring + 1) * segments + (seg + 1) % segments
                d = (ring + 1) * segments + seg
                idxs += [a, b, c, a, c, d]

        builder = MeshBuilder()
        builder.setVertices(np.array(verts, dtype=np.float32))
        builder.setIndices(np.array(idxs, dtype=np.int32).reshape(-1, 3))
        builder.calculateNormals()
        return builder.build()
