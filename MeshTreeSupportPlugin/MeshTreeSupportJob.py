# ==============================================================================
# Module: Job điều phối pipeline sinh support
#
# Lớp MeshTreeSupportJob kế thừa UM.Job.Job, chạy trên worker thread
# (không block UI). Điều phối 8 bước tuần tự:
#
#   1. Phát hiện vùng lơ lửng (OverhangDetector)
#   2. Tạo vỏ overhang (OverhangShellBuilder)
#   3. Xây dựng trường va chạm SDF (CollisionAvoider)
#   4. Loại bỏ tam giác shell va chạm
#   5. Xử lý đa giác (merge/split) (PolygonProcessor)
#   6. Tạo tip interface (TipInterfaceBuilder)
#   7. Mô phỏng nhánh cây (BranchRouter - Space Colonization)
#   8. Tạo mesh nhánh (TreeMeshBuilder - Frustum + Bézier bends)
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
from .PolygonProcessor import process_polygons
from .TipInterfaceBuilder import build_tip_interfaces
from . import BranchRouter
from . import TreeMeshBuilder


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
        self._result_shell_mesh_data = None
        self._cancelled = False

    def requestCancel(self):
        self._cancelled = True

    def isCancelled(self):
        return self._cancelled

    def getResultMeshData(self):
        return self._result_mesh_data

    def getResultShellMeshData(self):
        return self._result_shell_mesh_data

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
        self.progress.emit(3)
        Logger.log("d", "Buoc 1/8: Phat hien vung lo lung (angle = %.1f)...",
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
        self.progress.emit(8)
        shell_gap = float(s.get("shell_gap", 0.3))
        shell_thickness = float(s.get("shell_thickness", 0.5))

        Logger.log("d", "Buoc 2/8: Tao vo overhang (gap=%.1f, thickness=%.1f)...",
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
        # =====================================================================
        self.progress.emit(12)
        Logger.log("d", "Buoc 3/8: Xay dung truong va cham SDF "
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
        # BƯỚC 4: LOẠI BỎ TAM GIÁC SHELL VA CHẠM VỚI VẬT THỂ
        # =====================================================================
        self.progress.emit(25)
        Logger.log("d", "Buoc 4/8: Loai bo tam giac shell va cham...")

        num_tris = len(shell_verts) // 3
        if num_tris > 0:
            # Batch SDF check
            dists = collision_field.get_distances_batch(
                shell_verts.astype(np.float64)
            )
            # Reshape thành (num_tris, 3) — 3 đỉnh mỗi tam giác
            dists_per_tri = dists.reshape(num_tris, 3)
            # Tam giác safe = tất cả 3 đỉnh có SDF >= 0
            safe_mask = np.all(dists_per_tri >= 0, axis=1)

            removed = int(np.sum(~safe_mask))
            if removed > 0:
                tri_verts = shell_verts.reshape(num_tris, 3, 3)
                tri_normals = shell_normals.reshape(num_tris, 3, 3)
                shell_verts = tri_verts[safe_mask].reshape(-1, 3)
                shell_normals = tri_normals[safe_mask].reshape(-1, 3)
                Logger.log("i", "  -> Loai %d/%d tam giac shell va cham, con lai %d",
                           removed, num_tris, num_tris - removed)

        if self._cancelled:
            return

        # =====================================================================
        # BƯỚC 5: XỬ LÝ ĐA GIÁC (Merge nhỏ / Split lớn)
        # =====================================================================
        self.progress.emit(30)
        Logger.log("d", "Buoc 5/8: Xu ly da giac (merge/split)...")

        polygons = process_polygons(
            vertices, faces, overhang_mask, all_face_normals,
            min_area=float(s.get("min_polygon_area", 0.5)),
            max_area=float(s.get("max_polygon_area", 10.0)),
            gap=shell_gap,
            thickness=shell_thickness
        )

        Logger.log("i", "  -> %d da giac sau xu ly", len(polygons))

        if self._cancelled:
            return

        if len(polygons) == 0:
            Logger.log("w", "MeshTreeSupport: Khong co da giac nao. Chi xuat shell.")
            self._build_result_shell_only(shell_verts, shell_normals)
            return

        # =====================================================================
        # BƯỚC 6: TẠO TIP INTERFACE (Morphing polygon → octagon)
        # =====================================================================
        self.progress.emit(35)
        Logger.log("d", "Buoc 6/8: Tao tip interface (tip_radius=%.1fmm)...",
                   float(s.get("tip_radius", 0.4)))

        tip_verts, tip_normals, points_a = build_tip_interfaces(
            polygons,
            tip_radius=float(s.get("tip_radius", 0.4)),
            height_factor=float(s.get("tip_height_factor", 0.5))
        )

        Logger.log("i", "  -> Tip interface: %d dinh, %d Point A",
                   len(tip_verts), len(points_a))

        if self._cancelled:
            return

        if len(points_a) == 0:
            Logger.log("w", "MeshTreeSupport: Khong co Point A. Chi xuat shell.")
            self._build_result_shell_only(shell_verts, shell_normals)
            return

        # =====================================================================
        # BƯỚC 7: MÔ PHỎNG NHÁNH CÂY (Branch Routing - Space Colonization)
        # =====================================================================
        self.progress.emit(40)
        Logger.log("d", "Buoc 7/8: Mo phong nhanh cay (%d nhanh)...", len(points_a))

        # Chuyển list[PointA] → numpy arrays cho BranchRouter (Plan3)
        tip_points_arr = np.array([pa.position for pa in points_a], dtype=np.float64)
        # tip_normals: Plan3 dùng inward normal rồi negate → truyền -direction để
        # BranchRouter nhận được đúng outward departure direction
        tip_inward_arr = np.array([-pa.direction for pa in points_a], dtype=np.float64)

        all_nodes, all_edges = BranchRouter.route_branches(
            tip_points=tip_points_arr,
            collision_field=collision_field,
            step_size=float(s.get("step_size", 2.0)),
            merge_distance=float(s.get("merge_distance", 15.0)),
            min_clearance=float(s.get("min_clearance", 2.0)),
            cone_top_radius=float(s.get("tip_radius", 0.4)),
            cone_bottom_radius=float(s.get("tip_radius", 0.4)),
            straight_drop_height=float(s.get("straight_drop_height", 5.0)),
            tip_normals=tip_inward_arr,
            radius_growth_rate=float(s.get("radius_growth_rate", 0.01)),
            max_branch_angle=float(s.get("max_branch_angle", 45.0)),
            cone_height=float(s.get("step_size", 2.0)),
            departure_straight_down=bool(s.get("departure_straight_down", False)),
            max_merge_count=int(s.get("max_merge_count", 5)),
            cancel_check=self.isCancelled
        )

        Logger.log("i", "  -> Skeleton: %d nut, %d canh", len(all_nodes), len(all_edges))

        if self._cancelled:
            return

        if not all_edges:
            Logger.log("w", "MeshTreeSupport: Khong tao duoc nhanh nao. Hoan tat.")
            self.progress.emit(100)
            return

        # =====================================================================
        # BƯỚC 8: TẠO MESH NHÁNH (Frustum + Bézier bends + Base)
        # =====================================================================
        self.progress.emit(75)
        Logger.log("d", "Buoc 8/8: Tao mesh nhanh cay (%d segments)...",
                   int(s.get("cylinder_segments", 8)))

        branch_mesh = TreeMeshBuilder.build_tree_mesh(
            all_nodes, all_edges,
            segments=int(s.get("cylinder_segments", 8)),
            base_brim_multiplier=float(s.get("base_brim_multiplier", 3.0)),
            base_brim_height=float(s.get("base_brim_height", 0.5)),
            cancel_check=self.isCancelled
        )

        branch_verts = branch_mesh.getVertices() if branch_mesh is not None else None
        branch_normals = branch_mesh.getNormals() if branch_mesh is not None else None

        Logger.log("i", "  -> Mesh nhanh: %d dinh",
                   len(branch_verts) if branch_verts is not None else 0)

        if self._cancelled:
            return

        # =====================================================================
        # GHÉP TẤT CẢ MESH → KẾT QUẢ
        # =====================================================================
        self.progress.emit(90)

        all_mesh_parts = []
        all_normal_parts = []

        # Shell (lưu riêng để xuất thành object độc lập)
        if shell_verts is not None and len(shell_verts) > 0:
            self._result_shell_mesh_data = MeshData(
                vertices=shell_verts.astype(np.float32),
                normals=shell_normals.astype(np.float32)
            )
            all_mesh_parts.append(shell_verts.astype(np.float32))
            all_normal_parts.append(shell_normals.astype(np.float32))

        # Tip interface
        if tip_verts is not None and len(tip_verts) > 0:
            all_mesh_parts.append(tip_verts.astype(np.float32))
            all_normal_parts.append(tip_normals.astype(np.float32))

        # Branch
        if branch_verts is not None and len(branch_verts) > 0:
            all_mesh_parts.append(branch_verts.astype(np.float32))
            all_normal_parts.append(branch_normals.astype(np.float32))

        if not all_mesh_parts:
            Logger.log("w", "MeshTreeSupport: Khong tao duoc mesh nao. Hoan tat.")
            self.progress.emit(100)
            return

        final_verts = np.concatenate(all_mesh_parts, axis=0)
        final_normals = np.concatenate(all_normal_parts, axis=0)

        self._result_mesh_data = MeshData(
            vertices=final_verts,
            normals=final_normals
        )

        self.progress.emit(100)
        Logger.log("i", "MeshTreeSupport: Hoan tat! Mesh support co %d dinh "
                   "(shell + tip + branch).",
                   self._result_mesh_data.getVertexCount())

    def _build_result_shell_only(self, shell_verts, shell_normals):
        """Fallback: chỉ xuất shell khi không có nhánh."""
        if shell_verts is not None and len(shell_verts) > 0:
            self._result_mesh_data = MeshData(
                vertices=shell_verts.astype(np.float32),
                normals=shell_normals.astype(np.float32)
            )
        self.progress.emit(100)
