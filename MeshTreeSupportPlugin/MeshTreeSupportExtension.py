# Copyright (c) 2024 tqk2811
# MeshTreeSupportExtension - Extension Plugin cho UltiMaker Cura 5.x
#
# Tính mật độ cột tree support theo công thức:
#   số cột = tổng diện tích overhang / diện tích mỗi cột
# Từ đó suy ra tip_diameter và branch_diameter để set vào Cura trước khi slice.
#
# Cài đặt:
#   Đặt thư mục MeshTreeSupportPlugin/ vào:
#   Windows: %appdata%\cura\<version>\plugins\MeshTreeSupportPlugin\
#   macOS:   ~/Library/Application Support/cura/<version>/plugins/MeshTreeSupportPlugin/
#   Linux:   ~/.local/share/cura/<version>/plugins/MeshTreeSupportPlugin/

import math

import numpy as np
from UM.Extension import Extension
from UM.Logger import Logger
from cura.CuraApplication import CuraApplication

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
        QLabel, QDoubleSpinBox, QPushButton, QCheckBox, QSizePolicy,
    )
except ImportError:
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
        QLabel, QDoubleSpinBox, QPushButton, QCheckBox, QSizePolicy,
    )


# ─── Các key settings tree support trong Cura ────────────────────────────────
KEY_SUPPORT_ENABLE        = "support_enable"
KEY_SUPPORT_STRUCTURE     = "support_structure"
KEY_TIP_DIAMETER          = "support_tree_tip_diameter"
KEY_BRANCH_DIAMETER       = "support_tree_branch_diameter"
KEY_BRANCH_DIAMETER_ANGLE = "support_tree_branch_diameter_angle"
KEY_COLLISION_RESOLUTION  = "support_tree_collision_resolution"


class MeshTreeSupportExtension(Extension):
    """
    Extension Plugin: mở cửa sổ tính toán và đặt cài đặt tree support
    trước khi người dùng nhấn Slice.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setMenuName("Mesh Tree Support")
        self.addMenuItem("Cấu hình mật độ cột…", self._open_dialog)
        self._dialog: "ColumnDensityDialog | None" = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def open_dialog(self) -> None:
        self._open_dialog()

    def compute_overhang_area(self, overhang_angle_deg: float = 45.0) -> float:
        """
        Duyệt toàn bộ mesh trong scene, tính tổng diện tích projected (XY)
        của các mặt tam giác có hướng xuống quá ngưỡng overhang_angle_deg.

        Trả về diện tích (mm²).
        """
        # cos của góc giới hạn giữa normal mặt tam giác và vector -Z
        # normal.z < -threshold  →  mặt hướng xuống đủ để cần support
        threshold = math.cos(math.radians(90.0 - overhang_angle_deg))
        total_area = 0.0

        scene = CuraApplication.getInstance().getController().getScene()
        nodes = self._collect_mesh_nodes(scene.getRoot())

        for node in nodes:
            mesh = node.getMeshData()
            if mesh is None:
                continue

            verts_local = mesh.getVertices()  # (N, 3) float32
            if verts_local is None or len(verts_local) == 0:
                continue

            # Đưa vertices về world space (có cả scale/rotate)
            tf = node.getWorldTransformation().getData()  # 4×4 numpy array
            ones = np.ones((len(verts_local), 1), dtype=np.float64)
            v_h = np.hstack([verts_local.astype(np.float64), ones])  # (N,4)
            v_world = (tf @ v_h.T).T[:, :3]                          # (N,3)

            indices = mesh.getIndices()
            if indices is not None:
                v0 = v_world[indices[:, 0]]
                v1 = v_world[indices[:, 1]]
                v2 = v_world[indices[:, 2]]
            else:
                # Không có index buffer — assume mỗi 3 vertex liên tiếp = 1 tam giác
                n = (len(v_world) // 3) * 3
                v0 = v_world[:n:3]
                v1 = v_world[1:n:3]
                v2 = v_world[2:n:3]

            e1 = v1 - v0
            e2 = v2 - v0
            cross = np.cross(e1, e2)                        # (M, 3)
            lengths = np.linalg.norm(cross, axis=1)         # (M,)

            valid = lengths > 1e-10
            normals = np.zeros_like(cross)
            normals[valid] = cross[valid] / lengths[valid, np.newaxis]

            # dot với (0,0,-1) → âm của normal.z
            down_dot = -normals[:, 2]
            overhang_mask = valid & (down_dot > threshold)

            if overhang_mask.any():
                area_3d = lengths[overhang_mask] / 2.0          # diện tích tam giác
                projected = area_3d * down_dot[overhang_mask]   # chiếu lên mặt phẳng XY
                total_area += float(projected.sum())

        return total_area

    def apply_settings(self, column_section_area: float, tip_branch_ratio: float = 0.45) -> dict:
        """
        Tính tip_diameter từ diện tích tiết diện cột rồi áp dụng vào GlobalStack của Cura.

        column_section_area : mm² tiết diện của chính cột chống
        tip_branch_ratio    : tip_d / branch_d  (mặc định 0.45, nhỏ hơn = đầu nhọn hơn)

        Trả về dict các setting đã được apply thành công.
        """
        # Diện tích tiết diện cột = π * (tip_d/2)²  →  tip_d = 2√(A/π)
        tip_d = 2.0 * math.sqrt(column_section_area / math.pi)
        tip_d = round(max(0.2, min(tip_d, 5.0)), 3)

        branch_d = round(max(tip_d / tip_branch_ratio, 1.0), 3)
        branch_d = min(branch_d, 20.0)

        to_set = {
            KEY_SUPPORT_ENABLE:    True,
            KEY_SUPPORT_STRUCTURE: "tree",
            KEY_TIP_DIAMETER:      tip_d,
            KEY_BRANCH_DIAMETER:   branch_d,
        }

        stack = CuraApplication.getInstance().getMachineManager().activeMachine
        if stack is None:
            Logger.log("w", "[MeshTreeSupport] Không tìm thấy activeMachine")
            return {}

        applied = {}
        for key, val in to_set.items():
            try:
                stack.setProperty(key, "value", val)
                applied[key] = val
                Logger.log("d", f"[MeshTreeSupport] set {key} = {val}")
            except Exception as exc:
                Logger.log("w", f"[MeshTreeSupport] Không set được {key}: {exc}")

        return applied

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _open_dialog(self) -> None:
        if self._dialog is None:
            self._dialog = ColumnDensityDialog(self)
        self._dialog.refresh_area()
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()

    @staticmethod
    def _collect_mesh_nodes(root) -> list:
        """Duyệt cây scene, lấy tất cả node có getMeshData."""
        result = []
        stack = list(root.getChildren())
        while stack:
            node = stack.pop()
            if callable(getattr(node, "getMeshData", None)):
                result.append(node)
            stack.extend(node.getChildren())
        return result


# ─── Dialog UI ────────────────────────────────────────────────────────────────

class ColumnDensityDialog(QDialog):

    def __init__(self, ext: MeshTreeSupportExtension) -> None:
        super().__init__()
        self._ext = ext
        self._overhang_area: float = 0.0
        self.setWindowTitle("Mesh Tree Support — Mật độ cột")
        self.setMinimumWidth(400)
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint
        )
        self._build_ui()

    # ── Build UI ───────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ── Nhóm 1: Thông số đầu vào ─────────────────────────────────────────
        grp_input = QGroupBox("Thông số đầu vào")
        form = QFormLayout(grp_input)

        # --- Diện tích vùng bao phủ (để tính SỐ CỘT) ---
        self._spin_coverage = QDoubleSpinBox()
        self._spin_coverage.setRange(1.0, 10000.0)
        self._spin_coverage.setValue(80.0)
        self._spin_coverage.setSuffix(" mm²")
        self._spin_coverage.setDecimals(1)
        self._spin_coverage.setToolTip(
            "Mỗi cột chống sẽ hỗ trợ cho vùng diện tích này.\n"
            "Ví dụ: 80 mm² = 1 cột đỡ vùng ~10×8mm.\n"
            "Nhỏ hơn → cần nhiều cột hơn.\n"
            "Dùng để tính: số cột = diện tích overhang / giá trị này."
        )
        self._spin_coverage.valueChanged.connect(self._update_preview)
        form.addRow("Vùng bao phủ mỗi cột:", self._spin_coverage)

        # --- Diện tích tiết diện CỘT (để tính KÍCH THƯỚC cột) ---
        self._spin_col_section = QDoubleSpinBox()
        self._spin_col_section.setRange(0.5, 500.0)
        self._spin_col_section.setValue(10.0)
        self._spin_col_section.setSuffix(" mm²")
        self._spin_col_section.setDecimals(1)
        self._spin_col_section.setToolTip(
            "Diện tích tiết diện ngang của chính cột chống.\n"
            "Ví dụ: 10 mm² ≈ cột tròn đường kính ~3.57mm.\n"
            "Dùng để tính tip_diameter và branch_diameter."
        )
        self._spin_col_section.valueChanged.connect(self._update_preview)
        form.addRow("Tiết diện cột chống:", self._spin_col_section)

        # --- Góc overhang ---
        self._spin_overhang_angle = QDoubleSpinBox()
        self._spin_overhang_angle.setRange(0.0, 89.0)
        self._spin_overhang_angle.setValue(45.0)
        self._spin_overhang_angle.setSuffix("°")
        self._spin_overhang_angle.setDecimals(0)
        self._spin_overhang_angle.setToolTip(
            "Góc tối thiểu để một mặt được coi là overhang.\n"
            "Thường dùng 45° (mặc định Cura)."
        )
        form.addRow("Góc overhang:", self._spin_overhang_angle)

        # --- Tip/Branch ratio ---
        self._spin_ratio = QDoubleSpinBox()
        self._spin_ratio.setRange(0.1, 0.9)
        self._spin_ratio.setValue(0.45)
        self._spin_ratio.setDecimals(2)
        self._spin_ratio.setSingleStep(0.05)
        self._spin_ratio.setToolTip(
            "Tỷ lệ đường kính đầu tip / đường kính thân cột.\n"
            "Nhỏ hơn → đầu nhọn hơn, dễ tách khỏi model hơn."
        )
        self._spin_ratio.valueChanged.connect(self._update_preview)
        form.addRow("Tip / Branch ratio:", self._spin_ratio)

        root.addWidget(grp_input)

        # ── Nhóm 2: Kết quả tính toán ─────────────────────────────────────────
        grp_result = QGroupBox("Kết quả tính toán")
        info = QFormLayout(grp_result)

        self._lbl_overhang  = QLabel("—")
        self._lbl_count     = QLabel("—")
        self._lbl_tip       = QLabel("—")
        self._lbl_branch    = QLabel("—")

        info.addRow("Diện tích overhang:",  self._lbl_overhang)
        info.addRow("Số cột ước tính:",     self._lbl_count)
        info.addRow("Tip diameter:",        self._lbl_tip)
        info.addRow("Branch diameter:",     self._lbl_branch)

        root.addWidget(grp_result)

        # ── Buttons ────────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()

        btn_calc = QPushButton("Tính lại diện tích")
        btn_calc.setToolTip("Quét lại mesh trong scene để tính diện tích overhang.")
        btn_calc.clicked.connect(self.refresh_area)
        btn_row.addWidget(btn_calc)

        btn_apply = QPushButton("✓ Áp dụng")
        btn_apply.setDefault(True)
        btn_apply.setToolTip("Đặt tip_diameter và branch_diameter vào Cura, sau đó slice bình thường.")
        btn_apply.clicked.connect(self._on_apply)
        btn_row.addWidget(btn_apply)

        btn_close = QPushButton("Đóng")
        btn_close.clicked.connect(self.hide)
        btn_row.addWidget(btn_close)

        root.addLayout(btn_row)

        # Status bar nhỏ
        self._lbl_status = QLabel("")
        self._lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._lbl_status)

    # ── Slots ──────────────────────────────────────────────────────────────────

    def refresh_area(self) -> None:
        """Tính lại diện tích overhang từ scene, cập nhật UI."""
        self._lbl_status.setText("Đang tính diện tích overhang…")
        self.repaint()
        try:
            angle = self._spin_overhang_angle.value()
            self._overhang_area = self._ext.compute_overhang_area(angle)
            self._lbl_status.setText("")
        except Exception as exc:
            Logger.log("e", f"[MeshTreeSupport] compute_overhang_area: {exc}")
            self._overhang_area = 0.0
            self._lbl_status.setText(f"Lỗi: {exc}")
        self._update_preview()

    def _update_preview(self) -> None:
        """Cập nhật các nhãn kết quả mà không thay đổi Cura settings."""
        coverage    = self._spin_coverage.value()      # vùng bao phủ → tính số cột
        col_section = self._spin_col_section.value()   # tiết diện cột → tính tip_d
        ratio       = self._spin_ratio.value()

        # Số cột = diện tích overhang / diện tích vùng bao phủ mỗi cột
        count = (
            math.ceil(self._overhang_area / coverage)
            if coverage > 0 and self._overhang_area > 0
            else 0
        )

        # Kích thước cột từ diện tích tiết diện
        tip_d    = 2.0 * math.sqrt(col_section / math.pi)
        tip_d    = max(0.2, min(tip_d, 5.0))
        branch_d = max(tip_d / ratio, 1.0)
        branch_d = min(branch_d, 20.0)

        self._lbl_overhang.setText(f"{self._overhang_area:.1f} mm²")
        self._lbl_count.setText(   f"~{count} cột")
        self._lbl_tip.setText(     f"{tip_d:.3f} mm")
        self._lbl_branch.setText(  f"{branch_d:.3f} mm")

    def _on_apply(self) -> None:
        col_section = self._spin_col_section.value()
        ratio       = self._spin_ratio.value()
        applied     = self._ext.apply_settings(col_section, ratio)

        if applied:
            tip    = applied.get(KEY_TIP_DIAMETER,    "?")
            branch = applied.get(KEY_BRANCH_DIAMETER, "?")
            self._lbl_status.setText(
                f"Đã áp dụng: tip={tip} mm, branch={branch} mm  →  slice để xem kết quả."
            )
        else:
            self._lbl_status.setText("Không áp dụng được — kiểm tra máy in đang hoạt động.")
