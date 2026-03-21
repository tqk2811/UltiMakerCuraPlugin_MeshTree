# ==============================================================================
# Module: Job điều phối toàn bộ pipeline sinh cây support
#
# Lớp MeshTreeSupportJob kế thừa UM.Job.Job, chạy trên worker thread
# (không block UI). Điều phối 5 bước tuần tự:
#
#   1. Phát hiện vùng lơ lửng (OverhangDetector)
#   2. Gom cụm điểm (PointClusterer)
#   3. Xây dựng trường va chạm (CollisionAvoider + multiprocessing)
#   4. Sinh nhánh cây (BranchRouter - Space Colonization)
#   5. Tạo mesh ống trụ (TreeMeshBuilder)
#
# Nhận settings dict từ Extension (thay vì hằng số cứng) để người dùng
# có thể tinh chỉnh thông số qua giao diện QML.
#
# Kết quả (MeshData) được lưu trong self._result_mesh_data.
# Khi Job hoàn thành, signal finished được phát → Extension lấy kết quả.
#
# Luồng thực thi: worker thread (Cura JobQueue)
# ==============================================================================

import numpy as np

from UM.Job import Job
from UM.Logger import Logger

# Import các module thuật toán của plugin
from . import OverhangDetector
from . import PointClusterer
from .CollisionAvoider import CollisionField
from . import BranchRouter
from . import TreeMeshBuilder


class MeshTreeSupportJob(Job):
    """
    Job chạy nền để sinh cây support hữu cơ.

    Kế thừa UM.Job.Job → chạy trên worker thread, không block UI Cura.
    Báo tiến độ qua progress.emit() → Extension cập nhật UI.

    Thuộc tính:
        _vertices        : numpy array (N, 3) - tọa độ đỉnh mesh (world coords, Z-up)
        _faces           : numpy array (M, 3) - chỉ số tam giác
        _settings        : dict - thông số thuật toán (từ QML dialog)
        _result_mesh_data : MeshData hoặc None - kết quả mesh cây support
    """

    def __init__(self, vertices, faces, settings):
        """
        Khởi tạo Job.

        Tham số:
            vertices : numpy array (N, 3) - tọa độ đỉnh đã chuyển về world coords (Z-up)
            faces    : numpy array (M, 3) - chỉ số tam giác
            settings : dict - thông số thuật toán, keys:
                overhang_angle, min_overhang_height, cluster_radius,
                branch_tip_radius, step_size, merge_distance, min_merge_height,
                convergence_strength, straight_drop_height, min_clearance,
                sdf_resolution, sdf_padding, cylinder_segments
        """
        super().__init__()

        # Dữ liệu mesh đầu vào (Z-up world coords)
        self._vertices = vertices.astype(np.float64)
        self._faces = faces.astype(np.int32)

        # Thông số thuật toán (bản sao từ Extension, không bị thay đổi giữa chừng)
        self._settings = settings

        # Kết quả: MeshData chứa cây support
        self._result_mesh_data = None

        # Cờ huỷ: cooperative cancellation (main thread set, worker thread kiểm tra)
        self._cancelled = False

    def requestCancel(self):
        """Main thread gọi để yêu cầu huỷ Job."""
        self._cancelled = True

    def isCancelled(self):
        """Kiểm tra cờ huỷ. Worker thread gọi tại mỗi bước."""
        return self._cancelled

    def getResultMeshData(self):
        """Lấy kết quả mesh sau khi Job hoàn thành."""
        return self._result_mesh_data

    def run(self):
        """
        Hàm chính của Job - chạy toàn bộ pipeline sinh cây support.

        Quy trình 5 bước:
        1. Phát hiện vùng lơ lửng → danh sách điểm overhang
        2. Gom cụm điểm → giảm số lượng tip
        3. Xây dựng trường va chạm SDF (multiprocessing)
        4. Sinh nhánh cây (Space Colonization bottom-up)
        5. Tạo mesh ống trụ → MeshData

        Luồng thực thi: worker thread (Cura JobQueue)
        """

        Logger.log("i", "MeshTreeSupport: Bat dau sinh cay support...")

        # Shorthand cho settings
        s = self._settings
        vertices = self._vertices
        faces = self._faces

        try:
            self._run_pipeline(s, vertices, faces)
        except InterruptedError:
            Logger.log("i", "MeshTreeSupport: Job da bi huy.")

    def _run_pipeline(self, s, vertices, faces):
        """Chạy pipeline 5 bước. Raise InterruptedError nếu bị huỷ."""

        # =====================================================================
        # BƯỚC 1: PHÁT HIỆN VÙNG LƠ LỬNG (Overhang Detection)
        # Thuật toán: Facet Normal Angle Detection
        # Đầu vào: mesh (vertices, faces)
        # Đầu ra: tọa độ trọng tâm + pháp tuyến các mặt lơ lửng
        # =====================================================================
        self.progress.emit(5)
        Logger.log("d", "Buoc 1/5: Phat hien vung lo lung (angle = %.1f)...",
                   s["overhang_angle"])

        overhang_points, overhang_normals = OverhangDetector.detect_overhangs(
            vertices, faces,
            threshold_angle_deg=s["overhang_angle"],
            min_height=s["min_overhang_height"]
        )

        Logger.log("i", "  -> Tim thay %d mat lo lung", len(overhang_points))

        if self._cancelled:
            Logger.log("i", "MeshTreeSupport: Da huy tai buoc 1.")
            return

        # Kiểm tra: nếu không có overhang → không cần support
        if len(overhang_points) == 0:
            Logger.log("i", "MeshTreeSupport: Khong tim thay vung lo lung. Hoan tat.")
            self.progress.emit(100)
            return

        # =====================================================================
        # BƯỚC 2: GOM CỤM ĐIỂM (Point Clustering)
        # Thuật toán: KD-Tree + Greedy Clustering
        # Đầu vào: điểm overhang (có thể hàng nghìn)
        # Đầu ra: trọng tâm cụm (vài chục → vài trăm tip points)
        # =====================================================================
        self.progress.emit(15)
        Logger.log("d", "Buoc 2/5: Gom cum diem (cluster radius = %.1fmm)...",
                   s["cluster_radius"])

        tip_points, tip_normals = PointClusterer.cluster_points(
            overhang_points,
            normals=overhang_normals,
            cluster_radius=s["cluster_radius"]
        )

        Logger.log("i", "  -> Gom thanh %d cum (tip points)", len(tip_points))

        if self._cancelled:
            Logger.log("i", "MeshTreeSupport: Da huy tai buoc 2.")
            return

        if len(tip_points) == 0:
            Logger.log("w", "MeshTreeSupport: Gom cum cho 0 tip. Hoan tat.")
            self.progress.emit(100)
            return

        # =====================================================================
        # BƯỚC 3: XÂY DỰNG TRƯỜNG VA CHẠM (Collision Field)
        # Thuật toán: BVH + SDF Grid + multiprocessing.Pool
        # Đầu vào: mesh (vertices, faces)
        # Đầu ra: CollisionField (tra cứu khoảng cách + gradient O(1))
        #
        # Đây là bước tốn thời gian nhất. multiprocessing.Pool phân phối
        # việc tính SDF trên lưới 3D cho nhiều CPU core song song.
        # =====================================================================
        self.progress.emit(20)
        Logger.log("d", "Buoc 3/5: Xay dung truong va cham SDF "
                   "(resolution = %.1fmm)...", s["sdf_resolution"])

        collision_field = CollisionField.build(
            vertices, faces,
            resolution=s["sdf_resolution"],
            padding=s["sdf_padding"],
            cancel_check=self.isCancelled
        )

        Logger.log("i", "  -> Truong va cham SDF da san sang")

        if self._cancelled:
            Logger.log("i", "MeshTreeSupport: Da huy tai buoc 3.")
            return

        # =====================================================================
        # BƯỚC 4: SINH NHÁNH CÂY (Branch Routing)
        # Thuật toán: Space Colonization Algorithm (bottom-up)
        # Đầu vào: tip points + collision field + tham số
        # Đầu ra: skeleton (nodes + edges) - bộ xương cây support
        #
        # Mỗi tip bắt đầu tại điểm overhang, mọc xuống bàn in (Z=0).
        # Nhánh gần nhau merge (định luật Murray). Tránh va chạm mesh.
        # Giai đoạn cuối rơi thẳng đứng tạo chân đế.
        # =====================================================================
        self.progress.emit(40)
        Logger.log("d", "Buoc 4/5: Sinh nhanh cay (Space Colonization bottom-up)...")

        all_nodes, all_edges = BranchRouter.route_branches(
            tip_points=tip_points,
            collision_field=collision_field,
            step_size=s["step_size"],
            merge_distance=s["merge_distance"],
            min_clearance=s["min_clearance"],
            tip_radius=s["branch_tip_radius"],
            min_merge_height=s["min_merge_height"],
            straight_drop_height=s["straight_drop_height"],
            convergence_strength=s["convergence_strength"],
            tip_normals=tip_normals,
            radius_growth_rate=s.get("radius_growth_rate", 0.02)
        )

        Logger.log("i", "  -> Skeleton: %d nut, %d canh",
                   len(all_nodes), len(all_edges))

        if self._cancelled:
            Logger.log("i", "MeshTreeSupport: Da huy tai buoc 4.")
            return

        if not all_edges:
            Logger.log("w", "MeshTreeSupport: Khong tao duoc nhanh nao. Hoan tat.")
            self.progress.emit(100)
            return

        # =====================================================================
        # BƯỚC 5: TẠO MESH ỐNG TRỤ (Tree Mesh Building)
        # Thuật toán: Frustum (hình nón cụt) + Cap (nắp)
        # Đầu vào: skeleton (nodes + edges)
        # Đầu ra: MeshData (vertices + normals, triangle soup format)
        #
        # Mỗi cạnh → 1 hình nón cụt với bán kính 2 đầu khác nhau.
        # Đỉnh cây và chân cây được đóng nắp cho kín nước.
        # =====================================================================
        self.progress.emit(80)
        Logger.log("d", "Buoc 5/5: Tao mesh ong tru (%d segments)...",
                   int(s["cylinder_segments"]))

        mesh_data = TreeMeshBuilder.build_tree_mesh(
            all_nodes, all_edges,
            segments=int(s["cylinder_segments"]),
            base_brim_multiplier=s.get("base_brim_multiplier", 3.0),
            base_brim_height=s.get("base_brim_height", 0.5)
        )

        # Lưu kết quả để Extension lấy qua getResultMeshData()
        self._result_mesh_data = mesh_data

        self.progress.emit(100)
        Logger.log("i", "MeshTreeSupport: Hoan tat! Mesh support co %d dinh.",
                   mesh_data.getVertexCount() if mesh_data else 0)
