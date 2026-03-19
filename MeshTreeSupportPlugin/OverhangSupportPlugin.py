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
_TREE_NODE_TAG     = "__overhang_tree_support__"

_PREF_ANGLE        = "overhang_support_visualizer/overhang_angle"
_PREF_SPACING      = "overhang_support_visualizer/point_spacing"
_PREF_DIAM         = "overhang_support_visualizer/point_diameter"
_PREF_OFFSET       = "overhang_support_visualizer/point_offset"
_PREF_SHOW_OVERLAY = "overhang_support_visualizer/show_overlay"

_PREF_TREE_ANGLE   = "overhang_support_visualizer/tree_branch_angle"
_PREF_TREE_BASE    = "overhang_support_visualizer/tree_base_dist"
_PREF_TREE_PER_LVL = "overhang_support_visualizer/tree_dist_per_level"
_PREF_TREE_GROWTH  = "overhang_support_visualizer/tree_growth_pct"
_PREF_TREE_STEP    = "overhang_support_visualizer/tree_step_size"


class OverhangSupportPlugin(QObject, Extension):
    """Extension plugin that detects overhang areas and visualizes support points."""

    overhangAngleChanged    = pyqtSignal()
    pointSpacingChanged     = pyqtSignal()
    pointDiameterChanged    = pyqtSignal()
    pointOffsetChanged      = pyqtSignal()
    showOverlayChanged      = pyqtSignal()
    statusChanged           = pyqtSignal()

    treeBranchAngleChanged  = pyqtSignal()
    treeBaseDistChanged     = pyqtSignal()
    treeDistPerLevelChanged = pyqtSignal()
    treeGrowthPctChanged    = pyqtSignal()
    treeStepSizeChanged     = pyqtSignal()

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        Extension.__init__(self)

        self._support_point_nodes: List[SceneNode] = []
        self._overlay_nodes:       List[SceneNode] = []
        self._tree_nodes:          List[SceneNode] = []
        self._contact_points:      List[np.ndarray] = []
        self._status_message = ""
        self._panel = None

        prefs = Application.getInstance().getPreferences()
        prefs.addPreference(_PREF_ANGLE,        45)
        prefs.addPreference(_PREF_SPACING,        5)
        prefs.addPreference(_PREF_DIAM,           2)
        prefs.addPreference(_PREF_OFFSET,         0)
        prefs.addPreference(_PREF_SHOW_OVERLAY, True)

        prefs.addPreference(_PREF_TREE_ANGLE,    30)
        prefs.addPreference(_PREF_TREE_BASE,     20)
        prefs.addPreference(_PREF_TREE_PER_LVL,   5)
        prefs.addPreference(_PREF_TREE_GROWTH,    1)
        prefs.addPreference(_PREF_TREE_STEP,     1.0)

        self._overhang_angle      = int(prefs.getValue(_PREF_ANGLE))
        self._point_spacing       = round(float(prefs.getValue(_PREF_SPACING)), 2)
        self._point_diameter      = round(float(prefs.getValue(_PREF_DIAM)), 2)
        self._point_offset        = round(float(prefs.getValue(_PREF_OFFSET)), 2)
        self._show_overlay        = bool(prefs.getValue(_PREF_SHOW_OVERLAY))

        self._tree_branch_angle   = int(prefs.getValue(_PREF_TREE_ANGLE))
        self._tree_base_dist      = round(float(prefs.getValue(_PREF_TREE_BASE)), 2)
        self._tree_dist_per_level = round(float(prefs.getValue(_PREF_TREE_PER_LVL)), 2)
        self._tree_growth_pct     = round(float(prefs.getValue(_PREF_TREE_GROWTH)), 2)
        self._tree_step_size      = round(float(prefs.getValue(_PREF_TREE_STEP)), 2)

        self.setMenuName(catalog.i18nc("@item:inmenu", "Overhang Support Visualizer"))
        self.addMenuItem(catalog.i18nc("@item:inmenu", "Open Panel"), self._openPanel)

    # ------------------------------------------------------------------
    # QML properties – contact point detection
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
    # QML properties – tree support
    # ------------------------------------------------------------------

    @pyqtProperty(int, notify=treeBranchAngleChanged)
    def treeBranchAngle(self) -> int:
        return self._tree_branch_angle

    @treeBranchAngle.setter
    def treeBranchAngle(self, value: int):
        value = max(1, min(89, int(value)))
        if self._tree_branch_angle != value:
            self._tree_branch_angle = value
            Application.getInstance().getPreferences().setValue(_PREF_TREE_ANGLE, value)
            self.treeBranchAngleChanged.emit()

    @pyqtProperty(float, notify=treeBaseDistChanged)
    def treeBaseDist(self) -> float:
        return self._tree_base_dist

    @treeBaseDist.setter
    def treeBaseDist(self, value: float):
        value = round(max(0.01, float(value)), 2)
        if self._tree_base_dist != value:
            self._tree_base_dist = value
            Application.getInstance().getPreferences().setValue(_PREF_TREE_BASE, value)
            self.treeBaseDistChanged.emit()

    @pyqtProperty(float, notify=treeDistPerLevelChanged)
    def treeDistPerLevel(self) -> float:
        return self._tree_dist_per_level

    @treeDistPerLevel.setter
    def treeDistPerLevel(self, value: float):
        value = round(max(0.0, float(value)), 2)
        if self._tree_dist_per_level != value:
            self._tree_dist_per_level = value
            Application.getInstance().getPreferences().setValue(_PREF_TREE_PER_LVL, value)
            self.treeDistPerLevelChanged.emit()

    @pyqtProperty(float, notify=treeGrowthPctChanged)
    def treeGrowthPct(self) -> float:
        return self._tree_growth_pct

    @treeGrowthPct.setter
    def treeGrowthPct(self, value: float):
        value = round(max(0.0, float(value)), 2)
        if self._tree_growth_pct != value:
            self._tree_growth_pct = value
            Application.getInstance().getPreferences().setValue(_PREF_TREE_GROWTH, value)
            self.treeGrowthPctChanged.emit()

    @pyqtProperty(float, notify=treeStepSizeChanged)
    def treeStepSize(self) -> float:
        return self._tree_step_size

    @treeStepSize.setter
    def treeStepSize(self, value: float):
        value = round(max(0.1, float(value)), 2)
        if self._tree_step_size != value:
            self._tree_step_size = value
            Application.getInstance().getPreferences().setValue(_PREF_TREE_STEP, value)
            self.treeStepSizeChanged.emit()

    # ------------------------------------------------------------------
    # Panel
    # ------------------------------------------------------------------

    def _openPanel(self):
        if self._panel is None:
            qml_path = os.path.join(os.path.dirname(__file__), "OverhangSupportPanel.qml")
            app = Application.getInstance()
            self._panel = app.createQmlComponent(qml_path, {"manager": self})
            if self._panel:
                main_window = app.getMainWindow()
                if main_window:
                    self._panel.setTransientParent(main_window)
        if self._panel:
            self._panel.show()

    # ------------------------------------------------------------------
    # Public slots callable from QML
    # ------------------------------------------------------------------

    @pyqtSlot()
    def detectAndVisualize(self):
        """Detect overhang areas on all scene objects, create overlay + support markers."""
        self.clearSupportPoints()
        self._contact_points.clear()

        scene = Application.getInstance().getController().getScene()

        _SPECIAL_MESH_KEYS = ("support_mesh", "anti_overhang_mesh", "cutting_mesh", "infill_mesh")

        all_nodes = []
        for node in scene.getRoot().getAllChildren():
            if node.getMeshData() is None:
                continue
            if node.getName() in (_SUPPORT_NODE_TAG, _OVERLAY_NODE_TAG, _TREE_NODE_TAG):
                continue
            if not node.callDecoration("isSliceable"):
                continue
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

            active_plate = Application.getInstance().getMultiBuildPlateModel().activeBuildPlate
            overlay = CuraSceneNode()
            overlay.setName(_OVERLAY_NODE_TAG)
            overlay.setMeshData(self._buildOverhangMesh(overhang_faces, offset=max(0.15, self._point_offset)))
            overlay.setSelectable(False)
            overlay.setVisible(self._show_overlay)
            overlay.addDecorator(BuildPlateDecorator(active_plate))
            overlay.addDecorator(SliceableObjectDecorator())
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
            try:
                overlay.callDecoration("setActiveExtruder", "1")
            except Exception:
                pass
            self._overlay_nodes.append(overlay)
            operations.append(AddSceneNodeOperation(overlay, scene.getRoot()))

            points = self._sampleSupportPoints(overhang_faces, float(self._point_spacing))
            total_points += len(points)

            for pt in points:
                self._contact_points.append(pt.copy())
                marker = SceneNode()
                marker.setName(_SUPPORT_NODE_TAG)
                marker.setMeshData(sphere_mesh)
                marker.setSelectable(False)
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
        if all_nodes:
            op = GroupedOperation()
            for node in all_nodes:
                if node.getParent() is not None:
                    op.addOperation(RemoveSceneNodeOperation(node))
            op.push()
        self._support_point_nodes.clear()
        self._overlay_nodes.clear()
        self._setStatus("Support point markers cleared.")

    @pyqtSlot()
    def generateTreeSupport(self):
        """Generate tree support structure from detected contact points."""
        self.clearTreeSupport()

        if not self._contact_points:
            self._setStatus("Chưa có contact points. Hãy chạy 'Phát hiện & Hiển thị' trước.")
            return

        self._setStatus(f"Đang tạo cây chống đỡ từ {len(self._contact_points)} điểm…")

        segments = self._buildTreeBranches(self._contact_points)
        if not segments:
            self._setStatus("Không tạo được đường cây chống đỡ.")
            return

        mesh = self._buildTreeMesh(segments, self._point_diameter, self._tree_growth_pct)
        if mesh is None:
            self._setStatus("Không xây dựng được mesh cây chống đỡ.")
            return

        scene = Application.getInstance().getController().getScene()
        active_plate = Application.getInstance().getMultiBuildPlateModel().activeBuildPlate

        node = CuraSceneNode()
        node.setName(_TREE_NODE_TAG)
        node.setMeshData(mesh)
        node.setSelectable(True)
        node.addDecorator(BuildPlateDecorator(active_plate))
        node.addDecorator(SliceableObjectDecorator())

        self._tree_nodes.append(node)

        op = GroupedOperation()
        op.addOperation(AddSceneNodeOperation(node, scene.getRoot()))
        op.push()

        self._setStatus(f"Đã tạo cây chống đỡ với {len(segments)} đoạn.")

    @pyqtSlot()
    def clearTreeSupport(self):
        """Remove all tree support nodes from the scene."""
        if self._tree_nodes:
            op = GroupedOperation()
            for node in self._tree_nodes:
                if node.getParent() is not None:
                    op.addOperation(RemoveSceneNodeOperation(node))
            op.push()
        self._tree_nodes.clear()

    # ------------------------------------------------------------------
    # Tree support simulation
    # ------------------------------------------------------------------

    def _buildTreeBranches(self, contact_points: List[np.ndarray]) -> List[Tuple]:
        """
        Simulate tree support branch growth from contact points downward.
        Returns list of (start, end, level) segments.

        Algorithm (sweep top → ground):
          • Each contact point spawns a level-0 branch going straight down.
          • Branches are activated lazily as the sweep reaches their Y height.
          • At each sweep step, ONLY unpaired branches (partner is None) try to pair.
            Branches that are already bending toward a partner are excluded from
            new pairings until they merge into a higher-level branch.
          • Pairing threshold: tree_base_dist + max(level_a, level_b) * tree_dist_per_level
          • When paired, both branches tilt at tree_branch_angle° from vertical toward
            each other's XZ midpoint.
          • When a pair's XZ distance drops below 1.5 × step, they merge: a new
            branch (level + 1) starts at the midpoint, going straight down again.
          • If a branch reaches ground (Y ≤ 0) while paired, its partner is reset to
            straight-down and freed for future pairings.
        """
        if not contact_points:
            return []

        step       = max(0.1, self._tree_step_size)
        angle_rad  = math.radians(max(1.0, min(89.0, float(self._tree_branch_angle))))
        base_dist  = max(0.01, self._tree_base_dist)
        dist_per_lvl = max(0.0, self._tree_dist_per_level)
        sin_a = math.sin(angle_rad)
        cos_a = math.cos(angle_rad)
        tan_a = math.tan(angle_rad)
        merge_dist = step * 1.5

        pt_diam    = self._point_diameter
        growth_fac = pt_diam * self._tree_growth_pct / 100.0

        def _radius_at(y: float, origin_y: float) -> float:
            """Branch radius at world-Y `y` for a branch whose origin is at `origin_y`."""
            drop = max(0.0, origin_y - y)
            return max(0.01, (pt_diam + drop * growth_fac) / 2.0)

        class _Branch:
            __slots__ = ["tip", "direction", "level", "waypoints", "active", "partner", "origin_y"]
            def __init__(self, tip, level, origin_y=None):
                self.tip       = np.array(tip, dtype=np.float64)
                self.direction = np.array([0.0, -1.0, 0.0])
                self.level     = level
                # origin_y: highest contact-point Y among all branches merged into this one.
                # Used for the taper formula: diameter grows as we descend from origin_y.
                self.origin_y  = float(tip[1]) if origin_y is None else float(origin_y)
                self.waypoints = [self.tip.copy()]   # list of recorded XYZ waypoints
                self.active    = True
                self.partner   = None                # type: Optional[_Branch]

        all_branches: List[_Branch] = []

        # Sort contact points by Y descending for lazy activation
        pending = sorted(
            [np.array(p, dtype=np.float64) for p in contact_points],
            key=lambda p: -p[1]
        )

        active:  List[_Branch] = []
        y_cur = float(pending[0][1]) if pending else 0.0
        ground_y = 0.01

        max_iters = int(y_cur / step) + 500

        for _ in range(max_iters):
            # ── Activate contact-point branches whose Y we've just reached ──────
            while pending and pending[0][1] >= y_cur - step * 0.01:
                pt = pending.pop(0)
                b  = _Branch(pt, 0)
                all_branches.append(b)
                active.append(b)

            if not active and not pending:
                break

            # ── Pair ONLY unpaired branches (partner is None) ────────────────────
            # Branches already bending toward a partner are skipped entirely.
            unpaired = [b for b in active if b.partner is None]
            if len(unpaired) >= 2:
                # Collect candidate pairs sorted by XZ distance (greedy closest-first)
                cands = []
                for i in range(len(unpaired)):
                    for j in range(i + 1, len(unpaired)):
                        a, bb = unpaired[i], unpaired[j]
                        # Only consider branches at similar heights (within 4 steps)
                        if abs(a.tip[1] - bb.tip[1]) > step * 4:
                            continue
                        eff_level = max(a.level, bb.level)
                        thresh    = base_dist + eff_level * dist_per_lvl
                        dxz = float(np.linalg.norm((a.tip - bb.tip)[[0, 2]]))
                        if dxz > thresh:
                            continue
                        # Pre-check: meeting Y must be above ground.
                        # Each branch covers dxz/2 horizontally at branch_angle,
                        # dropping (dxz/2) / tan(angle) vertically.
                        avg_y     = (a.tip[1] + bb.tip[1]) / 2.0
                        meet_y    = avg_y - (dxz / 2.0) / tan_a
                        if meet_y < ground_y:
                            continue   # would meet below ground – pairing fails
                        cands.append((dxz, i, j))
                cands.sort()

                used = set()
                for dxz, i, j in cands:
                    if i in used or j in used:
                        continue
                    a, bb = unpaired[i], unpaired[j]
                    used.add(i); used.add(j)

                    a.partner  = bb
                    bb.partner = a

                    # Record direction-change waypoint at current tip
                    a.waypoints.append(a.tip.copy())
                    bb.waypoints.append(bb.tip.copy())

                    # Set converging directions toward XZ midpoint at branch_angle
                    xz_diff = (bb.tip - a.tip)[[0, 2]]
                    norm    = float(np.linalg.norm(xz_diff))
                    if norm > 1e-6:
                        xz_d = xz_diff / norm
                        a.direction  = np.array([ xz_d[0]*sin_a, -cos_a,  xz_d[1]*sin_a])
                        bb.direction = np.array([-xz_d[0]*sin_a, -cos_a, -xz_d[1]*sin_a])

                    # For level ≥ 1: RIGHT AFTER the bend, add a short stub going UP.
                    # The stub is a separate mini-branch so the main branch tip is
                    # unchanged and the diagonal continues unaffected.
                    # Extension length = tan(branch_angle) / radius_at_pairing_point
                    # For level ≥ 1: stub goes in the MIRROR of the diagonal direction
                    # (same angle, opposite horizontal + upward) so stub and diagonal
                    # form a straight rod through the bend point.
                    for br, xz_dir_toward in ((a, xz_d), (bb, -xz_d)):
                        if br.level >= 1:
                            ext_len    = tan_a / _radius_at(br.tip[1], br.origin_y)
                            stub_dir   = np.array([-xz_dir_toward[0]*sin_a, cos_a,
                                                   -xz_dir_toward[1]*sin_a])
                            up_pt      = br.tip + stub_dir * ext_len
                            stub       = _Branch(br.tip, br.level, origin_y=br.origin_y)
                            stub.waypoints = [br.tip.copy(), up_pt]
                            stub.active    = False
                            all_branches.append(stub)

            # ── Move all active branches one step ────────────────────────────────
            for b in active:
                b.tip += b.direction * step

            # ── Detect merges: paired branches whose XZ gap closed ───────────────
            checked_ids  = set()
            new_branches: List[_Branch] = []
            for b in list(active):
                if b.partner is None or id(b) in checked_ids:
                    continue
                p = b.partner
                if p not in active:
                    continue
                checked_ids.add(id(b))
                checked_ids.add(id(p))

                dxz = float(np.linalg.norm((b.tip - p.tip)[[0, 2]]))
                if dxz < merge_dist:
                    meet = (b.tip + p.tip) / 2.0
                    b.waypoints.append(meet.copy())
                    p.waypoints.append(meet.copy())
                    b.active = False
                    p.active = False

                    new_b = _Branch(meet, max(b.level, p.level) + 1,
                                    origin_y=max(b.origin_y, p.origin_y))
                    all_branches.append(new_b)
                    new_branches.append(new_b)

            active = [b for b in active if b.active] + new_branches

            # ── Ground collision ─────────────────────────────────────────────────
            for b in list(active):
                if b.tip[1] <= ground_y:
                    b.tip[1] = ground_y
                    b.waypoints.append(b.tip.copy())
                    b.active = False
                    # Free the partner so it can try new pairings
                    if b.partner is not None and b.partner.active:
                        b.partner.partner   = None
                        b.partner.direction = np.array([0.0, -1.0, 0.0])
                        b.partner.waypoints.append(b.partner.tip.copy())

            active = [b for b in active if b.active]
            y_cur -= step

        # Close branches still above ground
        for b in active:
            end_pt = b.tip.copy()
            end_pt[1] = ground_y
            b.waypoints.append(end_pt)

        # Convert waypoints → segments (carry origin_y for taper calculation)
        segments = []
        for b in all_branches:
            wps = b.waypoints
            for i in range(len(wps) - 1):
                s, e = wps[i], wps[i + 1]
                if np.linalg.norm(s - e) > 1e-6:
                    segments.append((s, e, b.level, b.origin_y))

        return segments

    @staticmethod
    def _buildTreeMesh(segments: List[Tuple], point_diameter: float, growth_pct: float):
        """
        Build a combined frustum (tapered cylinder) mesh for all tree support segments.

        Radius at any Y position along a branch:
            r(y) = (point_diameter + (origin_y - y) * point_diameter * growth_pct/100) / 2

        So at the contact point (y == origin_y) the branch starts at exactly
        point_diameter thickness, and grows wider as it descends.
        """
        SEG_SIDES  = 8
        factor     = point_diameter * growth_pct / 100.0   # pre-compute constant

        def radius_at(y: float, origin_y: float) -> float:
            drop = max(0.0, origin_y - y)
            return max(0.01, (point_diameter + drop * factor) / 2.0)

        all_verts = []
        all_idxs  = []

        for start, end, _level, origin_y in segments:
            d      = end - start
            length = float(np.linalg.norm(d))
            if length < 1e-6:
                continue
            d_norm = d / length

            # Orthonormal basis perpendicular to d_norm
            ref = np.array([1., 0., 0.]) if abs(d_norm[0]) < 0.9 else np.array([0., 1., 0.])
            u   = np.cross(d_norm, ref);  u /= np.linalg.norm(u)
            v   = np.cross(d_norm, u)

            r_start = radius_at(start[1], origin_y)
            r_end   = radius_at(end[1],   origin_y)

            base = len(all_verts)

            # Bottom ring at start (r_start), top ring at end (r_end)
            for ring_pt, r in ((start, r_start), (end, r_end)):
                for i in range(SEG_SIDES):
                    angle = 2.0 * math.pi * i / SEG_SIDES
                    all_verts.append(ring_pt + r * (math.cos(angle) * u + math.sin(angle) * v))

            # Side quads
            for i in range(SEG_SIDES):
                a   = base + i
                b   = base + (i + 1) % SEG_SIDES
                c   = base + SEG_SIDES + (i + 1) % SEG_SIDES
                d_i = base + SEG_SIDES + i
                all_idxs.extend([a, b, c, a, c, d_i])

            # Bottom cap (start)
            cbot = len(all_verts);  all_verts.append(start.copy())
            for i in range(SEG_SIDES):
                all_idxs.extend([cbot, base + (i + 1) % SEG_SIDES, base + i])

            # Top cap (end)
            ctop = len(all_verts);  all_verts.append(end.copy())
            for i in range(SEG_SIDES):
                all_idxs.extend([ctop, base + SEG_SIDES + i, base + SEG_SIDES + (i + 1) % SEG_SIDES])

        if not all_verts:
            return None

        builder = MeshBuilder()
        builder.setVertices(np.array(all_verts, dtype=np.float32))
        builder.setIndices(np.array(all_idxs,  dtype=np.int32).reshape(-1, 3))
        builder.calculateNormals()
        return builder.build()

    # ------------------------------------------------------------------
    # Overhang detection helpers
    # ------------------------------------------------------------------

    def _setStatus(self, msg: str):
        self._status_message = msg
        self.statusChanged.emit()
        Logger.log("d", "[OverhangSupportPlugin] %s", msg)

    def _detectOverhangFaces(self, mesh_data, transform_matrix) -> List[Tuple]:
        """
        Return a list of (v0, v1, v2) world-space triangles whose normals point
        downward beyond the configured overhang angle.
        """
        vertices = mesh_data.getVertices()
        indices  = mesh_data.getIndices()

        if vertices is None:
            return []

        mat    = transform_matrix.getData()
        ones   = np.ones((len(vertices), 1), dtype=np.float32)
        local_h = np.hstack([vertices, ones])
        world_h = local_h @ mat.T
        world_verts = world_h[:, :3]

        if indices is not None:
            idx = indices.reshape(-1, 3).astype(np.int32)
        else:
            idx = np.arange(len(world_verts)).reshape(-1, 3)

        v0 = world_verts[idx[:, 0]]
        v1 = world_verts[idx[:, 1]]
        v2 = world_verts[idx[:, 2]]

        edge1   = v1 - v0
        edge2   = v2 - v0
        normals = np.cross(edge1, edge2)
        lengths = np.linalg.norm(normals, axis=1)

        valid = lengths > 1e-10
        normals[valid] /= lengths[valid, np.newaxis]

        threshold     = -math.cos(math.radians(self._overhang_angle))
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
        Faces with a lower centroid Y get higher sampling priority.
        """
        rng = np.random.default_rng(seed=0)

        areas    = np.empty(len(overhang_faces), dtype=np.float64)
        center_y = np.empty(len(overhang_faces), dtype=np.float64)
        for i, (v0, v1, v2) in enumerate(overhang_faces):
            areas[i]    = 0.5 * np.linalg.norm(np.cross(v1 - v0, v2 - v0))
            center_y[i] = (v0[1] + v1[1] + v2[1]) / 3.0

        total_area = areas.sum()
        if total_area < 1e-6:
            return []

        num_target = max(1, int(total_area / (spacing * spacing)))
        num_target = min(num_target, 1000)

        y_min, y_max = center_y.min(), center_y.max()
        if y_max > y_min:
            lowness = (y_max - center_y) / (y_max - y_min)
        else:
            lowness = np.ones(len(overhang_faces))

        weights = areas * (lowness ** 2 + 0.05)
        weights /= weights.sum()

        points: List[np.ndarray] = []
        max_attempts = num_target * 30

        for _ in range(max_attempts):
            if len(points) >= num_target:
                break
            fi = rng.choice(len(overhang_faces), p=weights)
            v0, v1, v2 = overhang_faces[fi]
            r1 = rng.random()
            r2 = rng.random()
            if r1 + r2 > 1.0:
                r1, r2 = 1.0 - r1, 1.0 - r2
            pt = v0 + r1 * (v1 - v0) + r2 * (v2 - v0)
            if any(np.linalg.norm(pt - ex) < spacing for ex in points):
                continue
            points.append(pt)

        return points

    @staticmethod
    def _buildOverhangMesh(overhang_faces: List[Tuple], offset: float = 0.15):
        """Build a double-sided MeshData from overhang triangles (world-space coords)."""
        verts = []
        idxs  = []

        for v0, v1, v2 in overhang_faces:
            edge1 = v1 - v0
            edge2 = v2 - v0
            n     = np.cross(edge1, edge2)
            length = np.linalg.norm(n)
            n = (n / length) if length > 1e-10 else np.array([0.0, -1.0, 0.0])

            dv = n * offset
            ov0, ov1, ov2 = v0 + dv, v1 + dv, v2 + dv

            base = len(verts)
            verts.extend([ov0, ov1, ov2])
            idxs.extend([base, base + 1, base + 2])
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
            phi = math.pi * ring / rings
            for seg in range(segments):
                theta = 2.0 * math.pi * seg / segments
                verts.append([
                    radius * math.sin(phi) * math.cos(theta),
                    radius * math.cos(phi),
                    radius * math.sin(phi) * math.sin(theta),
                ])

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
