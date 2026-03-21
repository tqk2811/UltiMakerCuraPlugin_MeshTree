# ==============================================================================
# Module: Tạo mesh ống trụ từ skeleton cây (Tree Mesh Builder)
#
# Chuyển đổi bộ xương cây (skeleton = nodes + edges) thành lưới tam giác 3D
# có thể render và slice được trong Cura.
#
# Mỗi cạnh (edge) trong skeleton → 1 hình nón cụt (truncated cone / frustum):
# - Đầu nhỏ (tip): bán kính nhỏ (gần overhang)
# - Đầu lớn (base): bán kính lớn hơn (gần bàn in, sau merge)
# - Bề mặt xấp xỉ bằng N mặt tứ giác (quads), mỗi quad = 2 tam giác
#
# Đầu vào: skeleton (nodes, edges) từ BranchRouter
# Đầu ra: MeshData cho Cura (vertices + indices + normals)
#
# Luồng thực thi: Chạy trong worker thread (bên trong Job.run())
# ==============================================================================

import numpy as np
from UM.Mesh.MeshData import MeshData


# ==============================================================================
# PHẦN 1: SINH HÌNH NÓN CỤT (FRUSTUM) CHO MỖI CẠNH
#
# Mỗi cạnh trong skeleton nối 2 nút có vị trí (p1, p2) và bán kính (r1, r2).
# Hình nón cụt = 2 hình tròn (tại p1 và p2) nối bằng mặt bao.
#
# Để tạo mesh:
# 1. Tìm 2 vector vuông góc với trục p1→p2 (hệ tọa độ cục bộ)
# 2. Sinh N đỉnh trên mỗi hình tròn (đặt đều quanh chu vi)
# 3. Nối thành N quads → 2N tam giác
# ==============================================================================

def _build_frustum(p1, p2, r1, r2, segments):
    """
    Sinh mesh hình nón cụt (frustum) giữa 2 điểm.

    Thuật toán:
    1. Tính trục (direction) từ p1 đến p2
    2. Tìm 2 vector vuông góc (perp1, perp2) bằng tích chéo
    3. Sinh N đỉnh trên mỗi vòng tròn đầu mút
    4. Nối 2 vòng thành dải tam giác (triangle strip)

    Tham số:
        p1, p2   : numpy array (3,) - 2 đầu mút hình nón
        r1, r2   : float - bán kính tại p1 và p2
        segments : int - số mặt bao (8 → tiết diện bát giác)

    Trả về:
        vertices : numpy array (2*segments, 3) - tọa độ đỉnh
        faces    : numpy array (2*segments, 3) - chỉ số tam giác
    """

    # --- Tính trục và hệ tọa độ cục bộ ---
    direction = p2 - p1
    length = np.linalg.norm(direction)

    # Bỏ qua cạnh suy biến (2 đầu trùng nhau)
    if length < 1e-6:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int32)

    # Chuẩn hóa trục
    direction /= length

    # Tìm vector vuông góc thứ nhất (perp1)
    # Dùng tích chéo với trục Z (hoặc X nếu direction gần song song Z)
    if abs(direction[2]) < 0.9:
        ref = np.array([0.0, 0.0, 1.0])
    else:
        ref = np.array([1.0, 0.0, 0.0])

    perp1 = np.cross(direction, ref)
    perp1 /= np.linalg.norm(perp1)

    # Vector vuông góc thứ hai
    perp2 = np.cross(direction, perp1)
    # perp2 đã là vector đơn vị (vì direction và perp1 đều đơn vị)

    # --- Sinh đỉnh trên 2 vòng tròn ---
    # Góc chia đều quanh chu vi
    angles = np.linspace(0.0, 2.0 * np.pi, segments, endpoint=False)
    cos_a = np.cos(angles)  # shape (segments,)
    sin_a = np.sin(angles)  # shape (segments,)

    vertices = np.zeros((2 * segments, 3), dtype=np.float64)

    # Vòng tròn dưới (tại p1, bán kính r1)
    for i in range(segments):
        offset = r1 * (cos_a[i] * perp1 + sin_a[i] * perp2)
        vertices[i] = p1 + offset

    # Vòng tròn trên (tại p2, bán kính r2)
    for i in range(segments):
        offset = r2 * (cos_a[i] * perp1 + sin_a[i] * perp2)
        vertices[segments + i] = p2 + offset

    # --- Sinh tam giác nối 2 vòng ---
    # Mỗi cặp đỉnh liền kề trên 2 vòng tạo thành 1 quad = 2 triangles
    faces = np.zeros((2 * segments, 3), dtype=np.int32)
    for i in range(segments):
        j = (i + 1) % segments  # Đỉnh kế tiếp (vòng lại)

        # Tam giác 1: bottom[i] → bottom[j] → top[j]
        faces[2 * i] = [i, j, segments + j]

        # Tam giác 2: bottom[i] → top[j] → top[i]
        faces[2 * i + 1] = [i, segments + j, segments + i]

    return vertices, faces


# ==============================================================================
# PHẦN 2: SINH NẮP (CAP) CHO ĐẦU NHÁNH
#
# Mỗi đầu nhánh (tip) và chân cây (base) cần nắp để mesh kín nước.
# Nắp = hình quạt (fan triangulation) từ tâm ra các đỉnh chu vi.
# ==============================================================================

def _build_cap(center, radius, direction, segments, flip=False):
    """
    Sinh nắp tròn (disc) tại 1 đầu nhánh.

    Tham số:
        center    : numpy array (3,) - tâm nắp
        radius    : float - bán kính nắp
        direction : numpy array (3,) - hướng pháp tuyến nắp
        segments  : int - số mặt tam giác
        flip      : bool - lật hướng tam giác (cho nắp đáy)

    Trả về:
        vertices : numpy array (segments+1, 3) - đỉnh (tâm + chu vi)
        faces    : numpy array (segments, 3) - tam giác hình quạt
    """

    dir_norm = direction / np.linalg.norm(direction) if np.linalg.norm(direction) > 1e-6 else np.array([0, 0, 1.0])

    # Hệ tọa độ cục bộ
    if abs(dir_norm[2]) < 0.9:
        ref = np.array([0.0, 0.0, 1.0])
    else:
        ref = np.array([1.0, 0.0, 0.0])

    perp1 = np.cross(dir_norm, ref)
    perp1 /= np.linalg.norm(perp1)
    perp2 = np.cross(dir_norm, perp1)

    angles = np.linspace(0.0, 2.0 * np.pi, segments, endpoint=False)

    # Đỉnh: tâm + chu vi
    vertices = np.zeros((segments + 1, 3), dtype=np.float64)
    vertices[0] = center  # Tâm nắp

    for i in range(segments):
        offset = radius * (np.cos(angles[i]) * perp1 + np.sin(angles[i]) * perp2)
        vertices[i + 1] = center + offset

    # Tam giác hình quạt: tâm → chu vi[i] → chu vi[i+1]
    faces = np.zeros((segments, 3), dtype=np.int32)
    for i in range(segments):
        j = (i + 1) % segments
        if flip:
            faces[i] = [0, j + 1, i + 1]  # Ngược chiều → pháp tuyến hướng xuống
        else:
            faces[i] = [0, i + 1, j + 1]  # Thuận chiều → pháp tuyến hướng lên

    return vertices, faces


# ==============================================================================
# PHẦN 3: LẮP GHÉP TOÀN BỘ CÂY
#
# Ghép tất cả frustums và caps thành 1 mesh liền.
# Tính pháp tuyến mặt (face normals) cho rendering.
# Xuất ra MeshData cho Cura.
# ==============================================================================

def build_tree_mesh(all_nodes, all_edges, segments=8):
    """
    Tạo mesh 3D hoàn chỉnh từ skeleton cây support.

    Quy trình:
    1. Với mỗi cạnh trong skeleton: sinh 1 frustum (hình nón cụt)
    2. Tìm các nút tip (không có cạnh đi vào) → đóng nắp trên
    3. Tìm các nút base (Z ≈ 0) → đóng nắp dưới
    4. Ghép tất cả vertices/faces, tính normals
    5. Tạo MeshData

    Tham số:
        all_nodes : list of (position, radius) - nút skeleton
        all_edges : list of (idx1, idx2) - cạnh nối
        segments  : int - số mặt bao cho ống trụ (8 = bát giác)

    Trả về:
        MeshData - mesh lưới tam giác cho Cura
    """

    # Trường hợp đặc biệt: skeleton rỗng
    if not all_nodes or not all_edges:
        # Trả về mesh rỗng tối thiểu (1 tam giác suy biến)
        verts = np.zeros((3, 3), dtype=np.float32)
        return MeshData(vertices=verts)

    # --- Thu thập tất cả vertices và faces ---
    all_verts_list = []   # Danh sách các mảng vertices
    all_faces_list = []   # Danh sách các mảng faces
    vertex_offset = 0     # Offset chỉ số khi ghép

    # --- Bước 1: Sinh frustum cho mỗi cạnh ---
    for edge in all_edges:
        idx1, idx2 = edge
        p1, r1 = all_nodes[idx1]
        p2, r2 = all_nodes[idx2]

        # Chuyển position sang numpy array nếu chưa phải
        p1 = np.asarray(p1, dtype=np.float64)
        p2 = np.asarray(p2, dtype=np.float64)

        # Sinh mesh frustum
        verts, faces = _build_frustum(p1, p2, r1, r2, segments)

        if len(verts) == 0:
            continue

        # Dịch chỉ số faces theo offset hiện tại
        faces_offset = faces + vertex_offset
        all_verts_list.append(verts)
        all_faces_list.append(faces_offset)
        vertex_offset += len(verts)

    # --- Bước 2: Tìm nút tip và base để đóng nắp ---
    # Nút tip: chỉ có cạnh đi ra (là cha), không có cạnh đi vào (không là con)
    # Nút base: Z gần 0
    child_set = set()   # Tập nút là "con" (đầu nhận cạnh)
    parent_set = set()  # Tập nút là "cha" (đầu phát cạnh)

    for idx1, idx2 in all_edges:
        parent_set.add(idx1)
        child_set.add(idx2)

    # Nút tip = nút cha mà không phải con (gốc của cây, tức ngọn support)
    # Trong cấu trúc bottom-up: edges đi từ trên xuống, nên "cha" ở trên
    tip_nodes = parent_set - child_set
    # Nút base = nút con mà không phải cha (lá, tức chân cây)
    base_nodes = child_set - parent_set

    # Đóng nắp cho tip nodes
    for tip_idx in tip_nodes:
        pos, radius = all_nodes[tip_idx]
        pos = np.asarray(pos, dtype=np.float64)

        # Hướng nắp: hướng lên trên (+Z) cho đỉnh cây
        cap_verts, cap_faces = _build_cap(
            pos, radius, np.array([0.0, 0.0, 1.0]), segments, flip=False
        )
        cap_faces_offset = cap_faces + vertex_offset
        all_verts_list.append(cap_verts)
        all_faces_list.append(cap_faces_offset)
        vertex_offset += len(cap_verts)

    # Đóng nắp cho base nodes
    for base_idx in base_nodes:
        pos, radius = all_nodes[base_idx]
        pos = np.asarray(pos, dtype=np.float64)

        # Hướng nắp: hướng xuống dưới (-Z) cho chân cây
        cap_verts, cap_faces = _build_cap(
            pos, radius, np.array([0.0, 0.0, -1.0]), segments, flip=True
        )
        cap_faces_offset = cap_faces + vertex_offset
        all_verts_list.append(cap_verts)
        all_faces_list.append(cap_faces_offset)
        vertex_offset += len(cap_verts)

    # --- Bước 3: Ghép tất cả thành 1 mesh ---
    if not all_verts_list:
        verts = np.zeros((3, 3), dtype=np.float32)
        return MeshData(vertices=verts)

    # Ghép vertices và faces
    combined_verts = np.vstack(all_verts_list).astype(np.float32)   # (V, 3)
    combined_faces = np.vstack(all_faces_list).astype(np.int32)     # (F, 3)

    # --- Bước 4: Tính pháp tuyến mặt (face normals) → gán cho vertices ---
    # Với triangle soup: mỗi vertex chỉ thuộc 1 face → flat shading
    # Ta chuyển sang triangle soup format để Cura hiển thị đúng

    # Lấy tọa độ đỉnh theo chỉ số faces
    v0 = combined_verts[combined_faces[:, 0]]  # (F, 3)
    v1 = combined_verts[combined_faces[:, 1]]  # (F, 3)
    v2 = combined_verts[combined_faces[:, 2]]  # (F, 3)

    # Triangle soup: mỗi tam giác có 3 đỉnh riêng biệt
    num_faces = len(combined_faces)
    soup_verts = np.zeros((num_faces * 3, 3), dtype=np.float32)
    soup_verts[0::3] = v0
    soup_verts[1::3] = v1
    soup_verts[2::3] = v2

    # Tính pháp tuyến mặt
    edge1 = v1 - v0  # (F, 3)
    edge2 = v2 - v0  # (F, 3)
    face_normals = np.cross(edge1, edge2)  # (F, 3)

    # Chuẩn hóa pháp tuyến
    norms_length = np.linalg.norm(face_normals, axis=1, keepdims=True)
    norms_length = np.maximum(norms_length, 1e-10)
    face_normals = face_normals / norms_length

    # Gán cùng pháp tuyến cho 3 đỉnh của mỗi tam giác (flat shading)
    soup_normals = np.zeros((num_faces * 3, 3), dtype=np.float32)
    soup_normals[0::3] = face_normals
    soup_normals[1::3] = face_normals
    soup_normals[2::3] = face_normals

    # --- Bước 5: Tạo MeshData ---
    # Không cần indices vì đã dùng triangle soup format
    mesh_data = MeshData(vertices=soup_verts, normals=soup_normals)

    return mesh_data
