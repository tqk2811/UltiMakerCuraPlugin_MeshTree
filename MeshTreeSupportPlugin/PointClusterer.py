# ==============================================================================
# Module: Gom cụm điểm lơ lửng (Point Clustering)
#
# Thuật toán: KD-Tree tự xây dựng bằng numpy (không phụ thuộc scipy)
# - Xây dựng cây KD-Tree từ tập điểm overhang
# - Dùng truy vấn bán kính (radius query) để tìm láng giềng
# - Gom các điểm gần nhau thành cụm, lấy trọng tâm cụm làm đại diện
# - Giảm số lượng ngọn cây (tree tips) để tránh support quá dày đặc
#
# Đầu vào: mảng điểm (N,3), bán kính gom cụm
# Đầu ra: mảng trọng tâm cụm (K,3), K << N
#
# Luồng thực thi: Chạy trong worker thread (bên trong Job.run())
# ==============================================================================

import numpy as np


# ==============================================================================
# PHẦN 1: CẤU TRÚC KD-TREE
# KD-Tree là cây nhị phân phân chia không gian k chiều.
# Mỗi nút chia không gian theo 1 trục (x, y, hoặc z), luân phiên theo độ sâu.
# Cho phép truy vấn láng giềng nhanh hơn brute-force (O(log N) thay vì O(N)).
# ==============================================================================

class KDNode:
    """
    Nút trong cây KD-Tree.

    Thuộc tính:
        point  : numpy array (3,) - tọa độ điểm tại nút này
        index  : int - chỉ số gốc của điểm trong mảng đầu vào
        axis   : int - trục phân chia (0=X, 1=Y, 2=Z)
        left   : KDNode hoặc None - nhánh trái (giá trị nhỏ hơn trên trục chia)
        right  : KDNode hoặc None - nhánh phải (giá trị lớn hơn trên trục chia)
    """
    __slots__ = ['point', 'index', 'axis', 'left', 'right']

    def __init__(self, point, index, axis, left=None, right=None):
        self.point = point
        self.index = index
        self.axis = axis
        self.left = left
        self.right = right


def build_kdtree(points, indices=None, depth=0):
    """
    Xây dựng KD-Tree đệ quy từ tập điểm.

    Thuật toán:
    1. Chọn trục chia = depth % 3 (luân phiên X → Y → Z)
    2. Sắp xếp điểm theo trục chia
    3. Lấy điểm giữa (median) làm nút gốc
    4. Đệ quy xây nhánh trái (nửa dưới) và nhánh phải (nửa trên)

    Tham số:
        points  : numpy array (N, 3) - tọa độ các điểm
        indices : numpy array (N,) - chỉ số gốc, None thì tự tạo
        depth   : int - độ sâu hiện tại (để chọn trục chia)

    Trả về:
        KDNode - nút gốc của cây (hoặc None nếu không có điểm)
    """

    # Điều kiện dừng: không còn điểm nào
    if len(points) == 0:
        return None

    # Khởi tạo mảng chỉ số nếu chưa có (lần gọi đầu tiên)
    if indices is None:
        indices = np.arange(len(points))

    # Chọn trục chia: luân phiên X(0) → Y(1) → Z(2)
    axis = depth % 3

    # Sắp xếp theo trục chia để tìm median
    sorted_order = np.argsort(points[:, axis])
    mid = len(sorted_order) // 2  # Vị trí giữa (median)

    # Tạo nút với điểm median
    # Đệ quy xây nhánh trái (nửa nhỏ) và nhánh phải (nửa lớn)
    return KDNode(
        point=points[sorted_order[mid]].copy(),
        index=indices[sorted_order[mid]],
        axis=axis,
        left=build_kdtree(
            points[sorted_order[:mid]],
            indices[sorted_order[:mid]],
            depth + 1
        ),
        right=build_kdtree(
            points[sorted_order[mid + 1:]],
            indices[sorted_order[mid + 1:]],
            depth + 1
        )
    )


def query_radius(node, target, radius, results=None):
    """
    Truy vấn bán kính trên KD-Tree: tìm tất cả điểm nằm trong bán kính
    cho trước quanh điểm target.

    Thuật toán:
    1. Kiểm tra khoảng cách từ nút hiện tại đến target
    2. Nếu <= radius → thêm vào kết quả
    3. Tính hiệu trên trục chia để quyết định duyệt nhánh nào
    4. Luôn duyệt nhánh gần; chỉ duyệt nhánh xa nếu có thể chứa điểm gần

    Tham số:
        node    : KDNode - nút gốc cây con
        target  : numpy array (3,) - điểm tâm truy vấn
        radius  : float - bán kính tìm kiếm
        results : list - danh sách tích lũy chỉ số kết quả

    Trả về:
        list[int] - danh sách chỉ số các điểm trong bán kính
    """

    if results is None:
        results = []

    # Điều kiện dừng: nút rỗng
    if node is None:
        return results

    # Tính khoảng cách Euclid từ điểm nút đến target
    dist = np.linalg.norm(node.point - target)

    # Nếu điểm nằm trong bán kính → thêm vào kết quả
    if dist <= radius:
        results.append(node.index)

    # Hiệu trên trục chia: dùng để cắt tỉa (pruning) nhánh không cần duyệt
    diff = target[node.axis] - node.point[node.axis]

    # Duyệt nhánh gần trước (nhánh có khả năng chứa điểm gần nhất)
    # diff < 0 → target nằm bên trái → duyệt trái trước
    # diff >= 0 → target nằm bên phải → duyệt phải trước
    if diff < 0:
        near_branch = node.left
        far_branch = node.right
    else:
        near_branch = node.right
        far_branch = node.left

    # Luôn duyệt nhánh gần
    query_radius(near_branch, target, radius, results)

    # Chỉ duyệt nhánh xa nếu khoảng cách trên trục chia <= radius
    # (có thể có điểm trong bán kính ở nhánh xa)
    if abs(diff) <= radius:
        query_radius(far_branch, target, radius, results)

    return results


# ==============================================================================
# PHẦN 2: GOM CỤM THAM LAM (GREEDY CLUSTERING)
# Duyệt các điểm từ cao xuống thấp (ưu tiên overhang cao).
# Với mỗi điểm chưa ghé thăm, tìm tất cả láng giềng trong bán kính.
# Gom chúng thành 1 cụm, lấy trọng tâm làm điểm đại diện.
# ==============================================================================

def cluster_points(points, cluster_radius=5.0):
    """
    Gom cụm các điểm lơ lửng gần nhau bằng KD-Tree + thuật toán tham lam.

    Mục đích: Giảm số lượng ngọn cây support từ N (có thể hàng nghìn)
    xuống K (vài chục đến vài trăm), tránh tạo quá nhiều nhánh.

    Thuật toán:
    1. Xây dựng KD-Tree từ tất cả điểm overhang
    2. Sắp xếp điểm theo chiều cao Z giảm dần (ưu tiên overhang cao)
    3. Với mỗi điểm chưa ghé thăm:
       a. Truy vấn KD-Tree tìm mọi láng giềng trong cluster_radius
       b. Đánh dấu tất cả láng giềng là "đã ghé thăm"
       c. Tính trọng tâm cụm → đây là 1 tip point cho cây support
    4. Trả về mảng trọng tâm các cụm

    Tham số:
        points         : numpy array (N, 3) - tọa độ điểm overhang
        cluster_radius : float - bán kính gom cụm (mm)

    Trả về:
        numpy array (K, 3) - trọng tâm các cụm, K << N
    """

    # Trường hợp đặc biệt: không có điểm nào
    if len(points) == 0:
        return np.zeros((0, 3), dtype=np.float64)

    # Bước 1: Xây dựng KD-Tree từ toàn bộ điểm overhang
    kdtree = build_kdtree(points)

    # Bước 2: Sắp xếp chỉ số theo Z giảm dần (overhang cao được xử lý trước)
    # Lý do: overhang ở cao hơn thường quan trọng hơn vì nhánh support dài hơn
    sorted_indices = np.argsort(-points[:, 2])  # Giảm dần theo Z

    # Tập hợp các điểm đã được gom vào cụm nào đó
    visited = set()

    # Danh sách trọng tâm các cụm
    clusters = []

    # Bước 3: Duyệt từng điểm theo thứ tự Z giảm dần
    for idx in sorted_indices:
        # Bỏ qua điểm đã thuộc cụm khác
        if idx in visited:
            continue

        # Truy vấn KD-Tree: tìm tất cả điểm trong bán kính cluster_radius
        neighbor_indices = query_radius(kdtree, points[idx], cluster_radius)

        # Lọc bỏ những điểm đã được gom
        new_neighbors = [j for j in neighbor_indices if j not in visited]

        # Nếu không còn điểm nào mới → bỏ qua (hiếm khi xảy ra)
        if not new_neighbors:
            continue

        # Đánh dấu tất cả láng giềng là đã ghé thăm
        for j in new_neighbors:
            visited.add(j)

        # Tính trọng tâm cụm = trung bình tọa độ các điểm trong cụm
        cluster_centroid = np.mean(points[new_neighbors], axis=0)
        clusters.append(cluster_centroid)

    # Chuyển danh sách thành numpy array
    if clusters:
        return np.array(clusters, dtype=np.float64)
    else:
        return np.zeros((0, 3), dtype=np.float64)
