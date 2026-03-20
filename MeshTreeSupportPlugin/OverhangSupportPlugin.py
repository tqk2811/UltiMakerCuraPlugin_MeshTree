# ============================================================
# OverhangSupportPlugin.py
# Plugin Cura: Phát hiện vùng Overhang & Tạo Cây Chống Đỡ
# ============================================================
# Chức năng tổng quan:
#   1. Phát hiện các mặt tam giác trên object 3D có góc nghiêng
#      vượt ngưỡng (overhang) so với phương đứng.
#   2. Hiển thị overlay màu lên các mặt overhang đó trong viewport.
#   3. Đặt các điểm chống đỡ (contact points) phân bố đều trên
#      vùng overhang bằng thuật toán Poisson-disk sampling.
#   4. Xây dựng cấu trúc cây chống đỡ (tree support) từ các điểm
#      đó, mô phỏng nhánh hội tụ từ trên xuống đất – đa luồng.
#   5. Xuất cây thành mesh 3D hình côn (frustum) có thể in được.
# ============================================================

import os
import math
import threading                        # Chạy tính toán cây trên luồng riêng, không block UI
import concurrent.futures              # Kiểm tra clearance song song trên nhiều luồng CPU
import numpy as np                     # Tính toán vector/matrix hiệu suất cao
from typing import List, Tuple, Optional

# PyQt6 – hệ thống Qt của Cura để kết nối Python ↔ QML
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, pyqtProperty

# Cura/UM API
from UM.Extension import Extension                          # Base class cho mọi Cura Extension
from UM.Application import Application                      # Singleton ứng dụng Cura
from UM.Logger import Logger                                # Ghi log debug/error
from UM.Math.Vector import Vector                           # Vector 3D (dùng cho setPosition)
from UM.Mesh.MeshBuilder import MeshBuilder                 # Tạo mesh (vertices + indices)
from UM.Scene.SceneNode import SceneNode                    # Node trong scene graph
from UM.Operations.AddSceneNodeOperation import AddSceneNodeOperation       # Thêm node (undo-able)
from UM.Operations.RemoveSceneNodeOperation import RemoveSceneNodeOperation # Xoá node (undo-able)
from UM.Operations.GroupedOperation import GroupedOperation # Nhóm nhiều operation thành một undo step
from UM.i18n import i18nCatalog
from cura.Scene.BuildPlateDecorator import BuildPlateDecorator          # Gán node vào build plate cụ thể
from cura.Scene.SliceableObjectDecorator import SliceableObjectDecorator # Đánh dấu node có thể slice
from cura.Scene.CuraSceneNode import CuraSceneNode                       # Scene node đầy đủ tính năng Cura

catalog = i18nCatalog("cura")

# ── Tag đặt cho tên node để phân biệt node của plugin với object thật ──────────
# Dùng khi duyệt scene để bỏ qua node plugin và khi xoá chỉ xoá đúng node mình tạo
_SUPPORT_NODE_TAG  = "__overhang_support_point__"   # Hình cầu hiển thị contact point
_OVERLAY_NODE_TAG  = "__overhang_overlay__"          # Lớp overlay màu vùng overhang
_TREE_NODE_TAG     = "__overhang_tree_support__"     # Mesh cây chống đỡ

# ── Key lưu setting trong Cura Preferences (preferences.cfg) ───────────────────
# Dạng "group/key" – Cura tự quản lý file lưu trữ, plugin chỉ đọc/ghi qua API
_PREF_ANGLE        = "overhang_support_visualizer/overhang_angle"
_PREF_SPACING      = "overhang_support_visualizer/point_spacing"
_PREF_DIAM         = "overhang_support_visualizer/point_diameter"
_PREF_OFFSET       = "overhang_support_visualizer/point_offset"
_PREF_SHOW_OVERLAY = "overhang_support_visualizer/show_overlay"

_PREF_TREE_ANGLE     = "overhang_support_visualizer/tree_branch_angle"
_PREF_TREE_BASE      = "overhang_support_visualizer/tree_base_dist"
_PREF_TREE_PER_LVL   = "overhang_support_visualizer/tree_dist_per_level"
_PREF_TREE_GROWTH    = "overhang_support_visualizer/tree_growth_pct"
_PREF_TREE_CLEARANCE  = "overhang_support_visualizer/tree_clearance"
_PREF_TREE_STEP       = "overhang_support_visualizer/tree_step_size"
_PREF_TREE_MERGE_DROP = "overhang_support_visualizer/tree_merge_drop"
_PREF_TREE_THREADS   = "overhang_support_visualizer/tree_thread_count"


class OverhangSupportPlugin(QObject, Extension):
    """Extension plugin that detects overhang areas and visualizes support points."""

    # ── Signals Qt – mỗi signal kết nối một thuộc tính Python với binding QML ──
    # QML lắng nghe các signal này để cập nhật UI khi giá trị thay đổi từ code
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
    treeClearanceChanged    = pyqtSignal()
    treeStepSizeChanged     = pyqtSignal()
    treeMergeDropChanged    = pyqtSignal()
    treeThreadCountChanged  = pyqtSignal()
    isGeneratingChanged     = pyqtSignal()
    _treeReady              = pyqtSignal()   # Signal nội bộ: luồng nền → luồng chính khi hoàn thành

    def __init__(self, parent=None):
        # Khởi tạo cả QObject (Qt object model) lẫn Extension (Cura plugin API)
        QObject.__init__(self, parent)
        Extension.__init__(self)

        # ── Danh sách node đang hiển thị trong scene ────────────────────────
        # Lưu lại để có thể xoá chúng sau (không thể tìm lại qua tên vì nhiều node trùng tên)
        self._support_point_nodes: List[SceneNode] = []  # Hình cầu contact point
        self._overlay_nodes:       List[SceneNode] = []  # Overlay màu overhang
        self._tree_nodes:          List[SceneNode] = []  # Mesh cây chống đỡ

        # Danh sách tọa độ contact point (numpy array) – đầu vào cho thuật toán cây
        self._contact_points:      List[np.ndarray] = []

        self._status_message = ""     # Thông điệp trạng thái hiển thị trong panel
        self._panel = None            # QML Window object (None = chưa tạo)
        self._is_generating  = False  # Cờ ngăn bấm nút Tạo cây nhiều lần đồng thời
        self._pending_mesh   = None   # Mesh tạm thời được luồng nền truyền sang luồng chính
        self._pending_status = ""     # Status tạm thời tương ứng

        # Kết nối signal nội bộ _treeReady với slot _onTreeReady trên luồng chính
        # Đây là cơ chế an toàn khi luồng nền emit signal → Qt tự dispatch về main thread
        self._treeReady.connect(self._onTreeReady)

        # ── Đọc/khởi tạo Preferences ────────────────────────────────────────
        # addPreference: đặt giá trị mặc định nếu key chưa tồn tại
        prefs = Application.getInstance().getPreferences()
        prefs.addPreference(_PREF_ANGLE,        40)    # Góc overhang mặc định 40°
        prefs.addPreference(_PREF_SPACING,       2.6)  # Khoảng cách điểm 2.6 mm
        prefs.addPreference(_PREF_DIAM,          0.3)  # Đường kính điểm 0.3 mm
        prefs.addPreference(_PREF_OFFSET,        0.15) # Dịch xuống 0.15 mm
        prefs.addPreference(_PREF_SHOW_OVERLAY, True)  # Hiển thị overlay

        prefs.addPreference(_PREF_TREE_ANGLE,    25)   # Góc nhánh 25°
        prefs.addPreference(_PREF_TREE_BASE,     25)   # Khoảng cách ghép cặp cơ bản 25 mm
        prefs.addPreference(_PREF_TREE_PER_LVL,   7)   # Tăng thêm 7 mm/cấp
        prefs.addPreference(_PREF_TREE_GROWTH,     20) # Hệ số tăng kích thước 20%
        prefs.addPreference(_PREF_TREE_CLEARANCE,   2.0) # Khoảng cách tối thiểu tới vật 2 mm
        prefs.addPreference(_PREF_TREE_STEP,        1.0) # Bước mô phỏng 1 mm
        prefs.addPreference(_PREF_TREE_MERGE_DROP, 10.0) # Đoạn thẳng sau gộp 10 mm
        prefs.addPreference(_PREF_TREE_THREADS,     0)   # 0 = tự động chọn số luồng

        # Nạp giá trị từ preferences vào thuộc tính instance
        self._overhang_angle      = int(prefs.getValue(_PREF_ANGLE))
        self._point_spacing       = round(float(prefs.getValue(_PREF_SPACING)), 2)
        self._point_diameter      = round(float(prefs.getValue(_PREF_DIAM)), 2)
        self._point_offset        = round(float(prefs.getValue(_PREF_OFFSET)), 2)
        self._show_overlay        = bool(prefs.getValue(_PREF_SHOW_OVERLAY))

        self._tree_branch_angle   = int(prefs.getValue(_PREF_TREE_ANGLE))
        self._tree_base_dist      = round(float(prefs.getValue(_PREF_TREE_BASE)), 2)
        self._tree_dist_per_level = round(float(prefs.getValue(_PREF_TREE_PER_LVL)), 2)
        self._tree_growth_pct     = round(float(prefs.getValue(_PREF_TREE_GROWTH)), 2)
        self._tree_clearance      = round(float(prefs.getValue(_PREF_TREE_CLEARANCE)), 2)
        self._tree_step_size      = round(float(prefs.getValue(_PREF_TREE_STEP)), 2)
        self._tree_merge_drop     = round(float(prefs.getValue(_PREF_TREE_MERGE_DROP)), 2)
        self._tree_thread_count   = int(prefs.getValue(_PREF_TREE_THREADS))

        # Thêm menu vào thanh Extensions của Cura
        self.setMenuName(catalog.i18nc("@item:inmenu", "Overhang Support Visualizer"))
        self.addMenuItem(catalog.i18nc("@item:inmenu", "Open Panel"), self._openPanel)

    # ------------------------------------------------------------------
    # QML properties – Contact Point Detection
    # ------------------------------------------------------------------
    # Mỗi property theo mẫu:
    #   • @pyqtProperty(type, notify=signal) → getter được QML đọc
    #   • @xxx.setter                        → setter được QML ghi khi user thay đổi SpinBox
    #   • Setter luôn clamp giá trị vào range hợp lệ, lưu vào Preferences,
    #     rồi emit signal để QML binding cập nhật UI
    # ------------------------------------------------------------------

    @pyqtProperty(int, notify=overhangAngleChanged)
    def overhangAngle(self) -> int:
        """Góc overhang (độ). Mặt có Y-normal < -cos(angle) bị coi là overhang."""
        return self._overhang_angle

    @overhangAngle.setter
    def overhangAngle(self, value: int):
        value = max(0, min(90, int(value)))  # Clamp [0, 90]
        if self._overhang_angle != value:
            self._overhang_angle = value
            Application.getInstance().getPreferences().setValue(_PREF_ANGLE, value)
            self.overhangAngleChanged.emit()

    @pyqtProperty(float, notify=pointSpacingChanged)
    def pointSpacing(self) -> float:
        """Khoảng cách tối thiểu giữa hai contact point liền nhau (mm)."""
        return self._point_spacing

    @pointSpacing.setter
    def pointSpacing(self, value: float):
        value = round(max(0.01, float(value)), 2)  # Tối thiểu 0.01 mm
        if self._point_spacing != value:
            self._point_spacing = value
            Application.getInstance().getPreferences().setValue(_PREF_SPACING, value)
            self.pointSpacingChanged.emit()

    @pyqtProperty(float, notify=pointDiameterChanged)
    def pointDiameter(self) -> float:
        """Đường kính hình cầu hiển thị contact point (mm). Cũng là đường kính gốc nhánh cây."""
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
        """Khoảng dịch contact point xuống dưới theo trục Y (mm) so với mặt overhang."""
        return self._point_offset

    @pointOffset.setter
    def pointOffset(self, value: float):
        value = round(max(0.0, float(value)), 2)  # Tối thiểu 0 (không dịch)
        if self._point_offset != value:
            self._point_offset = value
            Application.getInstance().getPreferences().setValue(_PREF_OFFSET, value)
            self.pointOffsetChanged.emit()

    @pyqtProperty(bool, notify=showOverlayChanged)
    def showOverlay(self) -> bool:
        """Nếu True, hiển thị lớp overlay màu trên vùng overhang trong viewport."""
        return self._show_overlay

    @showOverlay.setter
    def showOverlay(self, value: bool):
        value = bool(value)
        if self._show_overlay != value:
            self._show_overlay = value
            Application.getInstance().getPreferences().setValue(_PREF_SHOW_OVERLAY, value)
            # Thay đổi visibility của các overlay node hiện có ngay lập tức
            for node in self._overlay_nodes:
                node.setVisible(value)
            self.showOverlayChanged.emit()

    @pyqtProperty(str, notify=statusChanged)
    def statusMessage(self) -> str:
        """Chuỗi trạng thái hiển thị ở cuối panel (readonly từ QML)."""
        return self._status_message

    # ------------------------------------------------------------------
    # QML properties – Tree Support Parameters
    # ------------------------------------------------------------------

    @pyqtProperty(int, notify=treeBranchAngleChanged)
    def treeBranchAngle(self) -> int:
        """Góc nghiêng của nhánh khi hội tụ (° từ trục đứng). Nhỏ hơn = chậm hội tụ hơn."""
        return self._tree_branch_angle

    @treeBranchAngle.setter
    def treeBranchAngle(self, value: int):
        value = max(1, min(89, int(value)))  # Clamp [1, 89] tránh 0° (thẳng đứng) & 90° (nằm ngang)
        if self._tree_branch_angle != value:
            self._tree_branch_angle = value
            Application.getInstance().getPreferences().setValue(_PREF_TREE_ANGLE, value)
            self.treeBranchAngleChanged.emit()

    @pyqtProperty(float, notify=treeBaseDistChanged)
    def treeBaseDist(self) -> float:
        """Khoảng cách XZ tối đa để ghép cặp hai nhánh cấp 0 (mm)."""
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
        """Tăng thêm (mm) vào ngưỡng ghép cặp cho mỗi cấp cây cao hơn."""
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
        """Hệ số tăng đường kính nhánh theo chiều cao (% đường kính/mm xuống)."""
        return self._tree_growth_pct

    @treeGrowthPct.setter
    def treeGrowthPct(self, value: float):
        value = round(max(0.0, float(value)), 2)
        if self._tree_growth_pct != value:
            self._tree_growth_pct = value
            Application.getInstance().getPreferences().setValue(_PREF_TREE_GROWTH, value)
            self.treeGrowthPctChanged.emit()

    @pyqtProperty(float, notify=treeClearanceChanged)
    def treeClearance(self) -> float:
        """Khoảng cách tối thiểu từ đường đi nhánh đến bề mặt vật thể (mm)."""
        return self._tree_clearance

    @treeClearance.setter
    def treeClearance(self, value: float):
        value = round(max(0.0, float(value)), 2)
        if self._tree_clearance != value:
            self._tree_clearance = value
            Application.getInstance().getPreferences().setValue(_PREF_TREE_CLEARANCE, value)
            self.treeClearanceChanged.emit()

    @pyqtProperty(float, notify=treeStepSizeChanged)
    def treeStepSize(self) -> float:
        """Bước mô phỏng cây (mm/bước). Nhỏ hơn = chính xác hơn nhưng chậm hơn."""
        return self._tree_step_size

    @treeStepSize.setter
    def treeStepSize(self, value: float):
        value = round(max(0.1, float(value)), 2)  # Tối thiểu 0.1 mm tránh vô hạn vòng lặp
        if self._tree_step_size != value:
            self._tree_step_size = value
            Application.getInstance().getPreferences().setValue(_PREF_TREE_STEP, value)
            self.treeStepSizeChanged.emit()

    @pyqtProperty(float, notify=treeMergeDropChanged)
    def treeMergeDrop(self) -> float:
        """Số mm nhánh đi thẳng xuống sau khi gộp trước khi cho phép bẻ góc tiếp (mm)."""
        return self._tree_merge_drop

    @treeMergeDrop.setter
    def treeMergeDrop(self, value: float):
        value = round(max(0.0, float(value)), 2)
        if self._tree_merge_drop != value:
            self._tree_merge_drop = value
            Application.getInstance().getPreferences().setValue(_PREF_TREE_MERGE_DROP, value)
            self.treeMergeDropChanged.emit()

    @pyqtProperty(int, notify=treeThreadCountChanged)
    def treeThreadCount(self) -> int:
        """Số luồng CPU dùng để kiểm tra clearance. 0 = tự động (dùng toàn bộ CPU)."""
        return self._tree_thread_count

    @treeThreadCount.setter
    def treeThreadCount(self, value: int):
        value = max(0, int(value))
        if self._tree_thread_count != value:
            self._tree_thread_count = value
            Application.getInstance().getPreferences().setValue(_PREF_TREE_THREADS, value)
            self.treeThreadCountChanged.emit()

    @pyqtProperty(bool, notify=isGeneratingChanged)
    def isGenerating(self) -> bool:
        """True khi đang tính toán cây trên luồng nền. QML dùng để disable nút và hiện spinner."""
        return self._is_generating

    # ------------------------------------------------------------------
    # Panel Management
    # ------------------------------------------------------------------

    def _openPanel(self):
        """Mở cửa sổ panel QML. Tạo mới nếu chưa có, chỉ show() nếu đã tạo rồi."""
        if self._panel is None:
            # Tìm file QML cùng thư mục với file Python này
            qml_path = os.path.join(os.path.dirname(__file__), "OverhangSupportPanel.qml")
            app = Application.getInstance()
            # Tạo QML component, truyền `manager=self` để QML binding tới plugin object này
            self._panel = app.createQmlComponent(qml_path, {"manager": self})
            if self._panel:
                # Đặt cửa sổ chính làm parent để panel luôn nằm trên cửa sổ Cura
                main_window = app.getMainWindow()
                if main_window:
                    self._panel.setTransientParent(main_window)
        if self._panel:
            self._panel.show()

    # ------------------------------------------------------------------
    # Public Slots – Gọi được từ QML qua `manager.methodName()`
    # ------------------------------------------------------------------

    @pyqtSlot()
    def detectAndVisualize(self):
        """
        Phát hiện vùng overhang trên tất cả object trong scene và hiển thị:
          • Overlay mesh màu lên vùng overhang (nếu showOverlay = True)
          • Hình cầu nhỏ tại các contact point phân bố đều trên vùng overhang

        Quy trình:
          1. Xoá kết quả cũ (clearSupportPoints).
          2. Duyệt scene, bỏ qua node plugin, node không thể slice, node special mesh.
          3. Với mỗi node: phát hiện mặt overhang → tạo overlay → sample contact points.
          4. Thêm tất cả node vào scene qua một GroupedOperation (hỗ trợ Ctrl+Z).
        """
        self.clearSupportPoints()
        self._contact_points.clear()

        scene = Application.getInstance().getController().getScene()

        # Các loại mesh đặc biệt không cần hỗ trợ (Cura tự xử lý)
        _SPECIAL_MESH_KEYS = ("support_mesh", "anti_overhang_mesh", "cutting_mesh", "infill_mesh")

        # Thu thập node hợp lệ (có mesh, có thể slice, không phải node plugin, không phải special mesh)
        all_nodes = []
        for node in scene.getRoot().getAllChildren():
            if node.getMeshData() is None:
                continue
            # Bỏ qua node do chính plugin tạo ra (tránh phân tích chúng lần nữa)
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

        # Tạo sphere mesh một lần dùng chung cho tất cả contact point (tiết kiệm bộ nhớ)
        radius = self._point_diameter / 2.0
        sphere_mesh = self._buildSphereMesh(radius)

        for node in all_nodes:
            mesh_data = node.getMeshData()
            if mesh_data is None:
                continue

            self._setStatus(f"Analysing '{node.getName()}'…")

            # Bước 1: Phát hiện mặt overhang trong không gian thế giới (world space)
            overhang_faces = self._detectOverhangFaces(mesh_data, node.getWorldTransformation())
            if not overhang_faces:
                continue

            active_plate = Application.getInstance().getMultiBuildPlateModel().activeBuildPlate

            # Bước 2: Tạo overlay mesh từ các mặt overhang
            overlay = CuraSceneNode()
            overlay.setName(_OVERLAY_NODE_TAG)
            overlay.setMeshData(self._buildOverhangMesh(overhang_faces, offset=max(0.15, self._point_offset)))
            overlay.setSelectable(False)  # Không cho click chọn overlay trong viewport
            overlay.setVisible(self._show_overlay)
            overlay.addDecorator(BuildPlateDecorator(active_plate))
            overlay.addDecorator(SliceableObjectDecorator())

            # Đánh dấu overlay là support_mesh để slicer xử lý đúng
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
                # Gán extruder 1 (extruder thứ 2) cho support overlay nếu có
                overlay.callDecoration("setActiveExtruder", "1")
            except Exception:
                pass
            self._overlay_nodes.append(overlay)
            operations.append(AddSceneNodeOperation(overlay, scene.getRoot()))

            # Bước 3: Sample các contact point phân bố đều trên vùng overhang
            points = self._sampleSupportPoints(overhang_faces, float(self._point_spacing))
            total_points += len(points)

            for pt in points:
                self._contact_points.append(pt.copy())  # Lưu để dùng khi tạo cây
                # Tạo hình cầu đánh dấu vị trí contact point
                marker = SceneNode()
                marker.setName(_SUPPORT_NODE_TAG)
                marker.setMeshData(sphere_mesh)
                marker.setSelectable(False)
                # Dịch điểm xuống dưới theo point_offset để tách khỏi bề mặt
                marker.setPosition(Vector(float(pt[0]), float(pt[1]) - self._point_offset, float(pt[2])))
                self._support_point_nodes.append(marker)
                operations.append(AddSceneNodeOperation(marker, scene.getRoot()))

        if operations:
            # Đẩy tất cả operation cùng lúc → một undo step duy nhất
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
        """Xoá toàn bộ overlay và contact point marker khỏi scene."""
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
        """
        Tạo mesh cây chống đỡ từ contact points đã phát hiện.

        Chạy trên luồng nền (daemon thread) để không block UI:
          1. _buildTreeBranches() – mô phỏng nhánh hội tụ → danh sách segments (start, end, level, origin_y)
          2. _buildTreeMesh()     – chuyển segments thành frustum mesh có thể in được
          3. Emit _treeReady → Qt dispatch về main thread → _onTreeReady() thêm node vào scene

        Cơ chế an toàn đa luồng:
          • _is_generating = True ngăn bấm nút lần nữa trong khi đang tính
          • _pending_mesh và _pending_status được set trên luồng nền,
            đọc trên luồng chính sau khi signal emit đảm bảo thứ tự
        """
        if self._is_generating:
            return  # Tránh chạy song song nhiều lần
        self.clearTreeSupport()

        if not self._contact_points:
            self._setStatus("Chưa có contact points. Hãy chạy 'Phát hiện & Hiển thị' trước.")
            return

        # Xác định số luồng: 0 nghĩa tự động dùng toàn bộ CPU
        n_workers = self._tree_thread_count if self._tree_thread_count > 0 else (os.cpu_count() or 1)
        self._is_generating = True
        self.isGeneratingChanged.emit()
        self._setStatus(f"Đang tạo cây chống đỡ từ {len(self._contact_points)} điểm ({n_workers} luồng)")

        # Sao chép dữ liệu trước khi đưa sang luồng nền (tránh race condition)
        contact_points = [p.copy() for p in self._contact_points]
        scene_tris     = self._collectSceneTris()  # Tam giác scene để kiểm tra va chạm
        point_diameter = self._point_diameter
        growth_pct     = self._tree_growth_pct

        def _run():
            """Hàm chạy trên luồng nền – không được trực tiếp thao tác scene Qt."""
            try:
                segments = self._buildTreeBranches(contact_points, scene_tris, n_workers=n_workers)
                if not segments:
                    self._pending_mesh   = None
                    self._pending_status = "Không tạo được đường cây chống đỡ."
                    self._treeReady.emit()
                    return
                mesh = self._buildTreeMesh(segments, point_diameter, growth_pct)
                self._pending_mesh   = mesh
                self._pending_status = (f"Đã tạo cây chống đỡ với {len(segments)} đoạn."
                                        if mesh else "Không xây dựng được mesh cây chống đỡ.")
            except Exception as exc:
                Logger.log("e", "[OverhangSupportPlugin] generateTreeSupport error: %s", exc)
                self._pending_mesh   = None
                self._pending_status = f"Lỗi tạo cây: {exc}"
            finally:
                # Luôn emit _treeReady để reset trạng thái UI dù thành công hay lỗi
                self._treeReady.emit()

        threading.Thread(target=_run, daemon=True).start()

    def _onTreeReady(self):
        """
        Slot nhận signal _treeReady – luôn chạy trên luồng chính (Qt main thread).
        Đây là nơi duy nhất an toàn để thao tác scene sau khi luồng nền hoàn thành.
        """
        # Reset trạng thái đang tính toán trước tiên để UI phản hồi
        self._is_generating = False
        self.isGeneratingChanged.emit()

        mesh = self._pending_mesh
        self._pending_mesh = None  # Giải phóng tham chiếu

        if mesh is None:
            self._setStatus(self._pending_status)
            return

        scene        = Application.getInstance().getController().getScene()
        active_plate = Application.getInstance().getMultiBuildPlateModel().activeBuildPlate

        # Tạo CuraSceneNode cho mesh cây chống đỡ
        node = CuraSceneNode()
        node.setName(_TREE_NODE_TAG)
        node.setMeshData(mesh)
        node.setSelectable(True)  # Cho phép click chọn cây trong viewport
        node.addDecorator(BuildPlateDecorator(active_plate))
        node.addDecorator(SliceableObjectDecorator())
        self._tree_nodes.append(node)

        op = GroupedOperation()
        op.addOperation(AddSceneNodeOperation(node, scene.getRoot()))
        op.push()

        self._setStatus(self._pending_status)

    @pyqtSlot()
    def clearTreeSupport(self):
        """Xoá toàn bộ mesh cây chống đỡ khỏi scene."""
        if self._tree_nodes:
            op = GroupedOperation()
            for node in self._tree_nodes:
                if node.getParent() is not None:
                    op.addOperation(RemoveSceneNodeOperation(node))
            op.push()
        self._tree_nodes.clear()

    # ------------------------------------------------------------------
    # Tree Support Simulation – Thuật toán tạo cây
    # ------------------------------------------------------------------

    def _buildTreeBranches(self, contact_points: List[np.ndarray],
                           scene_tris: Optional[np.ndarray] = None,
                           n_workers: int = 1) -> List[Tuple]:
        """
        Mô phỏng sự phát triển của các nhánh cây từ contact points xuống đất.
        Trả về danh sách segment (start, end, level, origin_y).

        Thuật toán tổng quan (quét từ trên xuống):
          • Mỗi contact point tạo một nhánh cấp 0 đi thẳng xuống.
          • Nhánh được kích hoạt lazily khi sweep đến đúng độ cao Y của nó.
          • Ở mỗi bước sweep, các nhánh chưa ghép cặp được thử ghép cặp phân tích:
              - Tính điểm hội tụ analytically (không step-by-step) → tránh dao động
              - Kiểm tra clearance song song (ThreadPoolExecutor)
              - Cặp có dxz nhỏ nhất được ưu tiên (greedy matching)
          • Khi ghép cặp: tạo nhánh cấp+1 từ điểm hội tụ, đi thẳng xuống min_drop mm trước
          • Khi chạm đất (Y ≤ 0.01): nhánh kết thúc

        Ngưỡng ghép cặp:
            thresh = base_dist + max(level_a, level_b) * dist_per_level

        Parameters:
            contact_points: Danh sách tọa độ np.array [x, y, z]
            scene_tris:     Mảng tam giác world-space (N, 3, 3) dùng kiểm tra clearance
            n_workers:      Số luồng song song cho clearance check
        """
        if not contact_points:
            return []

        # Các hằng số được tính trước tránh tính lại trong vòng lặp
        step       = max(0.1, self._tree_step_size)
        angle_rad  = math.radians(max(1.0, min(89.0, float(self._tree_branch_angle))))
        base_dist  = max(0.01, self._tree_base_dist)
        dist_per_lvl = max(0.0, self._tree_dist_per_level)
        sin_a = math.sin(angle_rad)   # Thành phần ngang khi nhánh nghiêng
        cos_a = math.cos(angle_rad)   # Thành phần dọc khi nhánh nghiêng
        tan_a = math.tan(angle_rad)   # Dùng tính điểm hội tụ theo công thức y = dxz/(2*tan_a)
        merge_dist = step * 1.5       # Ngưỡng dxz để coi là đã hội tụ (dự phòng)

        pt_diam    = self._point_diameter
        growth_fac = pt_diam * self._tree_growth_pct / 100.0  # mm tăng đường kính per mm xuống

        def _radius_at(y: float, origin_y: float) -> float:
            """
            Bán kính nhánh tại độ cao y, với gốc nhánh ở origin_y.
            Công thức: r = (Ø_điểm + drop * growth_factor) / 2
            Trong đó drop = max(0, origin_y - y) là khoảng cách xuống từ gốc.
            """
            drop = max(0.0, origin_y - y)
            return max(0.01, (pt_diam + drop * growth_fac) / 2.0)

        # ── Lớp nội bộ _Branch – đại diện cho một nhánh cây ────────────────
        class _Branch:
            # __slots__ tăng hiệu suất bộ nhớ khi có nhiều nhánh
            __slots__ = ["tip", "level", "waypoints", "active", "origin_y", "straight_left"]

            def __init__(self, tip, level, origin_y=None, straight_left=0.0):
                self.tip          = np.array(tip, dtype=np.float64)  # Vị trí đầu nhánh hiện tại
                self.level        = level        # Cấp cây (0=nhánh gốc, tăng khi gộp)
                self.origin_y     = float(tip[1]) if origin_y is None else float(origin_y)
                self.waypoints    = [self.tip.copy()]  # Lịch sử điểm đi qua → thành segments
                self.active       = True         # False khi nhánh kết thúc (gộp hoặc chạm đất)
                self.straight_left = float(straight_left)  # Còn bao nhiêu mm đi thẳng bắt buộc

        all_branches: List[_Branch] = []

        # Sắp xếp contact points theo Y giảm dần để kích hoạt theo thứ tự sweep top→bottom
        pending = sorted(
            [np.array(p, dtype=np.float64) for p in contact_points],
            key=lambda p: -p[1]
        )

        active: List[_Branch] = []
        y_cur    = float(pending[0][1]) if pending else 0.0
        ground_y     = 0.01    # Mặt đất ảo (0.01 mm trên bàn in)
        min_meet_y   = 20.0    # Điểm hội tụ phải cao ít nhất 20 mm khỏi bàn in
        max_iters = int(y_cur / step) + 500  # Giới hạn vòng lặp tránh vô hạn

        for _ in range(max_iters):
            # ── Kích hoạt nhánh mới khi sweep đến độ cao Y của chúng ────────
            while pending and pending[0][1] >= y_cur - step * 0.01:
                b = _Branch(pending.pop(0), 0)
                all_branches.append(b)
                active.append(b)

            if not active and not pending:
                break  # Không còn nhánh nào cần xử lý

            # ── Thử ghép cặp nhánh (analytical pairing) ─────────────────────
            if len(active) >= 2:
                # Phase 1: Lọc hình học nhanh (không kiểm tra clearance)
                raw_cands = []
                n = len(active)
                for i in range(n):
                    for j in range(i + 1, n):
                        a, bb = active[i], active[j]
                        # Bỏ qua nhánh đang trong giai đoạn đi thẳng sau gộp
                        if a.straight_left > 0 or bb.straight_left > 0:
                            continue
                        # Hai nhánh phải ở độ cao gần nhau (trong vòng 4 bước)
                        if abs(a.tip[1] - bb.tip[1]) > step * 4:
                            continue
                        # Ngưỡng ghép cặp tăng theo cấp cao hơn của hai nhánh
                        eff_level = max(a.level, bb.level)
                        thresh    = base_dist + eff_level * dist_per_lvl
                        dxz = float(np.linalg.norm((a.tip - bb.tip)[[0, 2]]))
                        if dxz > thresh:
                            continue
                        # Tính điểm hội tụ Y bằng công thức giải tích
                        # meet_y = avg_y - (dxz/2) / tan(angle)
                        avg_y  = (a.tip[1] + bb.tip[1]) / 2.0
                        meet_y = avg_y - (dxz / 2.0) / tan_a
                        if meet_y < min_meet_y:
                            continue  # Hội tụ quá gần đất, bỏ qua
                        raw_cands.append((dxz, i, j, meet_y,
                                          a.tip.copy(), bb.tip.copy()))

                # Phase 2: Kiểm tra clearance song song (tốn thời gian nhất)
                if scene_tris is not None and len(scene_tris) and clearance > 0.0 and raw_cands:
                    def _check(item):
                        """Kiểm tra xem đường từ tip → meet_point có đủ clearance không."""
                        dxz_, i_, j_, my, a_tip, b_tip = item
                        mid_xz  = (a_tip[[0, 2]] + b_tip[[0, 2]]) / 2.0
                        meet_pt = np.array([mid_xz[0], my, mid_xz[1]])
                        ok = (self._segment_clearance_ok(a_tip, meet_pt, scene_tris, clearance) and
                              self._segment_clearance_ok(b_tip, meet_pt, scene_tris, clearance))
                        return item if ok else None

                    # Chạy song song tất cả candidate, thu kết quả hợp lệ
                    with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
                        results = list(pool.map(_check, raw_cands))
                    cands = [(r[0], r[1], r[2], r[3]) for r in results if r is not None]
                else:
                    cands = [(r[0], r[1], r[2], r[3]) for r in raw_cands]

                # Sắp xếp theo dxz tăng dần → ưu tiên cặp gần nhau nhất
                cands.sort()

                used = set()
                new_branches: List[_Branch] = []
                for dxz, i, j, meet_y in cands:
                    if i in used or j in used:
                        continue  # Mỗi nhánh chỉ ghép một cặp trong một vòng lặp
                    used.add(i); used.add(j)
                    a, bb = active[i], active[j]

                    # Tính điểm hội tụ trong không gian 3D
                    mid_xz  = (a.tip[[0, 2]] + bb.tip[[0, 2]]) / 2.0
                    meet_pt = np.array([mid_xz[0], meet_y, mid_xz[1]])

                    # Vector đơn vị từ a sang bb trong mặt phẳng XZ
                    xz_diff = (bb.tip - a.tip)[[0, 2]]
                    norm    = float(np.linalg.norm(xz_diff))
                    xz_d    = xz_diff / norm if norm > 1e-6 else np.array([1.0, 0.0])

                    # Ghi nhận waypoints: tip hiện tại → điểm hội tụ (tạo đoạn chéo)
                    a.waypoints.append(a.tip.copy())
                    a.waypoints.append(meet_pt.copy())
                    bb.waypoints.append(bb.tip.copy())
                    bb.waypoints.append(meet_pt.copy())
                    a.active = bb.active = False  # Đánh dấu đã gộp, dừng di chuyển

                    # Nhánh cấp ≥ 1: thêm stub ngắn đi ngược lên tại điểm hội tụ
                    # (tạo hình dạng "Y" đẹp hơn tại điểm nối)
                    for br, xz_dir_toward in ((a, xz_d), (bb, -xz_d)):
                        if br.level >= 1:
                            ext_len  = tan_a * _radius_at(br.tip[1], br.origin_y)
                            stub_dir = np.array([-xz_dir_toward[0]*sin_a, cos_a,
                                                 -xz_dir_toward[1]*sin_a])
                            up_pt    = br.tip + stub_dir * ext_len
                            stub     = _Branch(br.tip, br.level, origin_y=br.origin_y)
                            stub.waypoints = [br.tip.copy(), up_pt]
                            stub.active    = False
                            all_branches.append(stub)

                    # Tạo nhánh gộp cấp cao hơn, bắt đầu từ điểm hội tụ
                    new_b = _Branch(meet_pt, max(a.level, bb.level) + 1,
                                    origin_y=max(a.origin_y, bb.origin_y),
                                    straight_left=self._tree_merge_drop)  # Đi thẳng N mm đầu
                    all_branches.append(new_b)
                    new_branches.append(new_b)

                # Cập nhật danh sách active: bỏ đã gộp, thêm nhánh mới
                active = [b for b in active if b.active] + new_branches

            # ── Di chuyển tất cả nhánh đang hoạt động xuống một bước ────────
            for b in active:
                b.tip[1] -= step
                if b.straight_left > 0:
                    # Giảm dần straight_left khi đang trong giai đoạn đi thẳng bắt buộc
                    b.straight_left = max(0.0, b.straight_left - step)

            # ── Kiểm tra chạm đất ────────────────────────────────────────────
            for b in list(active):
                if b.tip[1] <= ground_y:
                    b.tip[1] = ground_y
                    b.waypoints.append(b.tip.copy())
                    b.active = False  # Kết thúc nhánh tại mặt đất
            active = [b for b in active if b.active]

            y_cur -= step  # Tiến sweep xuống một bước

        # Đóng các nhánh còn lại chưa chạm đất (force-land chúng)
        for b in active:
            end_pt    = b.tip.copy()
            end_pt[1] = ground_y
            b.waypoints.append(end_pt)

        # Chuyển waypoints → danh sách segments (start, end, level, origin_y)
        segments = []
        for b in all_branches:
            wps = b.waypoints
            for i in range(len(wps) - 1):
                s, e = wps[i], wps[i + 1]
                # Bỏ qua segment quá ngắn (tránh degenerate geometry)
                if np.linalg.norm(s - e) > 1e-6:
                    segments.append((s, e, b.level, b.origin_y))

        return segments

    @staticmethod
    def _buildTreeMesh(segments: List[Tuple], point_diameter: float, growth_pct: float):
        """
        Tạo mesh hình học cho cây chống đỡ từ danh sách segments.

        Mỗi segment được dựng thành một frustum (hình trụ côn có 8 cạnh):
          • 2 vòng tròn (bottom ring = start, top ring = end)
          • Side quads nối hai vòng
          • Bottom cap và top cap đóng kín hai đầu

        Bán kính tại điểm y:
            r(y) = (point_diameter + (origin_y - y) * point_diameter * growth_pct/100) / 2

        Tham số:
            segments:      List (start, end, level, origin_y) từ _buildTreeBranches
            point_diameter: Đường kính tại contact point (mm)
            growth_pct:    Hệ số tăng đường kính (% / mm xuống)
        """
        SEG_SIDES  = 8  # Số cạnh đa giác xấp xỉ hình tròn (8 đủ mịn, nhanh render)
        factor     = point_diameter * growth_pct / 100.0   # Hệ số tính trước

        def radius_at(y: float, origin_y: float) -> float:
            """Bán kính nhánh tại độ cao y, gốc nhánh tại origin_y."""
            drop = max(0.0, origin_y - y)
            return max(0.01, (point_diameter + drop * factor) / 2.0)

        all_verts = []  # Danh sách vertex (list of np.array [x, y, z])
        all_idxs  = []  # Danh sách triangle indices (list of int)

        for start, end, _level, origin_y in segments:
            d      = end - start
            length = float(np.linalg.norm(d))
            if length < 1e-6:
                continue  # Bỏ segment quá ngắn
            d_norm = d / length  # Vector đơn vị dọc theo nhánh

            # Tạo hệ trục trực chuẩn (u, v) vuông góc với d_norm
            # → dùng để tạo vòng tròn quanh trục nhánh
            ref = np.array([1., 0., 0.]) if abs(d_norm[0]) < 0.9 else np.array([0., 1., 0.])
            u   = np.cross(d_norm, ref);  u /= np.linalg.norm(u)
            v   = np.cross(d_norm, u)

            r_start = radius_at(start[1], origin_y)  # Bán kính đầu nhánh
            r_end   = radius_at(end[1],   origin_y)  # Bán kính cuối nhánh

            base = len(all_verts)  # Index đầu tiên của frustum này trong all_verts

            # Tạo hai vòng tròn vertex: ring 0 tại start, ring 1 tại end
            for ring_pt, r in ((start, r_start), (end, r_end)):
                for i in range(SEG_SIDES):
                    angle = 2.0 * math.pi * i / SEG_SIDES
                    all_verts.append(ring_pt + r * (math.cos(angle) * u + math.sin(angle) * v))

            # Side triangles: mỗi mặt bên là 2 tam giác (quad chia đôi)
            for i in range(SEG_SIDES):
                a   = base + i
                b   = base + (i + 1) % SEG_SIDES
                c   = base + SEG_SIDES + (i + 1) % SEG_SIDES
                d_i = base + SEG_SIDES + i
                all_idxs.extend([a, b, c, a, c, d_i])

            # Bottom cap: các tam giác quạt từ tâm start đến ring 0
            cbot = len(all_verts);  all_verts.append(start.copy())  # Tâm đáy
            for i in range(SEG_SIDES):
                all_idxs.extend([cbot, base + (i + 1) % SEG_SIDES, base + i])

            # Top cap: các tam giác quạt từ tâm end đến ring 1
            ctop = len(all_verts);  all_verts.append(end.copy())  # Tâm đỉnh
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
    # Scene Geometry Helpers – Thu thập tam giác từ scene
    # ------------------------------------------------------------------

    def _collectSceneTris(self) -> Optional[np.ndarray]:
        """
        Thu thập tất cả tam giác world-space từ các object có thể in trong scene.
        Trả về mảng shape (N, 3, 3): N tam giác, mỗi tam giác có 3 đỉnh [x, y, z].

        Dùng để kiểm tra clearance khi mô phỏng cây (tránh nhánh đi xuyên qua vật thể).
        Trả về None nếu không có object nào hợp lệ.
        """
        scene = Application.getInstance().getController().getScene()
        _SPECIAL = ("support_mesh", "anti_overhang_mesh", "cutting_mesh", "infill_mesh")
        all_tris = []
        for node in scene.getRoot().getAllChildren():
            md = node.getMeshData()
            if md is None:
                continue
            # Bỏ qua node của plugin và node special mesh
            if node.getName() in (_SUPPORT_NODE_TAG, _OVERLAY_NODE_TAG, _TREE_NODE_TAG):
                continue
            if not node.callDecoration("isSliceable"):
                continue
            stack = node.callDecoration("getStack")
            if stack and any(stack.getProperty(k, "value") for k in _SPECIAL):
                continue
            verts = md.getVertices()
            if verts is None:
                continue

            # Chuyển vertices từ local space → world space bằng ma trận biến đổi
            mat  = node.getWorldTransformation().getData()
            ones = np.ones((len(verts), 1), dtype=np.float32)
            wv   = (np.hstack([verts, ones]) @ mat.T)[:, :3].astype(np.float64)

            idx  = md.getIndices()
            if idx is not None:
                idx = idx.reshape(-1, 3).astype(np.int32)
            else:
                idx = np.arange(len(wv)).reshape(-1, 3)  # Fallback nếu không có indices
            all_tris.append(wv[idx])

        return np.concatenate(all_tris, axis=0) if all_tris else None

    @staticmethod
    def _point_tris_min_dist(p: np.ndarray, tris: np.ndarray) -> float:
        """
        Tính khoảng cách tối thiểu từ điểm p đến điểm gần nhất trên tập tam giác.

        Sử dụng thuật toán Ericson (closest point on triangle) vector hóa song song
        trên toàn bộ tam giác bằng numpy → hiệu suất cao hơn vòng lặp Python.

        Các vùng Voronoi của tam giác ABC:
          • 3 vùng đỉnh (A, B, C): điểm gần nhất là đỉnh
          • 3 vùng cạnh (AB, BC, CA): điểm gần nhất nằm trên cạnh
          • 1 vùng nội thất: chiếu điểm lên mặt phẳng tam giác

        Parameters:
            p:    Điểm cần đo (shape 3,)
            tris: Mảng tam giác (shape N, 3, 3)

        Returns:
            float: Khoảng cách nhỏ nhất từ p đến tập tam giác
        """
        a = tris[:, 0]; b = tris[:, 1]; c = tris[:, 2]
        ab = b - a;  ac = c - a
        ap = p - a   # broadcast: (N, 3)

        # Tích vô hướng để xác định vùng Voronoi
        d1 = np.einsum("ij,ij->i", ab, ap)
        d2 = np.einsum("ij,ij->i", ac, ap)
        bp = p - b
        d3 = np.einsum("ij,ij->i", ab, bp)
        d4 = np.einsum("ij,ij->i", ac, bp)
        cp = p - c
        d5 = np.einsum("ij,ij->i", ab, cp)
        d6 = np.einsum("ij,ij->i", ac, cp)

        N       = len(tris)
        closest = np.empty((N, 3))
        used    = np.zeros(N, dtype=bool)

        # Vùng đỉnh A: ap·AB ≤ 0 và ap·AC ≤ 0
        m = (d1 <= 0) & (d2 <= 0)
        closest[m] = a[m];  used[m] = True

        # Vùng đỉnh B: bp·AB ≥ 0 và bp·AC ≤ bp·AB
        m = ~used & (d3 >= 0) & (d4 <= d3)
        closest[m] = b[m];  used[m] = True

        # Vùng đỉnh C: cp·AC ≥ 0 và cp·AB ≤ cp·AC
        m = ~used & (d6 >= 0) & (d5 <= d6)
        closest[m] = c[m];  used[m] = True

        # Vùng cạnh AB
        vc = d1 * d4 - d3 * d2
        m  = ~used & (vc <= 0) & (d1 >= 0) & (d3 <= 0)
        if np.any(m):
            denom = d1[m] - d3[m]
            t_ab  = np.where(np.abs(denom) > 1e-10, d1[m] / denom, 0.0)
            closest[m] = a[m] + t_ab[:, np.newaxis] * ab[m]
            used[m] = True

        # Vùng cạnh AC
        vb = d5 * d2 - d1 * d6
        m  = ~used & (vb <= 0) & (d2 >= 0) & (d6 <= 0)
        if np.any(m):
            denom = d2[m] - d6[m]
            t_ac  = np.where(np.abs(denom) > 1e-10, d2[m] / denom, 0.0)
            closest[m] = a[m] + t_ac[:, np.newaxis] * ac[m]
            used[m] = True

        # Vùng cạnh BC
        va = d3 * d6 - d5 * d4
        m  = ~used & (va <= 0) & (d4 >= d3) & (d5 >= d6)
        if np.any(m):
            bc    = c - b
            denom = (d4[m] - d3[m]) + (d5[m] - d6[m])
            t_bc  = np.where(np.abs(denom) > 1e-10, (d4[m] - d3[m]) / denom, 0.0)
            closest[m] = b[m] + t_bc[:, np.newaxis] * bc[m]
            used[m] = True

        # Nội thất tam giác: chiếu điểm lên mặt phẳng (dùng normal)
        m = ~used
        if np.any(m):
            n      = np.cross(ab[m], ac[m])
            n_len  = np.linalg.norm(n, axis=1, keepdims=True)
            n_norm = n / np.where(n_len > 1e-10, n_len, 1.0)
            dot    = np.einsum("ij,ij->i", ap[m], n_norm)
            closest[m] = p - dot[:, np.newaxis] * n_norm

        return float(np.min(np.linalg.norm(closest - p, axis=1)))

    @staticmethod
    def _segment_clearance_ok(p: np.ndarray, q: np.ndarray,
                               tris: np.ndarray, min_dist: float) -> bool:
        """
        Kiểm tra xem đoạn thẳng P→Q có đủ clearance (min_dist mm) so với tập tam giác không.

        Tối ưu hóa hiệu suất:
          1. AABB pre-filter: loại tam giác có bounding box không overlap với
             capsule quanh đoạn (AABB mở rộng min_dist theo mọi hướng)
          2. Sample count tối đa 8 điểm trên đoạn để tránh O(length/clearance)
             khi đoạn dài và clearance nhỏ

        Parameters:
            p, q:      Điểm đầu và cuối đoạn thẳng
            tris:      Mảng tam giác world-space (N, 3, 3)
            min_dist:  Khoảng cách tối thiểu cho phép (mm)

        Returns:
            True nếu đoạn đủ xa mọi tam giác, False nếu vi phạm clearance
        """
        seg_len = float(np.linalg.norm(q - p))
        if seg_len < 1e-6:
            return True  # Segment quá ngắn, bỏ qua

        # ── AABB pre-filter ──────────────────────────────────────────────────
        # Chỉ xét tam giác có bounding box giao với "ống" bao quanh segment
        seg_min = np.minimum(p, q) - min_dist
        seg_max = np.maximum(p, q) + min_dist
        tri_min = tris.min(axis=1)   # (N, 3) – góc nhỏ AABB từng tam giác
        tri_max = tris.max(axis=1)   # (N, 3) – góc lớn AABB từng tam giác
        mask    = (np.all(tri_min <= seg_max, axis=1) &
                   np.all(tri_max >= seg_min, axis=1))
        nearby  = tris[mask]
        if len(nearby) == 0:
            return True   # Không có tam giác gần, đoạn an toàn

        # ── Sample segment (tối đa 8 điểm) ──────────────────────────────────
        n_samples = min(8, max(3,
                        int(math.ceil(seg_len / max(0.01, min_dist / 2.0))) + 1))
        d = q - p
        for t in np.linspace(0.0, 1.0, n_samples):
            # Với mỗi điểm sample, tính khoảng cách đến tam giác gần nhất
            if OverhangSupportPlugin._point_tris_min_dist(p + t * d, nearby) < min_dist:
                return False  # Vi phạm clearance
        return True

    # ------------------------------------------------------------------
    # Overhang Detection Helpers – Phát hiện vùng overhang
    # ------------------------------------------------------------------

    def _setStatus(self, msg: str):
        """Cập nhật thông điệp trạng thái và emit signal để QML binding refresh."""
        self._status_message = msg
        self.statusChanged.emit()
        Logger.log("d", "[OverhangSupportPlugin] %s", msg)

    def _detectOverhangFaces(self, mesh_data, transform_matrix) -> List[Tuple]:
        """
        Phát hiện các mặt tam giác có góc overhang vượt ngưỡng.

        Một mặt bị coi là overhang khi:
            normal_y < -cos(overhang_angle)
        Nghĩa là normal của mặt hướng đủ xuống dưới (Y âm).

        Quy trình:
          1. Biến đổi vertices từ local space → world space (nhân ma trận biến đổi 4×4)
          2. Tính normal của từng tam giác bằng cross product (edge1 × edge2)
          3. Normalize normals và so sánh thành phần Y với ngưỡng

        Parameters:
            mesh_data:        UM.Mesh.MeshData – dữ liệu mesh của node
            transform_matrix: Ma trận world transformation 4×4

        Returns:
            List of (v0, v1, v2) world-space vertex tuples cho các mặt overhang
        """
        vertices = mesh_data.getVertices()
        indices  = mesh_data.getIndices()

        if vertices is None:
            return []

        # Chuyển vertices sang world space: [x, y, z] → [x, y, z, 1] @ mat.T → [x', y', z']
        mat    = transform_matrix.getData()
        ones   = np.ones((len(vertices), 1), dtype=np.float32)
        local_h = np.hstack([vertices, ones])   # (N, 4) homogeneous
        world_h = local_h @ mat.T               # (N, 4) world homogeneous
        world_verts = world_h[:, :3]            # (N, 3) drop w

        # Lấy indices tam giác; nếu không có thì mỗi 3 vertex liên tiếp = 1 tam giác
        if indices is not None:
            idx = indices.reshape(-1, 3).astype(np.int32)
        else:
            idx = np.arange(len(world_verts)).reshape(-1, 3)

        # Tách 3 đỉnh của mỗi tam giác
        v0 = world_verts[idx[:, 0]]
        v1 = world_verts[idx[:, 1]]
        v2 = world_verts[idx[:, 2]]

        # Tính normal bằng cross product (chưa normalize)
        edge1   = v1 - v0
        edge2   = v2 - v0
        normals = np.cross(edge1, edge2)   # (M, 3)
        lengths = np.linalg.norm(normals, axis=1)

        # Normalize normal (bỏ qua tam giác degenerate có diện tích ≈ 0)
        valid = lengths > 1e-10
        normals[valid] /= lengths[valid, np.newaxis]

        # Ngưỡng: normal_y < -cos(angle) → hướng xuống nhiều hơn góc overhang
        threshold     = -math.cos(math.radians(self._overhang_angle))
        overhang_mask = valid & (normals[:, 1] < threshold)

        # Trả về danh sách tuple (v0, v1, v2) cho các mặt overhang
        oi = np.where(overhang_mask)[0]
        return list(zip(v0[oi], v1[oi], v2[oi]))

    def _sampleSupportPoints(
        self,
        overhang_faces: List[Tuple],
        spacing: float
    ) -> List[np.ndarray]:
        """
        Phân bố các contact point trên vùng overhang bằng area-weighted Poisson-disk sampling.

        Thuật toán:
          1. Tính diện tích và trung tâm Y của từng mặt
          2. Tạo trọng số = diện_tích × (lowness² + 0.05)
             (lowness cao = mặt thấp = cần chống đỡ hơn → ưu tiên cao hơn)
          3. Sample ngẫu nhiên có trọng số, loại điểm quá gần nhau (Poisson-disk filter)

        Giới hạn:
          • Tối đa 1000 điểm để tránh quá tải scene
          • Tối đa num_target × 30 lần thử để đảm bảo kết thúc

        Parameters:
            overhang_faces: List (v0, v1, v2) world-space triangles
            spacing:        Khoảng cách tối thiểu giữa hai điểm (mm)

        Returns:
            List[np.ndarray]: Danh sách tọa độ contact point [x, y, z]
        """
        rng = np.random.default_rng(seed=0)  # Seed cố định → kết quả tái lập (reproducible)

        areas    = np.empty(len(overhang_faces), dtype=np.float64)
        center_y = np.empty(len(overhang_faces), dtype=np.float64)
        for i, (v0, v1, v2) in enumerate(overhang_faces):
            # Diện tích = 0.5 × |cross(v1-v0, v2-v0)|
            areas[i]    = 0.5 * np.linalg.norm(np.cross(v1 - v0, v2 - v0))
            center_y[i] = (v0[1] + v1[1] + v2[1]) / 3.0  # Tâm Y của tam giác

        total_area = areas.sum()
        if total_area < 1e-6:
            return []

        # Ước tính số điểm cần = tổng diện tích / (spacing²)
        num_target = max(1, int(total_area / (spacing * spacing)))
        num_target = min(num_target, 1000)  # Giới hạn 1000 điểm

        # Tính "lowness" – mặt càng thấp càng có lowness cao → ưu tiên chống đỡ
        y_min, y_max = center_y.min(), center_y.max()
        if y_max > y_min:
            lowness = (y_max - center_y) / (y_max - y_min)
        else:
            lowness = np.ones(len(overhang_faces))

        # Trọng số sampling: ưu tiên mặt lớn và mặt thấp
        weights = areas * (lowness ** 2 + 0.05)  # +0.05 tránh weight = 0
        weights /= weights.sum()  # Normalize thành phân phối xác suất

        points: List[np.ndarray] = []
        max_attempts = num_target * 30  # Giới hạn vòng lặp

        for _ in range(max_attempts):
            if len(points) >= num_target:
                break
            # Chọn ngẫu nhiên tam giác theo trọng số
            fi = rng.choice(len(overhang_faces), p=weights)
            v0, v1, v2 = overhang_faces[fi]
            # Lấy điểm ngẫu nhiên đồng đều bên trong tam giác
            # (phương pháp gương: đảm bảo r1+r2 ≤ 1)
            r1 = rng.random()
            r2 = rng.random()
            if r1 + r2 > 1.0:
                r1, r2 = 1.0 - r1, 1.0 - r2
            pt = v0 + r1 * (v1 - v0) + r2 * (v2 - v0)
            # Poisson-disk filter: bỏ qua nếu quá gần điểm đã có
            if any(np.linalg.norm(pt - ex) < spacing for ex in points):
                continue
            points.append(pt)

        return points

    @staticmethod
    def _buildOverhangMesh(overhang_faces: List[Tuple], offset: float = 0.15):
        """
        Tạo mesh hiển thị vùng overhang (overlay) trong viewport.

        Mỗi tam giác overhang được dịch theo hướng normal × offset mm để tách khỏi
        bề mặt gốc và tránh z-fighting. Mesh double-sided (cả hai mặt) để nhìn được
        từ mọi góc.

        Parameters:
            overhang_faces: List (v0, v1, v2) world-space triangles
            offset:         Khoảng dịch ra khỏi bề mặt (mm), mặc định 0.15

        Returns:
            UM.Mesh.MeshData object
        """
        verts = []
        idxs  = []

        for v0, v1, v2 in overhang_faces:
            # Tính normal của tam giác
            edge1 = v1 - v0
            edge2 = v2 - v0
            n     = np.cross(edge1, edge2)
            length = np.linalg.norm(n)
            n = (n / length) if length > 1e-10 else np.array([0.0, -1.0, 0.0])

            # Dịch toàn bộ tam giác theo hướng normal
            dv = n * offset
            ov0, ov1, ov2 = v0 + dv, v1 + dv, v2 + dv

            base = len(verts)
            verts.extend([ov0, ov1, ov2])
            # Front face (theo hướng normal)
            idxs.extend([base, base + 1, base + 2])
            # Back face (ngược lại để nhìn được từ cả hai phía)
            idxs.extend([base, base + 2, base + 1])

        builder = MeshBuilder()
        builder.setVertices(np.array(verts, dtype=np.float32))
        builder.setIndices(np.array(idxs, dtype=np.int32).reshape(-1, 3))
        builder.calculateNormals()
        return builder.build()

    @staticmethod
    def _buildSphereMesh(radius: float, segments: int = 16, rings: int = 10):
        """
        Tạo mesh hình cầu UV-sphere để hiển thị contact point trong viewport.

        Cấu trúc UV-sphere:
          • rings + 1 vòng ngang (từ cực bắc đến cực nam)
          • segments điểm trên mỗi vòng
          • Mỗi ô lưới = 2 tam giác (quad chia đôi)

        Công thức vertex:
            x = radius × sin(phi) × cos(theta)
            y = radius × cos(phi)              ← trục Y lên trên
            z = radius × sin(phi) × sin(theta)

        Parameters:
            radius:   Bán kính hình cầu (mm)
            segments: Số điểm theo kinh tuyến (mặc định 16)
            rings:    Số vòng theo vĩ tuyến (mặc định 10)

        Returns:
            UM.Mesh.MeshData object
        """
        verts = []
        # Tạo vertices theo lưới (rings+1) × segments
        for ring in range(rings + 1):
            phi = math.pi * ring / rings          # 0 → π (bắc → nam)
            for seg in range(segments):
                theta = 2.0 * math.pi * seg / segments  # 0 → 2π
                verts.append([
                    radius * math.sin(phi) * math.cos(theta),
                    radius * math.cos(phi),
                    radius * math.sin(phi) * math.sin(theta),
                ])

        # Tạo indices bằng cách nối 4 điểm liền kề thành 2 tam giác
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
