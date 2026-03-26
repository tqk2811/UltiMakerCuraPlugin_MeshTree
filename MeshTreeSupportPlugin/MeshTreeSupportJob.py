# ==============================================================================
# Module: Job điều phối pipeline sinh support
#
# Lớp MeshTreeSupportJob kế thừa UM.Job.Job, chạy trên worker thread
# (không block UI). Điều phối 4 bước tuần tự:
#
#   1. Phát hiện vùng lơ lửng (OverhangDetector)
#   2. Tạo vỏ overhang (OverhangShellBuilder)
#   3. Xây dựng trường va chạm SDF (CollisionAvoider)
#   4. Lọc tip points theo SDF
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
from .CollisionAvoider import CollisionField


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
        self.progress.emit(5)
        Logger.log("d", "Buoc 1/4: Phat hien vung lo lung (angle = %.1f)...",
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
        self.progress.emit(15)
        shell_gap = float(s.get("shell_gap", 0.3))
        shell_thickness = float(s.get("shell_thickness", 0.5))

        Logger.log("d", "Buoc 2/4: Tao vo overhang (gap=%.1f, thickness=%.1f)...",
                   shell_gap, shell_thickness)

        shell_verts, shell_normals = OverhangShellBuilder.build_overhang_shell(
            vertices, faces, overhang_mask, all_face_normals,
            gap=shell_gap, thickness=shell_thickness
        )

        Logger.log("i", "  -> Vo overhang: %d dinh", len(shell_verts))

        if self._cancelled:
            return

        # =====================================================================
        # BƯỚC 3: XÂY DỰNG TRƯỜNG VA CHẠM (Collision Field)
        # Thuật toán: BVH + SDF Grid + multiprocessing.Pool
        # Đầu vào: mesh (vertices, faces)
        # Đầu ra: CollisionField (tra cứu khoảng cách + gradient O(1))
        # =====================================================================
        self.progress.emit(20)
        Logger.log("d", "Buoc 3/4: Xay dung truong va cham SDF "
                   "(resolution = %.1fmm)...", s["sdf_resolution"])

        collision_field = CollisionField.build(
            vertices, faces,
            resolution=s["sdf_resolution"],
            padding=s["sdf_padding"],
            cancel_check=self.isCancelled
        )

        Logger.log("i", "  -> Truong va cham SDF da san sang")

        if self._cancelled:
            return

        # =====================================================================
        # BƯỚC 4: LỌC TIP POINTS KHÔNG ĐỦ KHÔNG GIAN
        # Kiểm tra SDF tại mỗi tip point (trọng tâm overhang).
        # Nếu SDF < 0 → tip nằm bên trong vật thể → loại bỏ.
        # =====================================================================
        self.progress.emit(80)

        tip_points = overhang_points.copy()
        tip_normals = overhang_normals.copy()

        clearance_threshold = 0.0
        valid_mask = np.ones(len(tip_points), dtype=bool)
        for i, tp in enumerate(tip_points):
            dist = collision_field.get_distance(tp)
            if dist < clearance_threshold:
                valid_mask[i] = False

        removed_count = int(np.sum(~valid_mask))
        if removed_count > 0:
            tip_points = tip_points[valid_mask]
            tip_normals = tip_normals[valid_mask]
            Logger.log("i", "  -> Loai %d tip point khong du khong gian (SDF < %.1fmm), con lai %d",
                       removed_count, clearance_threshold, len(tip_points))

        Logger.log("i", "  -> %d tip points sau loc", len(tip_points))

        if self._cancelled:
            return

        # =====================================================================
        # TẠO MESH DATA TỪ VỎ OVERHANG
        # =====================================================================
        if shell_verts is None or len(shell_verts) == 0:
            Logger.log("w", "MeshTreeSupport: Khong tao duoc vo overhang. Hoan tat.")
            self.progress.emit(100)
            return

        self._result_mesh_data = MeshData(
            vertices=shell_verts.astype(np.float32),
            normals=shell_normals.astype(np.float32) if shell_normals is not None else None
        )

        self.progress.emit(100)
        Logger.log("i", "MeshTreeSupport: Hoan tat! Mesh support co %d dinh.",
                   self._result_mesh_data.getVertexCount())
