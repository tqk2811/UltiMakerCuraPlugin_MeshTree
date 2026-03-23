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
    #
    # Winding order đảo ngược so với right-handed thông thường vì:
    # Mesh được build trong Z-up left-handed, sau đó swap Y↔Z (det=-1)
    # về Y-up right-handed cho Cura. Swap đảo winding → cần xây ngược
    # để sau swap ra đúng chiều (CCW = outward trong right-handed).
    faces = np.zeros((2 * segments, 3), dtype=np.int32)
    for i in range(segments):
        j = (i + 1) % segments  # Đỉnh kế tiếp (vòng lại)

        # Tam giác 1: bottom[i] → top[j] → bottom[j]  (winding đảo)
        faces[2 * i] = [i, segments + j, j]

        # Tam giác 2: bottom[i] → top[i] → top[j]  (winding đảo)
        faces[2 * i + 1] = [i, segments + i, segments + j]

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
    # Winding đảo cho left-handed Z-up → sau swap Y↔Z ra đúng chiều
    faces = np.zeros((segments, 3), dtype=np.int32)
    for i in range(segments):
        j = (i + 1) % segments
        if flip:
            faces[i] = [0, i + 1, j + 1]  # Đảo: pháp tuyến hướng xuống sau swap
        else:
            faces[i] = [0, j + 1, i + 1]  # Đảo: pháp tuyến hướng lên sau swap

    return vertices, faces


# ==============================================================================
# PHẦN 3: SINH HÌNH CẦU (SPHERE) TẠI ĐIỂM GIAO NHÁNH
#
# Khi 2+ nhánh gặp nhau (merge/junction), giữa các frustum có khe hở.
# Đặt 1 hình cầu cùng bán kính tại điểm giao để lấp đầy khe hở,
# tạo ngoại hình mượt mà tự nhiên hơn.
#
# Hình cầu được sinh bằng UV sphere: chia theo kinh tuyến (longitude)
# và vĩ tuyến (latitude), tạo lưới tam giác bao phủ toàn bộ bề mặt cầu.
# ==============================================================================

def _build_sphere(center, radius, segments):
    """
    Sinh mesh hình cầu (UV sphere) tại vị trí cho trước.

    Tham số:
        center   : numpy array (3,) - tâm hình cầu
        radius   : float - bán kính
        segments : int - số chia theo kinh tuyến (và vĩ tuyến = segments//2)

    Trả về:
        vertices : numpy array (V, 3) - tọa độ đỉnh
        faces    : numpy array (F, 3) - chỉ số tam giác
    """
    # Số chia vĩ tuyến (rings) = nửa segments, tối thiểu 3
    rings = max(3, segments // 2)
    sectors = segments  # Số chia kinh tuyến

    # Sinh đỉnh
    # Đỉnh cực bắc (top) và cực nam (bottom) + các vòng vĩ tuyến
    vertices = []

    # Cực bắc (+Z)
    vertices.append(center + np.array([0.0, 0.0, radius]))

    # Các vòng vĩ tuyến (từ trên xuống dưới, trừ 2 cực)
    for i in range(1, rings):
        phi = np.pi * i / rings  # Góc từ cực bắc (0 → π)
        z = radius * np.cos(phi)
        r_ring = radius * np.sin(phi)
        for j in range(sectors):
            theta = 2.0 * np.pi * j / sectors
            x = r_ring * np.cos(theta)
            y = r_ring * np.sin(theta)
            vertices.append(center + np.array([x, y, z]))

    # Cực nam (-Z)
    vertices.append(center + np.array([0.0, 0.0, -radius]))

    vertices = np.array(vertices, dtype=np.float64)

    # Sinh tam giác
    faces = []

    # Tam giác nối cực bắc với vòng đầu tiên
    for j in range(sectors):
        j_next = (j + 1) % sectors
        # Winding đảo cho left-handed Z-up (giống frustum)
        faces.append([0, 1 + j_next, 1 + j])

    # Tam giác giữa các vòng vĩ tuyến
    for i in range(rings - 2):
        ring_start = 1 + i * sectors
        next_ring_start = 1 + (i + 1) * sectors
        for j in range(sectors):
            j_next = (j + 1) % sectors
            # Quad = 2 tam giác (winding đảo)
            v1 = ring_start + j
            v2 = ring_start + j_next
            v3 = next_ring_start + j_next
            v4 = next_ring_start + j
            faces.append([v1, v3, v2])
            faces.append([v1, v4, v3])

    # Tam giác nối vòng cuối với cực nam
    south_idx = len(vertices) - 1
    last_ring_start = 1 + (rings - 2) * sectors
    for j in range(sectors):
        j_next = (j + 1) % sectors
        # Winding đảo
        faces.append([last_ring_start + j, last_ring_start + j_next, south_idx])

    faces = np.array(faces, dtype=np.int32)
    return vertices, faces


# ==============================================================================
# PHẦN 4: LẮP GHÉP TOÀN BỘ CÂY
#
# Ghép tất cả frustums và caps thành 1 mesh liền.
# Tính pháp tuyến mặt (face normals) cho rendering.
# Xuất ra MeshData cho Cura.
# ==============================================================================

def build_tree_mesh(all_nodes, all_edges, segments=8,
                    base_brim_multiplier=3.0, base_brim_height=0.5,
                    cancel_check=None):
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
    for edge_i, edge in enumerate(all_edges):
        if cancel_check is not None and cancel_check():
            verts = np.zeros((3, 3), dtype=np.float32)
            return MeshData(vertices=verts)
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

    # --- Bước 2: Tìm nút tip, base, junction để đóng nắp và đặt cầu ---
    child_set = set()   # Tập nút là "con" (đầu nhận cạnh)
    parent_set = set()  # Tập nút là "cha" (đầu phát cạnh)
    # Đếm số cạnh đi vào mỗi nút (incoming edges)
    incoming_count = {}  # node_idx → số cạnh đi vào

    for idx1, idx2 in all_edges:
        parent_set.add(idx1)
        child_set.add(idx2)
        incoming_count[idx2] = incoming_count.get(idx2, 0) + 1

    # Nút nối (vừa là child vừa là parent): đặt hình cầu tại các điểm
    # bẻ góc và giao nhánh để lấp khe hở giữa các frustum
    mid_nodes = child_set & parent_set  # Nút giữa đường (bẻ góc)
    for node_idx in mid_nodes:
        pos, radius = all_nodes[node_idx]
        pos = np.asarray(pos, dtype=np.float64)
        sphere_verts, sphere_faces = _build_sphere(pos, radius, segments)
        if len(sphere_verts) > 0:
            sphere_faces_offset = sphere_faces + vertex_offset
            all_verts_list.append(sphere_verts)
            all_faces_list.append(sphere_faces_offset)
            vertex_offset += len(sphere_verts)

    # Nút tip = nút cha mà không phải con (gốc của cây, tức ngọn support)
    # Trong cấu trúc bottom-up: edges đi từ trên xuống, nên "cha" ở trên
    tip_nodes = parent_set - child_set
    # Nút base = nút con mà không phải cha (lá, tức chân cây)
    base_nodes = child_set - parent_set

    # Đóng nắp cho tip nodes (bán kính ≈ 0 → nắp rất nhỏ, đỉnh nón)
    for tip_idx in tip_nodes:
        pos, radius = all_nodes[tip_idx]
        pos = np.asarray(pos, dtype=np.float64)

        cap_verts, cap_faces = _build_cap(
            pos, radius, np.array([0.0, 0.0, 1.0]), segments, flip=False
        )
        cap_faces_offset = cap_faces + vertex_offset
        all_verts_list.append(cap_verts)
        all_faces_list.append(cap_faces_offset)
        vertex_offset += len(cap_verts)

    # Đóng nắp + đế chống đổ cho base nodes
    # Đế (brim) = hình nón cụt ngắn mở rộng từ bán kính nhánh,
    # tạo chân rộng ổn định trên bàn in.

    for base_idx in base_nodes:
        pos, radius = all_nodes[base_idx]
        pos = np.asarray(pos, dtype=np.float64)

        # Tạo đế chống đổ: frustum từ (pos) xuống (pos - brim_height)
        # với bán kính mở rộng dần
        brim_radius = radius * base_brim_multiplier
        brim_bottom = pos.copy()
        brim_bottom[2] = max(0.0, pos[2] - base_brim_height)

        # Frustum: đầu trên = bán kính nhánh, đầu dưới = bán kính brim
        brim_verts, brim_faces = _build_frustum(
            pos, brim_bottom, radius, brim_radius, segments
        )
        if len(brim_verts) > 0:
            brim_faces_offset = brim_faces + vertex_offset
            all_verts_list.append(brim_verts)
            all_faces_list.append(brim_faces_offset)
            vertex_offset += len(brim_verts)

        # Nắp đáy của đế (đĩa tròn rộng tại Z=0)
        cap_verts, cap_faces = _build_cap(
            brim_bottom, brim_radius, np.array([0.0, 0.0, -1.0]), segments, flip=True
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
