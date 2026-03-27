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
# Tại các điểm bẻ góc (bend nodes, góc > 15°):
# - Thay vì hình cầu (Plan3 gốc), dùng ống Bézier mượt để lấp khe hở
# - Cubic Bézier curve qua điểm bẻ, tạo transition mượt giữa 2 frustum
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
# ==============================================================================

def _build_frustum(p1, p2, r1, r2, segments):
    """
    Sinh mesh hình nón cụt (frustum) giữa 2 điểm.

    Tham số:
        p1, p2   : numpy array (3,) - 2 đầu mút hình nón
        r1, r2   : float - bán kính tại p1 và p2
        segments : int - số mặt bao (8 → tiết diện bát giác)

    Trả về:
        vertices : numpy array (2*segments, 3)
        faces    : numpy array (2*segments, 3) dtype int32
    """
    direction = p2 - p1
    length = np.linalg.norm(direction)

    if length < 1e-6:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int32)

    direction /= length

    if abs(direction[2]) < 0.9:
        ref = np.array([0.0, 0.0, 1.0])
    else:
        ref = np.array([1.0, 0.0, 0.0])

    perp1 = np.cross(direction, ref)
    perp1 /= np.linalg.norm(perp1)
    perp2 = np.cross(direction, perp1)

    angles = np.linspace(0.0, 2.0 * np.pi, segments, endpoint=False)
    cos_a = np.cos(angles)
    sin_a = np.sin(angles)

    vertices = np.zeros((2 * segments, 3), dtype=np.float64)

    for i in range(segments):
        offset = r1 * (cos_a[i] * perp1 + sin_a[i] * perp2)
        vertices[i] = p1 + offset

    for i in range(segments):
        offset = r2 * (cos_a[i] * perp1 + sin_a[i] * perp2)
        vertices[segments + i] = p2 + offset

    faces = np.zeros((2 * segments, 3), dtype=np.int32)
    for i in range(segments):
        j = (i + 1) % segments
        # Winding đảo cho left-handed Z-up (sau swap Y↔Z ra đúng CCW)
        faces[2 * i] = [i, segments + j, j]
        faces[2 * i + 1] = [i, segments + i, segments + j]

    return vertices, faces


# ==============================================================================
# PHẦN 2: SINH NẮP (CAP) CHO ĐẦU NHÁNH
# ==============================================================================

def _build_cap(center, radius, direction, segments, flip=False):
    """
    Sinh nắp tròn (disc) tại 1 đầu nhánh.

    Tham số:
        center    : numpy array (3,)
        radius    : float
        direction : numpy array (3,) - pháp tuyến nắp
        segments  : int
        flip      : bool - lật hướng tam giác

    Trả về:
        vertices : numpy array (segments+1, 3)
        faces    : numpy array (segments, 3)
    """
    dir_norm = direction / np.linalg.norm(direction) if np.linalg.norm(direction) > 1e-6 else np.array([0, 0, 1.0])

    if abs(dir_norm[2]) < 0.9:
        ref = np.array([0.0, 0.0, 1.0])
    else:
        ref = np.array([1.0, 0.0, 0.0])

    perp1 = np.cross(dir_norm, ref)
    perp1 /= np.linalg.norm(perp1)
    perp2 = np.cross(dir_norm, perp1)

    angles = np.linspace(0.0, 2.0 * np.pi, segments, endpoint=False)
    vertices = np.zeros((segments + 1, 3), dtype=np.float64)
    vertices[0] = center
    for i in range(segments):
        vertices[i + 1] = center + radius * (np.cos(angles[i]) * perp1 + np.sin(angles[i]) * perp2)

    faces = np.zeros((segments, 3), dtype=np.int32)
    for i in range(segments):
        j = (i + 1) % segments
        if not flip:
            faces[i] = [0, i + 1, j + 1]
        else:
            faces[i] = [0, j + 1, i + 1]

    return vertices, faces


# ==============================================================================
# PHẦN 3: ỐNG BÉZIER TẠI ĐIỂM BẺ GÓC (thay thế hình cầu)
#
# Khi 2 frustum gặp nhau tại góc > 15°, có khe hở/giao thoa tại điểm nối.
# Thay vì đặt UV sphere (Plan3 gốc), dùng ống Bézier cubic để lấp mượt.
#
# Với mỗi cặp (incoming_edge → bend_node → outgoing_edge):
# - P0 = bend_pos - d_in * L  (điểm trước bend, nằm trên incoming edge)
# - P1 = P2 = bend_pos        (control points tại bend)
# - P3 = bend_pos + d_out * L (điểm sau bend, nằm trên outgoing edge)
# → Cubic Bézier tạo curve tiếp xúc với cả 2 frustum tại 2 đầu,
#   đi qua điểm bẻ, tạo hiệu ứng bẻ góc mượt mà tự nhiên.
# ==============================================================================

def _build_bend_bezier(p_from, p_bend, p_to, radius, segments):
    """
    Sinh ống Bézier mượt tại điểm bẻ góc.

    Tham số:
        p_from  : numpy array (3,) - nút trước bend (trên incoming edge)
        p_bend  : numpy array (3,) - nút tại điểm bẻ
        p_to    : numpy array (3,) - nút sau bend (trên outgoing edge)
        radius  : float - bán kính tại bend node
        segments: int - số cạnh cross-section

    Trả về:
        vertices : numpy array (N*segments, 3)
        faces    : numpy array (2*(N-1)*segments, 3) dtype int32
    """
    d_in = p_bend - p_from
    l_in = np.linalg.norm(d_in)
    if l_in < 1e-6:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int32)
    d_in /= l_in

    d_out = p_to - p_bend
    l_out = np.linalg.norm(d_out)
    if l_out < 1e-6:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int32)
    d_out /= l_out

    # Cubic Bézier: P0 → P1=P2=bend → P3
    L = max(min(l_in, l_out) * 0.4, 0.3)
    P0 = p_bend - d_in * L
    P1 = p_bend
    P2 = p_bend
    P3 = p_bend + d_out * L

    # Sample đủ điểm dọc curve
    n_samples = max(5, int(np.linalg.norm(P3 - P0) / 0.5) + 1)

    rings = []  # list of (segments, 3) arrays
    for si in range(n_samples):
        t = si / (n_samples - 1)
        u = 1.0 - t
        # Vị trí trên cubic Bézier
        pos = u**3 * P0 + 3*u**2*t * P1 + 3*u*t**2 * P2 + t**3 * P3
        # Tangent (đạo hàm)
        tangent = 3*u**2 * (P1 - P0) + 6*u*t * (P2 - P1) + 3*t**2 * (P3 - P2)
        tl = np.linalg.norm(tangent)
        if tl < 1e-6:
            tangent = d_out if t > 0.5 else d_in
        else:
            tangent /= tl

        # Xây ring vuông góc với tangent
        if abs(tangent[2]) < 0.9:
            ref = np.array([0.0, 0.0, 1.0])
        else:
            ref = np.array([1.0, 0.0, 0.0])
        perp1 = np.cross(tangent, ref)
        pl = np.linalg.norm(perp1)
        if pl < 1e-6:
            continue
        perp1 /= pl
        perp2 = np.cross(tangent, perp1)

        angles = np.linspace(0.0, 2.0 * np.pi, segments, endpoint=False)
        ring = np.zeros((segments, 3), dtype=np.float64)
        for i, a in enumerate(angles):
            ring[i] = pos + radius * (np.cos(a) * perp1 + np.sin(a) * perp2)
        rings.append(ring)

    if len(rings) < 2:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int32)

    n_rings = len(rings)
    all_verts = np.vstack(rings)  # (n_rings * segments, 3)

    faces = []
    for ri in range(n_rings - 1):
        base0 = ri * segments
        base1 = (ri + 1) * segments
        for i in range(segments):
            j = (i + 1) % segments
            # Winding đảo (nhất quán với _build_frustum)
            faces.append([base0 + i, base1 + j, base0 + j])
            faces.append([base0 + i, base1 + i, base1 + j])

    if not faces:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int32)

    return all_verts, np.array(faces, dtype=np.int32)


# ==============================================================================
# PHẦN 4: LẮP GHÉP TOÀN BỘ CÂY
# ==============================================================================

def build_tree_mesh(all_nodes, all_edges, segments=8,
                    base_brim_multiplier=3.0, base_brim_height=0.5,
                    cancel_check=None):
    """
    Tạo mesh 3D hoàn chỉnh từ skeleton cây support.

    Quy trình:
    1. Mỗi cạnh → 1 frustum (hình nón cụt)
    2. Tại bend nodes (góc > 15°) → ống Bézier thay thế hình cầu
    3. Tip nodes → đóng nắp trên
    4. Base nodes → đế brim + nắp đáy
    5. Ghép tất cả, tính normals, xuất MeshData

    Tham số:
        all_nodes           : list of (position, radius)
        all_edges           : list of (idx1, idx2)
        segments            : int - số mặt bao (8 = bát giác)
        base_brim_multiplier: float - hệ số mở rộng đế
        base_brim_height    : float - chiều cao đế (mm)
        cancel_check        : callable hoặc None

    Trả về:
        MeshData
    """

    if not all_nodes or not all_edges:
        verts = np.zeros((3, 3), dtype=np.float32)
        return MeshData(vertices=verts)

    all_verts_list = []
    all_faces_list = []
    vertex_offset = 0

    # --- Bước 1: Frustum cho mỗi cạnh ---
    for edge in all_edges:
        if cancel_check is not None and cancel_check():
            verts = np.zeros((3, 3), dtype=np.float32)
            return MeshData(vertices=verts)

        idx1, idx2 = edge
        p1 = np.asarray(all_nodes[idx1][0], dtype=np.float64)
        p2 = np.asarray(all_nodes[idx2][0], dtype=np.float64)
        r1 = all_nodes[idx1][1]
        r2 = all_nodes[idx2][1]

        verts, faces = _build_frustum(p1, p2, r1, r2, segments)
        if len(verts) == 0:
            continue

        all_verts_list.append(verts)
        all_faces_list.append(faces + vertex_offset)
        vertex_offset += len(verts)

    # --- Bước 2: Phân tích topology để tìm bend_nodes ---
    child_set = set()
    parent_set = set()
    incoming_edges = {}
    outgoing_edges = {}

    for idx1, idx2 in all_edges:
        parent_set.add(idx1)
        child_set.add(idx2)
        outgoing_edges.setdefault(idx1, []).append(idx2)
        incoming_edges.setdefault(idx2, []).append(idx1)

    mid_nodes = child_set & parent_set
    _COS_BEND_THRESHOLD = np.cos(np.radians(15.0))

    # Tìm bend_nodes: mid_nodes có ít nhất 1 cặp (incoming, outgoing) bẻ > 15°
    bend_nodes = set()
    for node_idx in mid_nodes:
        pos = np.asarray(all_nodes[node_idx][0], dtype=np.float64)
        froms = incoming_edges.get(node_idx, [])
        tos = outgoing_edges.get(node_idx, [])
        for f in froms:
            d_in = pos - np.asarray(all_nodes[f][0], dtype=np.float64)
            l_in = np.linalg.norm(d_in)
            if l_in < 1e-6:
                continue
            d_in /= l_in
            for t in tos:
                d_out = np.asarray(all_nodes[t][0], dtype=np.float64) - pos
                l_out = np.linalg.norm(d_out)
                if l_out < 1e-6:
                    continue
                d_out /= l_out
                if np.dot(d_in, d_out) < _COS_BEND_THRESHOLD:
                    bend_nodes.add(node_idx)
                    break
            if node_idx in bend_nodes:
                break

    # --- Bước 3: Bézier tại bend_nodes (thay thế hình cầu) ---
    for node_idx in bend_nodes:
        if cancel_check is not None and cancel_check():
            verts = np.zeros((3, 3), dtype=np.float32)
            return MeshData(vertices=verts)

        p_bend = np.asarray(all_nodes[node_idx][0], dtype=np.float64)
        radius = all_nodes[node_idx][1]
        froms = incoming_edges.get(node_idx, [])
        tos = outgoing_edges.get(node_idx, [])

        for f_idx in froms:
            p_from = np.asarray(all_nodes[f_idx][0], dtype=np.float64)
            for t_idx in tos:
                p_to = np.asarray(all_nodes[t_idx][0], dtype=np.float64)

                # Kiểm tra cặp này có bẻ góc không
                d_in = p_bend - p_from
                d_out = p_to - p_bend
                l_in = np.linalg.norm(d_in)
                l_out = np.linalg.norm(d_out)
                if l_in < 1e-6 or l_out < 1e-6:
                    continue
                if np.dot(d_in / l_in, d_out / l_out) >= _COS_BEND_THRESHOLD:
                    continue  # Không bẻ góc, bỏ qua

                bend_v, bend_f = _build_bend_bezier(p_from, p_bend, p_to, radius, segments)
                if len(bend_v) == 0:
                    continue

                all_verts_list.append(bend_v)
                all_faces_list.append(bend_f + vertex_offset)
                vertex_offset += len(bend_v)

    # --- Bước 4: Nắp tip và đế base ---
    tip_nodes = parent_set - child_set
    base_nodes = child_set - parent_set

    for tip_idx in tip_nodes:
        pos = np.asarray(all_nodes[tip_idx][0], dtype=np.float64)
        radius = all_nodes[tip_idx][1]

        cap_v, cap_f = _build_cap(pos, radius, np.array([0.0, 0.0, 1.0]), segments, flip=False)
        all_verts_list.append(cap_v)
        all_faces_list.append(cap_f + vertex_offset)
        vertex_offset += len(cap_v)

    for base_idx in base_nodes:
        pos = np.asarray(all_nodes[base_idx][0], dtype=np.float64)
        radius = all_nodes[base_idx][1]

        brim_radius = radius * base_brim_multiplier
        brim_bottom = pos.copy()
        brim_bottom[2] = max(0.0, pos[2] - base_brim_height)

        brim_v, brim_f = _build_frustum(pos, brim_bottom, radius, brim_radius, segments)
        if len(brim_v) > 0:
            all_verts_list.append(brim_v)
            all_faces_list.append(brim_f + vertex_offset)
            vertex_offset += len(brim_v)

        cap_v, cap_f = _build_cap(brim_bottom, brim_radius, np.array([0.0, 0.0, -1.0]), segments, flip=True)
        all_verts_list.append(cap_v)
        all_faces_list.append(cap_f + vertex_offset)
        vertex_offset += len(cap_v)

    # --- Bước 5: Ghép và tính normals ---
    if not all_verts_list:
        verts = np.zeros((3, 3), dtype=np.float32)
        return MeshData(vertices=verts)

    combined_verts = np.vstack(all_verts_list).astype(np.float32)
    combined_faces = np.vstack(all_faces_list).astype(np.int32)

    v0 = combined_verts[combined_faces[:, 0]]
    v1 = combined_verts[combined_faces[:, 1]]
    v2 = combined_verts[combined_faces[:, 2]]

    num_faces = len(combined_faces)
    soup_verts = np.zeros((num_faces * 3, 3), dtype=np.float32)
    soup_verts[0::3] = v0
    soup_verts[1::3] = v1
    soup_verts[2::3] = v2

    edge1 = v1 - v0
    edge2 = v2 - v0
    face_normals = np.cross(edge1, edge2)
    norms_length = np.linalg.norm(face_normals, axis=1, keepdims=True)
    norms_length = np.maximum(norms_length, 1e-10)
    face_normals /= norms_length

    soup_normals = np.zeros((num_faces * 3, 3), dtype=np.float32)
    soup_normals[0::3] = face_normals
    soup_normals[1::3] = face_normals
    soup_normals[2::3] = face_normals

    return MeshData(vertices=soup_verts, normals=soup_normals)
