# ==============================================================================
# Module: Job điều phối pipeline sinh support
#
# Lớp MeshTreeSupportJob kế thừa UM.Job.Job, chạy trên worker thread
# (không block UI). Điều phối 2 bước tuần tự:
#
#   1. Phát hiện vùng lơ lửng (OverhangDetector)
#   2. Tạo vỏ overhang (OverhangShellBuilder)
#
# Kết quả (MeshData) được lưu trong self._result_mesh_data.
# Khi Job hoàn thành, signal finished được phát → Extension lấy kết quả.
#
# Luồng thực thi: worker thread (Cura JobQueue)
# ==============================================================================

import numpy as np

from UM.Job import Job
from UM.Logger import Logger
from UM.Mesh.MeshData import MeshData

# Import các module thuật toán của plugin
from . import OverhangDetector
from . import OverhangShellBuilder


class MeshTreeSupportJob(Job):
    """
    Job chạy nền để sinh support.

    Kế thừa UM.Job.Job → chạy trên worker thread, không block UI Cura.
    Báo tiến độ qua progress.emit() → Extension cập nhật UI.
    """

    def __init__(self, vertices, faces, settings):
        super().__init__()

        self._vertices = vertices.astype(np.float64)
        self._faces = faces.astype(np.int32)
        self._settings = settings
        self._result_mesh_data = None
        self._cancelled = False

    def requestCancel(self):
        self._cancelled = True

    def isCancelled(self):
        return self._cancelled

    def getResultMeshData(self):
        return self._result_mesh_data

    def run(self):
        Logger.log("i", "MeshTreeSupport: Bat dau sinh support...")

        s = self._settings
        vertices = self._vertices
        faces = self._faces

        try:
            self._run_pipeline(s, vertices, faces)
        except InterruptedError:
            Logger.log("i", "MeshTreeSupport: Job da bi huy.")

    def _run_pipeline(self, s, vertices, faces):

        # =====================================================================
        # BƯỚC 1: PHÁT HIỆN VÙNG LƠ LỬNG (Overhang Detection)
        # =====================================================================
        self.progress.emit(10)
        Logger.log("d", "Buoc 1/2: Phat hien vung lo lung (angle = %.1f)...",
                   s["overhang_angle"])

        overhang_points, overhang_normals, overhang_mask, all_face_normals = \
            OverhangDetector.detect_overhangs(
                vertices, faces,
                threshold_angle_deg=s["overhang_angle"],
                min_height=s["min_overhang_height"]
            )

        Logger.log("i", "  -> Tim thay %d mat lo lung", len(overhang_points))

        if self._cancelled:
            return

        if len(overhang_points) == 0:
            Logger.log("i", "MeshTreeSupport: Khong tim thay vung lo lung. Hoan tat.")
            self.progress.emit(100)
            return

        # =====================================================================
        # BƯỚC 2: TẠO VỎ OVERHANG (Overhang Shell)
        # =====================================================================
        self.progress.emit(50)
        shell_gap = float(s.get("shell_gap", 0.3))
        shell_thickness = float(s.get("shell_thickness", 0.5))

        Logger.log("d", "Buoc 2/2: Tao vo overhang (gap=%.1f, thickness=%.1f)...",
                   shell_gap, shell_thickness)

        shell_verts, shell_normals = OverhangShellBuilder.build_overhang_shell(
            vertices, faces, overhang_mask, all_face_normals,
            gap=shell_gap, thickness=shell_thickness
        )

        Logger.log("i", "  -> Vo overhang: %d dinh", len(shell_verts))

        if self._cancelled:
            return

        if shell_verts is None or len(shell_verts) == 0:
            Logger.log("w", "MeshTreeSupport: Khong tao duoc vo overhang. Hoan tat.")
            self.progress.emit(100)
            return

        # =====================================================================
        # TẠO MESH DATA TỪ VỎ OVERHANG
        # =====================================================================
        self._result_mesh_data = MeshData(
            vertices=shell_verts.astype(np.float32),
            normals=shell_normals.astype(np.float32) if shell_normals is not None else None
        )

        self.progress.emit(100)
        Logger.log("i", "MeshTreeSupport: Hoan tat! Mesh support co %d dinh.",
                   self._result_mesh_data.getVertexCount())
