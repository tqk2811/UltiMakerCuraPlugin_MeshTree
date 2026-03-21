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
# Kết quả (MeshData) được lưu trong self._result_mesh_data.
# Khi Job hoàn thành, signal finished được phát → Extension lấy kết quả
# và gọi callLater() để thêm vào scene trên main thread.
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


# ==============================================================================
# HẰNG SỐ CẤU HÌNH (Settings)
# Các tham số mặc định cho toàn bộ pipeline.
# Có thể điều chỉnh để tối ưu cho từng loại mô hình.
# ==============================================================================

# Góc overhang (độ): mặt có pháp tuyến lệch > góc này so với -Z → cần support
OVERHANG_ANGLE = 45.0

# Bán kính gom cụm (mm): điểm overhang trong bán kính này gộp thành 1 tip
CLUSTER_RADIUS = 5.0

# Bán kính nhánh tại ngọn cây (mm)
BRANCH_TIP_RADIUS = 0.5

# Bước di chuyển mỗi lần lặp khi sinh nhánh (mm)
STEP_SIZE = 1.0

# Khoảng cách an toàn tối thiểu từ nhánh đến mesh (mm)
MIN_CLEARANCE = 2.0

# Khoảng cách để 2 nhánh merge thành 1 (mm)
MERGE_DISTANCE = 5.0

# Độ phân giải lưới SDF (mm): nhỏ hơn = chính xác hơn, chậm hơn
SDF_RESOLUTION = 3.0

# Chiều cao tối thiểu để merge nhánh (mm trên bàn in)
# Dưới mức này, nhánh chỉ rơi thẳng xuống, không merge nữa
MIN_MERGE_HEIGHT = 20.0

# Chiều cao bắt đầu rơi thẳng đứng (mm): tạo chân đế ổn định
STRAIGHT_DROP_HEIGHT = 10.0

# Số mặt bao cho ống trụ (8 = bát giác, 12 = mượt hơn)
CYLINDER_SEGMENTS = 8

# Lực hội tụ về trọng tâm (0.0 - 1.0)
CONVERGENCE_STRENGTH = 0.3

# Chiều cao tối thiểu trên bàn in để lọc overhang (mm)
MIN_OVERHANG_HEIGHT = 0.5

# Padding quanh mesh cho lưới SDF (mm)
SDF_PADDING = 10.0


class MeshTreeSupportJob(Job):
    """
    Job chạy nền để sinh cây support hữu cơ.

    Kế thừa UM.Job.Job → chạy trên worker thread, không block UI Cura.
    Báo tiến độ qua setProgress() → UI hiển thị thanh tiến trình.

    Thuộc tính:
        _vertices        : numpy array (N, 3) - tọa độ đỉnh mesh (world coords)
        _faces           : numpy array (M, 3) - chỉ số tam giác
        _result_mesh_data : MeshData hoặc None - kết quả mesh cây support
    """

    def __init__(self, vertices, faces):
        """
        Khởi tạo Job.

        Tham số:
            vertices : numpy array (N, 3) - tọa độ đỉnh đã chuyển về world coords
            faces    : numpy array (M, 3) - chỉ số tam giác
        """
        super().__init__()

        # Dữ liệu mesh đầu vào (đã ở hệ tọa độ thế giới)
        self._vertices = vertices.astype(np.float64)
        self._faces = faces.astype(np.int32)

        # Kết quả: MeshData chứa cây support
        self._result_mesh_data = None

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

        Logger.log("i", "MeshTreeSupport: Bắt đầu sinh cây support...")

        vertices = self._vertices
        faces = self._faces

        # =====================================================================
        # BƯỚC 1: PHÁT HIỆN VÙNG LƠ LỬNG (Overhang Detection)
        # Thuật toán: Facet Normal Angle Detection
        # Đầu vào: mesh (vertices, faces)
        # Đầu ra: tọa độ trọng tâm + pháp tuyến các mặt lơ lửng
        # =====================================================================
        self.setProgress(5)
        Logger.log("d", "Bước 1/5: Phát hiện vùng lơ lửng (overhang angle = %.1f°)...",
                   OVERHANG_ANGLE)

        overhang_points, overhang_normals = OverhangDetector.detect_overhangs(
            vertices, faces,
            threshold_angle_deg=OVERHANG_ANGLE,
            min_height=MIN_OVERHANG_HEIGHT
        )

        Logger.log("i", "  → Tìm thấy %d mặt lơ lửng", len(overhang_points))

        # Kiểm tra: nếu không có overhang → không cần support
        if len(overhang_points) == 0:
            Logger.log("i", "MeshTreeSupport: Không tìm thấy vùng lơ lửng. Hoàn tất.")
            self.setProgress(100)
            return

        # =====================================================================
        # BƯỚC 2: GOM CỤM ĐIỂM (Point Clustering)
        # Thuật toán: KD-Tree + Greedy Clustering
        # Đầu vào: điểm overhang (có thể hàng nghìn)
        # Đầu ra: trọng tâm cụm (vài chục → vài trăm tip points)
        # =====================================================================
        self.setProgress(15)
        Logger.log("d", "Bước 2/5: Gom cụm điểm (cluster radius = %.1fmm)...",
                   CLUSTER_RADIUS)

        tip_points = PointClusterer.cluster_points(
            overhang_points,
            cluster_radius=CLUSTER_RADIUS
        )

        Logger.log("i", "  → Gom thành %d cụm (tip points)", len(tip_points))

        if len(tip_points) == 0:
            Logger.log("w", "MeshTreeSupport: Gom cụm cho 0 tip. Hoàn tất.")
            self.setProgress(100)
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
        self.setProgress(20)
        Logger.log("d", "Bước 3/5: Xây dựng trường va chạm SDF "
                   "(resolution = %.1fmm, multiprocessing)...", SDF_RESOLUTION)

        collision_field = CollisionField.build(
            vertices, faces,
            resolution=SDF_RESOLUTION,
            padding=SDF_PADDING
        )

        Logger.log("i", "  → Trường va chạm SDF đã sẵn sàng")

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
        self.setProgress(40)
        Logger.log("d", "Bước 4/5: Sinh nhánh cây (Space Colonization bottom-up)...")

        all_nodes, all_edges = BranchRouter.route_branches(
            tip_points=tip_points,
            collision_field=collision_field,
            step_size=STEP_SIZE,
            merge_distance=MERGE_DISTANCE,
            min_clearance=MIN_CLEARANCE,
            tip_radius=BRANCH_TIP_RADIUS,
            min_merge_height=MIN_MERGE_HEIGHT,
            straight_drop_height=STRAIGHT_DROP_HEIGHT,
            convergence_strength=CONVERGENCE_STRENGTH
        )

        Logger.log("i", "  → Skeleton: %d nút, %d cạnh",
                   len(all_nodes), len(all_edges))

        if not all_edges:
            Logger.log("w", "MeshTreeSupport: Không tạo được nhánh nào. Hoàn tất.")
            self.setProgress(100)
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
        self.setProgress(80)
        Logger.log("d", "Bước 5/5: Tạo mesh ống trụ (%d segments)...",
                   CYLINDER_SEGMENTS)

        mesh_data = TreeMeshBuilder.build_tree_mesh(
            all_nodes, all_edges,
            segments=CYLINDER_SEGMENTS
        )

        # Lưu kết quả để Extension lấy qua getResultMeshData()
        self._result_mesh_data = mesh_data

        self.setProgress(100)
        Logger.log("i", "MeshTreeSupport: Hoàn tất! Mesh support có %d đỉnh.",
                   mesh_data.getVertexCount() if mesh_data else 0)
