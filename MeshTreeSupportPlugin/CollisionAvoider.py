# ==============================================================================
# Module: Tránh va chạm (Collision Avoidance)
#
# Kết hợp hai kỹ thuật:
# 1. BVH (Bounding Volume Hierarchy) - cây phân cấp hộp bao trục (AABB)
#    để tăng tốc truy vấn khoảng cách điểm-đến-mesh
# 2. SDF (Signed Distance Field) - trường khoảng cách trên lưới 3D
#    cho phép tra cứu nhanh bằng nội suy ba chiều (trilinear interpolation)
#
# Đầu vào: vertices (N,3), faces (M,3)
# Đầu ra: CollisionField object cung cấp API tra cứu khoảng cách nhanh
#
# Luồng thực thi:
# - build_bvh(), compute_sdf_grid(): worker thread (trong Job.run())
# - get_distance(), get_avoidance_vector(): worker thread (trong Job.run())
# ==============================================================================

import numpy as np
from UM.Logger import Logger

# Hằng số: số lượng tam giác tối đa trong mỗi nút lá BVH
_MAX_LEAF_SIZE = 8

# Hằng số: độ sâu đệ quy tối đa của BVH (tránh stack overflow)
_MAX_BVH_DEPTH = 28


# ==============================================================================
# PHẦN 1: BVH (Bounding Volume Hierarchy)
#
# BVH là cấu trúc cây nhị phân, mỗi nút chứa hộp bao trục AABB.
# Cho phép truy vấn khoảng cách từ 1 điểm đến mesh (hàng nghìn tam giác)
# với độ phức tạp O(log M) thay vì O(M).
#
# Thuật toán xây dựng:
# - Tính hộp bao AABB cho nhóm tam giác
# - Tìm trục dài nhất → chia tại trung vị (median split)
# - Đệ quy cho nửa trái và nửa phải
# ==============================================================================

class AABBNode:
    """
    Nút trong cây BVH.

    Nút trong (internal): chứa 2 nút con (left, right)
    Nút lá (leaf): chứa danh sách chỉ số tam giác (face_indices)

    Thuộc tính:
        min_corner   : numpy array (3,) - góc nhỏ nhất của hộp bao AABB
        max_corner   : numpy array (3,) - góc lớn nhất của hộp bao AABB
        left         : AABBNode - nhánh trái (hoặc None nếu là nút lá)
        right        : AABBNode - nhánh phải (hoặc None nếu là nút lá)
        face_indices : numpy array - chỉ số tam giác (chỉ có ở nút lá)
    """
    __slots__ = ['min_corner', 'max_corner', 'left', 'right', 'face_indices']

    def __init__(self):
        self.min_corner = None
        self.max_corner = None
        self.left = None
        self.right = None
        self.face_indices = None


def build_bvh(vertices, faces, face_indices=None, depth=0):
    """
    Xây dựng cây BVH từ mesh tam giác.

    Thuật toán Median Split:
    1. Tính AABB bao quanh tất cả tam giác trong tập hiện tại
    2. Tìm trục có kích thước lớn nhất (trục chia tối ưu)
    3. Sắp xếp tam giác theo trọng tâm trên trục đó
    4. Chia tại vị trí median → hai nửa gần bằng nhau
    5. Đệ quy cho mỗi nửa

    Tham số:
        vertices     : numpy array (N, 3) - tọa độ đỉnh mesh
        faces        : numpy array (M, 3) - chỉ số đỉnh cho mỗi tam giác
        face_indices : numpy array - tập con chỉ số tam giác (None = toàn bộ)
        depth        : int - độ sâu đệ quy hiện tại

    Trả về:
        AABBNode - nút gốc của cây BVH
    """

    # Lần gọi đầu tiên: sử dụng toàn bộ tam giác
    if face_indices is None:
        face_indices = np.arange(len(faces), dtype=np.int32)

    node = AABBNode()

    # --- Tính hộp bao AABB ---
    # Lấy tất cả đỉnh của các tam giác trong tập
    tri_verts = vertices[faces[face_indices].ravel()]  # shape (K*3, 3)
    node.min_corner = tri_verts.min(axis=0)
    node.max_corner = tri_verts.max(axis=0)

    # --- Điều kiện tạo nút lá ---
    # Dừng khi số tam giác đủ nhỏ hoặc đạt độ sâu tối đa
    if len(face_indices) <= _MAX_LEAF_SIZE or depth >= _MAX_BVH_DEPTH:
        node.face_indices = face_indices
        return node

    # --- Chọn trục chia: trục có kích thước AABB lớn nhất ---
    extent = node.max_corner - node.min_corner
    axis = int(np.argmax(extent))  # 0=X, 1=Y, 2=Z

    # --- Tính trọng tâm các tam giác theo trục chia ---
    # Trọng tâm = trung bình 3 đỉnh, ta chỉ cần thành phần trên trục chia
    tri_vertices = vertices[faces[face_indices]]  # shape (K, 3, 3)
    centroids_on_axis = tri_vertices[:, :, axis].mean(axis=1)  # shape (K,)

    # --- Chia tại trung vị (median) ---
    median_val = np.median(centroids_on_axis)
    left_mask = centroids_on_axis <= median_val
    right_mask = ~left_mask

    left_indices = face_indices[left_mask]
    right_indices = face_indices[right_mask]

    # Nếu không chia được (tất cả cùng 1 bên) → tạo nút lá
    if len(left_indices) == 0 or len(right_indices) == 0:
        node.face_indices = face_indices
        return node

    # --- Đệ quy xây dựng nhánh trái và phải ---
    node.left = build_bvh(vertices, faces, left_indices, depth + 1)
    node.right = build_bvh(vertices, faces, right_indices, depth + 1)

    return node


# ==============================================================================
# PHẦN 2: TÍNH KHOẢNG CÁCH ĐIỂM-ĐẾN-TAM GIÁC
#
# Sử dụng thuật toán từ "Real-Time Collision Detection" (Ericson, 2004).
# Chia không gian quanh tam giác thành 7 vùng Voronoi:
# - 3 vùng đỉnh (gần đỉnh nhất)
# - 3 vùng cạnh (gần cạnh nhất)
# - 1 vùng mặt (hình chiếu nằm trong tam giác)
# Xác định vùng bằng tọa độ barycentric rồi tính khoảng cách.
# ==============================================================================

def _point_to_triangle_distance(p, a, b, c):
    """
    Tính khoảng cách ngắn nhất từ điểm p đến tam giác (a, b, c).

    Thuật toán Ericson (2004): dùng tọa độ barycentric để xác định
    điểm gần nhất trên tam giác, rồi tính khoảng cách Euclid.

    Tham số:
        p : numpy array (3,) - điểm truy vấn
        a : numpy array (3,) - đỉnh thứ nhất của tam giác
        b : numpy array (3,) - đỉnh thứ hai
        c : numpy array (3,) - đỉnh thứ ba

    Trả về:
        float - khoảng cách ngắn nhất từ p đến tam giác
    """

    # Hai cạnh xuất phát từ đỉnh a
    ab = b - a  # Vector cạnh a→b
    ac = c - a  # Vector cạnh a→c
    ap = p - a  # Vector a→p

    # Các tích vô hướng (dot product) cần thiết
    d1 = np.dot(ab, ap)
    d2 = np.dot(ac, ap)

    # Vùng đỉnh A: hình chiếu nằm ngoài cả hai cạnh ab và ac
    if d1 <= 0.0 and d2 <= 0.0:
        return np.linalg.norm(p - a)

    # Kiểm tra vùng đỉnh B
    bp = p - b
    d3 = np.dot(ab, bp)
    d4 = np.dot(ac, bp)
    if d3 >= 0.0 and d4 <= d3:
        return np.linalg.norm(p - b)

    # Kiểm tra vùng cạnh AB
    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        # Hình chiếu nằm trên cạnh AB
        v = d1 / (d1 - d3)
        closest = a + v * ab
        return np.linalg.norm(p - closest)

    # Kiểm tra vùng đỉnh C
    cp = p - c
    d5 = np.dot(ab, cp)
    d6 = np.dot(ac, cp)
    if d6 >= 0.0 and d5 <= d6:
        return np.linalg.norm(p - c)

    # Kiểm tra vùng cạnh AC
    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        # Hình chiếu nằm trên cạnh AC
        w = d2 / (d2 - d6)
        closest = a + w * ac
        return np.linalg.norm(p - closest)

    # Kiểm tra vùng cạnh BC
    va = d3 * d6 - d5 * d4
    if va <= 0.0 and (d4 - d3) >= 0.0 and (d5 - d6) >= 0.0:
        # Hình chiếu nằm trên cạnh BC
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        closest = b + w * (c - b)
        return np.linalg.norm(p - closest)

    # Vùng mặt: hình chiếu nằm bên trong tam giác
    denom = 1.0 / (va + vb + vc)
    v = vb * denom
    w = vc * denom
    closest = a + v * ab + w * ac
    return np.linalg.norm(p - closest)


def _point_aabb_distance(point, min_corner, max_corner):
    """
    Tính khoảng cách ngắn nhất từ điểm đến hộp AABB.
    Nếu điểm nằm trong hộp → khoảng cách = 0.

    Thuật toán: kẹp (clamp) mỗi tọa độ vào phạm vi hộp,
    rồi tính khoảng cách từ điểm gốc đến điểm kẹp.

    Tham số:
        point      : numpy array (3,)
        min_corner : numpy array (3,) - góc nhỏ AABB
        max_corner : numpy array (3,) - góc lớn AABB

    Trả về:
        float - khoảng cách (0 nếu điểm nằm trong hộp)
    """
    # Kẹp tọa độ điểm vào phạm vi AABB
    clamped = np.clip(point, min_corner, max_corner)
    return np.linalg.norm(point - clamped)


def query_min_distance(bvh_node, point, vertices, faces, best_dist=float('inf')):
    """
    Truy vấn BVH: tìm khoảng cách nhỏ nhất từ 1 điểm đến mesh.

    Thuật toán duyệt cây BVH có cắt tỉa (pruning):
    1. Tính khoảng cách từ điểm đến AABB của nút
    2. Nếu >= best_dist hiện tại → bỏ qua nhánh này (cắt tỉa)
    3. Nếu nút lá → duyệt từng tam giác, cập nhật best_dist
    4. Nếu nút trong → đệ quy, ưu tiên nhánh gần hơn trước

    Tham số:
        bvh_node  : AABBNode - nút hiện tại
        point     : numpy array (3,) - điểm truy vấn
        vertices  : numpy array (N, 3) - tọa độ đỉnh mesh
        faces     : numpy array (M, 3) - chỉ số đỉnh
        best_dist : float - khoảng cách tốt nhất tìm được

    Trả về:
        float - khoảng cách nhỏ nhất từ point đến mesh
    """

    if bvh_node is None:
        return best_dist

    # Cắt tỉa: nếu AABB quá xa → không thể cải thiện best_dist
    box_dist = _point_aabb_distance(point, bvh_node.min_corner, bvh_node.max_corner)
    if box_dist >= best_dist:
        return best_dist

    # Nút lá: duyệt từng tam giác
    if bvh_node.face_indices is not None:
        for fi in bvh_node.face_indices:
            # Lấy 3 đỉnh của tam giác
            v0 = vertices[faces[fi, 0]]
            v1 = vertices[faces[fi, 1]]
            v2 = vertices[faces[fi, 2]]
            # Tính khoảng cách chính xác điểm-tam giác
            d = _point_to_triangle_distance(point, v0, v1, v2)
            if d < best_dist:
                best_dist = d
        return best_dist

    # Nút trong: đệ quy hai nhánh, ưu tiên nhánh gần hơn
    left_dist = _point_aabb_distance(
        point, bvh_node.left.min_corner, bvh_node.left.max_corner
    ) if bvh_node.left else float('inf')

    right_dist = _point_aabb_distance(
        point, bvh_node.right.min_corner, bvh_node.right.max_corner
    ) if bvh_node.right else float('inf')

    # Duyệt nhánh gần trước để có best_dist tốt hơn sớm → cắt tỉa hiệu quả
    if left_dist < right_dist:
        best_dist = query_min_distance(bvh_node.left, point, vertices, faces, best_dist)
        best_dist = query_min_distance(bvh_node.right, point, vertices, faces, best_dist)
    else:
        best_dist = query_min_distance(bvh_node.right, point, vertices, faces, best_dist)
        best_dist = query_min_distance(bvh_node.left, point, vertices, faces, best_dist)

    return best_dist


# ==============================================================================
# PHẦN 3: RAY CASTING - XÁC ĐỊNH BÊN TRONG / BÊN NGOÀI MESH
#
# Để chuyển từ unsigned distance sang signed distance, cần xác định
# mỗi điểm nằm bên trong hay bên ngoài mesh.
#
# Thuật toán: Parity Test (Jordan Curve Theorem mở rộng 3D)
# - Bắn tia từ điểm theo hướng +Z
# - Đếm số giao điểm với mesh
# - Số lẻ = bên trong, số chẵn = bên ngoài
#
# Sử dụng thuật toán Möller-Trumbore cho ray-triangle intersection.
# ==============================================================================

def _ray_triangle_z_hit(origin_xy, v0, v1, v2):
    """
    Tìm tọa độ Z giao điểm của tia (origin_xy, +Z) với tam giác.

    Thuật toán Möller-Trumbore đơn giản hóa cho tia song song trục Z:
    - Ray direction = (0, 0, 1)
    - Kiểm tra tọa độ XY bằng barycentric
    - Trả về Z giao điểm (hoặc None nếu không cắt)

    Tham số:
        origin_xy : numpy array (2,) - tọa độ XY gốc tia
        v0, v1, v2 : numpy array (3,) - 3 đỉnh tam giác

    Trả về:
        float hoặc None - tọa độ Z giao điểm (None nếu không cắt)
    """
    e1 = v1 - v0
    e2 = v2 - v0

    # Với ray dir = (0,0,1): a = e1[1]*e2[0] - e1[0]*e2[1]
    a = e1[1] * e2[0] - e1[0] * e2[1]

    if abs(a) < 1e-10:
        return None  # Tia song song mặt tam giác

    inv_a = 1.0 / a
    sx = origin_xy[0] - v0[0]
    sy = origin_xy[1] - v0[1]

    u = (sx * (-e2[1]) + sy * e2[0]) * inv_a
    if u < 0.0 or u > 1.0:
        return None

    q_z = sx * e1[1] - sy * e1[0]
    v = q_z * inv_a
    if v < 0.0 or u + v > 1.0:
        return None

    # Z giao điểm = v0.z + u*e1.z + v*e2.z
    return v0[2] + u * e1[2] + v * e2[2]


def _collect_ray_z_hits(bvh_node, origin_xy, vertices, faces, hits):
    """
    Thu thập TẤT CẢ tọa độ Z giao điểm của tia +Z với mesh qua BVH.

    Thay vì đếm giao điểm cho từng điểm lưới, ta thu thập 1 lần
    cho mỗi cột (x,y) rồi dùng lại cho toàn bộ z trong cột đó.

    Tham số:
        bvh_node  : AABBNode - nút BVH
        origin_xy : numpy array (2,) - tọa độ XY gốc tia
        vertices  : numpy array (N, 3)
        faces     : numpy array (M, 3)
        hits      : list - danh sách Z giao điểm (output, append vào)
    """
    if bvh_node is None:
        return

    # Cắt tỉa: tia +Z có đi qua hộp AABB không?
    # Chỉ cần XY nằm trong AABB (Z không giới hạn vì ta thu thập tất cả)
    if (origin_xy[0] < bvh_node.min_corner[0] or
            origin_xy[0] > bvh_node.max_corner[0] or
            origin_xy[1] < bvh_node.min_corner[1] or
            origin_xy[1] > bvh_node.max_corner[1]):
        return

    # Nút lá: kiểm tra từng tam giác
    if bvh_node.face_indices is not None:
        for fi in bvh_node.face_indices:
            v0 = vertices[faces[fi, 0]]
            v1 = vertices[faces[fi, 1]]
            v2 = vertices[faces[fi, 2]]
            z_hit = _ray_triangle_z_hit(origin_xy, v0, v1, v2)
            if z_hit is not None:
                hits.append(z_hit)
        return

    # Nút trong: đệ quy
    _collect_ray_z_hits(bvh_node.left, origin_xy, vertices, faces, hits)
    _collect_ray_z_hits(bvh_node.right, origin_xy, vertices, faces, hits)


# ==============================================================================
# PHẦN 4: TÍNH LƯỚI SDF (Signed Distance Field) - ĐA LUỒNG
#
# Trường khoảng cách CÓ DẤU (Signed Distance Field):
# - Bên ngoài mesh: SDF > 0 (khoảng cách dương)
# - Trên bề mặt mesh: SDF = 0
# - Bên trong mesh: SDF < 0 (khoảng cách âm)
#
# Tối ưu:
# 1. Column ray casting: bắn 1 tia/cột (x,y) → thu thập tất cả Z hits
#    → xác định inside/outside cho toàn bộ z trong cột (bisect O(log K))
#    Giảm từ O(nx*ny*nz*logM) xuống O(nx*ny*logM) cho phần ray casting
#
# 2. ThreadPoolExecutor: chia lưới thành lát X, mỗi thread xử lý 1 lát
#    Python GIL giới hạn CPU-bound nhưng vẫn tận dụng được khi numpy
#    release GIL trong các phép toán mảng
#
# 3. Tránh multiprocessing vì gây deadlock trên Windows/Cura embedded Python
# ==============================================================================

import bisect
import os
from concurrent.futures import ThreadPoolExecutor


def _process_sdf_slice(ix, x_coord, y_coords, z_coords, bvh_root, vertices, faces):
    """
    Tính 1 lát X của lưới SDF (đa luồng an toàn).

    Mỗi lát xử lý tất cả (iy, iz) cho 1 giá trị ix.
    Tối ưu: column ray casting — 1 tia/cột (x,y) thay vì 1 tia/điểm.

    Tham số:
        ix        : int - chỉ số X
        x_coord   : float - tọa độ X
        y_coords  : numpy array - tọa độ Y
        z_coords  : numpy array - tọa độ Z
        bvh_root  : AABBNode - gốc BVH
        vertices  : numpy array (N, 3)
        faces     : numpy array (M, 3)

    Trả về:
        slice_data   : numpy array (ny, nz) - khoảng cách có dấu
        inside_count : int - số điểm bên trong mesh
    """
    ny = len(y_coords)
    nz = len(z_coords)
    slice_data = np.zeros((ny, nz), dtype=np.float64)
    inside_count = 0

    for iy in range(ny):
        origin_xy = np.array([x_coord, y_coords[iy]])

        # === Column ray casting ===
        # Bắn 1 tia +Z cho cột (x,y) → thu thập TẤT CẢ Z giao điểm
        # Thay vì bắn nz tia riêng lẻ → giảm O(nz*logM) xuống O(logM)
        z_hits = []
        _collect_ray_z_hits(bvh_root, origin_xy, vertices, faces, z_hits)
        z_hits.sort()  # Sắp xếp Z tăng dần cho bisect

        for iz in range(nz):
            point = np.array([x_coord, y_coords[iy], z_coords[iz]])

            # Khoảng cách unsigned đến tam giác gần nhất
            dist = query_min_distance(bvh_root, point, vertices, faces)

            # Xác định inside/outside từ Z hits đã tính sẵn
            # Số giao điểm phía trên điểm hiện tại (Z > z_coords[iz])
            # bisect_right: vị trí chèn → số hits phía trên = tổng - vị trí
            above_count = len(z_hits) - bisect.bisect_right(z_hits, z_coords[iz])
            if above_count % 2 == 1:
                dist = -dist  # Bên trong mesh
                inside_count += 1

            slice_data[iy, iz] = dist

    return slice_data, inside_count


def compute_sdf_grid(vertices, faces, resolution=3.0, padding=10.0, cancel_check=None):
    """
    Tính lưới Signed Distance Field 3D đa luồng bằng BVH + column ray casting.

    Tối ưu so với phiên bản đơn luồng:
    1. Column ray casting: O(nx*ny*logM) thay vì O(nx*ny*nz*logM)
    2. ThreadPoolExecutor: xử lý song song các lát X

    Tham số:
        vertices     : numpy array (N, 3) - tọa độ đỉnh mesh
        faces        : numpy array (M, 3) - chỉ số tam giác
        resolution   : float - bước lưới (mm)
        padding      : float - padding quanh mesh (mm)
        cancel_check : callable hoặc None - trả về True nếu cần huỷ

    Trả về:
        sdf_grid   : numpy array (Nx, Ny, Nz) - khoảng cách có dấu
        origin     : numpy array (3,) - góc nhỏ nhất lưới
        resolution : float - bước lưới
        grid_dims  : tuple (Nx, Ny, Nz)

    Raises:
        InterruptedError: khi cancel_check() trả về True
    """

    # --- Bước 1: Tính bounding box mở rộng ---
    grid_origin = vertices.min(axis=0) - padding
    max_bound = vertices.max(axis=0) + padding

    # --- Bước 2: Tạo lưới 3D ---
    grid_dims = np.ceil((max_bound - grid_origin) / resolution).astype(int) + 1
    nx, ny, nz = grid_dims

    total_points = int(nx) * int(ny) * int(nz)
    num_threads = min(os.cpu_count() or 4, int(nx))
    Logger.log("d", "SDF grid: %d x %d x %d = %d diem (signed, %d threads)",
               nx, ny, nz, total_points, num_threads)

    x_coords = np.linspace(grid_origin[0], grid_origin[0] + (nx - 1) * resolution, nx)
    y_coords = np.linspace(grid_origin[1], grid_origin[1] + (ny - 1) * resolution, ny)
    z_coords = np.linspace(grid_origin[2], grid_origin[2] + (nz - 1) * resolution, nz)

    # --- Bước 3: Xây BVH ---
    bvh_root = build_bvh(vertices, faces)

    # --- Bước 4: Tính SDF đa luồng ---
    # Chia lưới thành lát X, mỗi thread xử lý 1 lát
    # BVH là read-only → chia sẻ an toàn giữa các thread
    sdf_grid = np.zeros((nx, ny, nz), dtype=np.float64)
    total_inside = 0

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        # Submit tất cả lát X
        futures = {}
        for ix in range(nx):
            # Kiểm tra huỷ trước khi submit
            if cancel_check is not None and cancel_check():
                raise InterruptedError("SDF computation cancelled")

            future = executor.submit(
                _process_sdf_slice,
                ix, x_coords[ix], y_coords, z_coords,
                bvh_root, vertices, faces
            )
            futures[future] = ix

        # Thu thập kết quả theo thứ tự hoàn thành
        for future in futures:
            # Kiểm tra huỷ khi chờ kết quả
            if cancel_check is not None and cancel_check():
                executor.shutdown(wait=False)
                raise InterruptedError("SDF computation cancelled")

            slice_data, inside_count = future.result()
            ix = futures[future]
            sdf_grid[ix] = slice_data
            total_inside += inside_count

    Logger.log("d", "SDF signed: %d/%d diem ben trong mesh",
               total_inside, total_points)

    return sdf_grid, grid_origin, resolution, tuple(grid_dims)


# ==============================================================================
# PHẦN 5: NỘI SUY BA CHIỀU (TRILINEAR INTERPOLATION)
#
# Tra cứu SDF tại bất kỳ điểm nào (không chỉ điểm lưới) bằng cách
# nội suy tuyến tính giữa 8 đỉnh của ô lưới chứa điểm đó.
# Độ phức tạp: O(1) - cực nhanh, phù hợp cho truy vấn lặp lại.
# ==============================================================================

def _trilinear_interpolate(grid, point, origin, resolution, dims):
    """
    Nội suy ba chiều (trilinear interpolation) trên lưới 3D.

    Thuật toán:
    1. Chuyển tọa độ thế giới → tọa độ lưới (fractional index)
    2. Tìm 8 đỉnh ô lưới bao quanh
    3. Nội suy tuyến tính theo 3 trục: X → Y → Z

    Tham số:
        grid       : numpy array (Nx, Ny, Nz) - lưới SDF
        point      : numpy array (3,) - tọa độ cần tra cứu
        origin     : numpy array (3,) - góc nhỏ nhất lưới
        resolution : float - bước lưới
        dims       : tuple (Nx, Ny, Nz) - kích thước lưới

    Trả về:
        float - giá trị nội suy (khoảng cách xấp xỉ đến mesh)
    """

    # Chuyển sang tọa độ lưới (chỉ số thực - fractional index)
    grid_pos = (point - origin) / resolution

    # Kiểm tra ngoài phạm vi lưới → trả về inf (coi là an toàn)
    if (np.any(grid_pos < 0) or
            grid_pos[0] >= dims[0] - 1 or
            grid_pos[1] >= dims[1] - 1 or
            grid_pos[2] >= dims[2] - 1):
        return float('inf')

    # Chỉ số ô lưới (làm tròn xuống)
    i0 = grid_pos.astype(int)           # Góc nhỏ: [ix, iy, iz]
    i1 = i0 + 1                         # Góc lớn: [ix+1, iy+1, iz+1]

    # Trọng số nội suy (phần thập phân)
    frac = grid_pos - i0                # [fx, fy, fz] ∈ [0, 1)
    fx, fy, fz = frac

    # Lấy giá trị SDF tại 8 đỉnh ô lưới (c_xyz, x/y/z ∈ {0,1})
    c000 = grid[i0[0], i0[1], i0[2]]
    c001 = grid[i0[0], i0[1], i1[2]]
    c010 = grid[i0[0], i1[1], i0[2]]
    c011 = grid[i0[0], i1[1], i1[2]]
    c100 = grid[i1[0], i0[1], i0[2]]
    c101 = grid[i1[0], i0[1], i1[2]]
    c110 = grid[i1[0], i1[1], i0[2]]
    c111 = grid[i1[0], i1[1], i1[2]]

    # Nội suy theo trục X
    c00 = c000 * (1.0 - fx) + c100 * fx
    c01 = c001 * (1.0 - fx) + c101 * fx
    c10 = c010 * (1.0 - fx) + c110 * fx
    c11 = c011 * (1.0 - fx) + c111 * fx

    # Nội suy theo trục Y
    c0 = c00 * (1.0 - fy) + c10 * fy
    c1 = c01 * (1.0 - fy) + c11 * fy

    # Nội suy theo trục Z → kết quả cuối cùng
    return c0 * (1.0 - fz) + c1 * fz


# ==============================================================================
# PHẦN 6: COLLISION FIELD
#
# Lớp bọc (wrapper) cung cấp API đơn giản cho BranchRouter:
# - get_distance(point): khoảng cách xấp xỉ đến mesh
# - get_avoidance_vector(point, min_clearance): vector bẻ hướng tránh va chạm
# - Gradient SDF được tính trước bằng np.gradient() → tra cứu O(1)
# ==============================================================================

class CollisionField:
    """
    Trường va chạm: kết hợp SDF grid + gradient grid.
    Cung cấp tra cứu khoảng cách và hướng tránh va chạm cực nhanh (O(1)).

    Được tạo bởi CollisionField.build() sau khi SDF grid đã tính xong.
    Sử dụng bởi BranchRouter trong vòng lặp sinh nhánh cây.
    """

    def __init__(self, sdf_grid, grad_x, grad_y, grad_z, origin, resolution, dims):
        """
        Khởi tạo CollisionField.

        Tham số:
            sdf_grid   : numpy array (Nx,Ny,Nz) - lưới khoảng cách
            grad_x/y/z : numpy array (Nx,Ny,Nz) - gradient theo mỗi trục
            origin     : numpy array (3,) - góc nhỏ nhất lưới
            resolution : float - bước lưới
            dims       : tuple (Nx,Ny,Nz) - kích thước lưới
        """
        self._sdf = sdf_grid
        self._grad_x = grad_x
        self._grad_y = grad_y
        self._grad_z = grad_z
        self._origin = origin
        self._resolution = resolution
        self._dims = dims

    @staticmethod
    def build(vertices, faces, resolution=3.0, padding=10.0, cancel_check=None):
        """
        Factory method: tính SDF grid + gradient, trả về CollisionField.

        Tham số:
            vertices     : numpy array (N, 3)
            faces        : numpy array (M, 3)
            resolution   : float - bước lưới SDF (mm)
            padding      : float - padding quanh mesh (mm)
            cancel_check : callable hoặc None - trả về True nếu cần huỷ

        Trả về:
            CollisionField instance sẵn sàng tra cứu

        Raises:
            InterruptedError: khi cancel_check() trả về True
        """

        # Tính lưới SDF đơn luồng
        sdf_grid, origin, res, dims = compute_sdf_grid(
            vertices, faces, resolution, padding, cancel_check
        )

        # Tính gradient SDF bằng sai phân hữu hạn (finite differences)
        # np.gradient tự động dùng central differences → gradient mượt
        # Gradient chỉ hướng tăng khoảng cách = hướng tránh xa mesh
        grad_x = np.gradient(sdf_grid, res, axis=0)  # ∂SDF/∂x
        grad_y = np.gradient(sdf_grid, res, axis=1)  # ∂SDF/∂y
        grad_z = np.gradient(sdf_grid, res, axis=2)  # ∂SDF/∂z

        return CollisionField(sdf_grid, grad_x, grad_y, grad_z, origin, res, dims)

    def get_distance(self, point):
        """
        Tra cứu khoảng cách xấp xỉ từ điểm đến mesh (bằng nội suy SDF).

        Tham số:
            point : numpy array (3,) - tọa độ cần kiểm tra

        Trả về:
            float - khoảng cách (mm), inf nếu ngoài lưới
        """
        return _trilinear_interpolate(
            self._sdf, point, self._origin, self._resolution, self._dims
        )

    def get_avoidance_vector(self, point, min_clearance):
        """
        Tính vector bẻ hướng để tránh va chạm với mesh.

        SDF có dấu (signed):
        - distance > 0: bên ngoài mesh
        - distance < 0: BÊN TRONG mesh (cần đẩy ra mạnh)
        - distance >= min_clearance: an toàn, không cần bẻ hướng

        Thuật toán:
        1. Tra cứu SDF tại điểm → khoảng cách d (có dấu)
        2. Nếu d >= min_clearance → không cần bẻ hướng
        3. Tra cứu gradient SDF → hướng tăng khoảng cách (ra xa mesh)
        4. Tính cường độ:
           - Bên ngoài gần mesh (0 < d < min_clearance): strength nhẹ
           - Bên trong mesh (d < 0): strength = 1.0 (đẩy mạnh nhất)

        Tham số:
            point         : numpy array (3,) - tọa độ cần kiểm tra
            min_clearance : float - khoảng cách an toàn tối thiểu (mm)

        Trả về:
            avoidance : numpy array (3,) - vector bẻ hướng (0 nếu an toàn)
            distance  : float - khoảng cách hiện tại đến mesh (có dấu)
        """

        # Tra cứu khoảng cách (có dấu: âm = bên trong mesh)
        distance = self.get_distance(point)

        # An toàn: không cần bẻ hướng
        if distance >= min_clearance:
            return np.zeros(3), distance

        # Tra cứu gradient tại điểm (hướng ra xa mesh)
        gx = _trilinear_interpolate(
            self._grad_x, point, self._origin, self._resolution, self._dims
        )
        gy = _trilinear_interpolate(
            self._grad_y, point, self._origin, self._resolution, self._dims
        )
        gz = _trilinear_interpolate(
            self._grad_z, point, self._origin, self._resolution, self._dims
        )

        gradient = np.array([gx, gy, gz])
        grad_len = np.linalg.norm(gradient)

        # Chuẩn hóa gradient thành vector đơn vị
        if grad_len > 1e-6:
            gradient /= grad_len
        else:
            # Gradient quá nhỏ (vùng phẳng) → đẩy lên trên (hướng Z dương)
            gradient = np.array([0.0, 0.0, 1.0])

        # Cường độ bẻ hướng
        if distance < 0:
            # BÊN TRONG mesh → đẩy ra mạnh nhất
            strength = 1.0
        else:
            # Bên ngoài nhưng gần mesh → tỷ lệ nghịch với khoảng cách
            strength = (min_clearance - distance) / min_clearance
            strength = np.clip(strength, 0.0, 1.0)

        # Vector bẻ hướng = hướng × cường độ
        # Bên trong mesh: magnitude = 1.0 (chi phối hoàn toàn direction)
        # Bên ngoài gần mesh: magnitude ≤ 0.5 (nhẹ nhàng bẻ hướng)
        if distance < 0:
            avoidance = gradient * strength * 1.0
        else:
            avoidance = gradient * strength * 0.5

        return avoidance, distance
