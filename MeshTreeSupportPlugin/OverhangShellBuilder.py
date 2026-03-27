# ==============================================================================
# Module: Tạo vỏ overhang (Overhang Shell Builder)
#
# Tạo một lớp vỏ mỏng (shell) ôm sát bề mặt lơ lửng của vật thể.
# Vỏ gồm 2 lớp:
#   - Lớp trong (inner): cách bề mặt vật thể một khoảng gap
#   - Lớp ngoài (outer): cách lớp trong một khoảng thickness
#   - Thành bên (side walls): nối biên lớp trong và lớp ngoài
#
# Các tip của tree support sẽ nối vào lớp ngoài của vỏ.
#
# Hệ tọa độ: Z-up (Z = chiều cao, bàn in tại Z=0)
#
# Đầu vào: vertices, faces, overhang_mask, face_normals, gap, thickness
# Đầu ra: triangle soup (verts, normals) cho Cura
#
# Luồng thực thi: Chạy trong worker thread (bên trong Job.run())
# ==============================================================================

import numpy as np
from collections import defaultdict


def build_overhang_shell(vertices, faces, overhang_mask, face_normals,
                         gap, thickness):
    """
    Tạo vỏ shell ôm sát bề mặt overhang.

    Thuật toán:
    1. Trích xuất các mặt overhang từ mesh gốc
    2. Tính per-vertex normal bằng trung bình các face normal lân cận
    3. Offset vertex theo outward normal:
       - Inner surface: offset = gap
       - Outer surface: offset = gap + thickness
    4. Tạo side walls tại các cạnh biên (boundary edges)
    5. Ghép tất cả thành triangle soup với normals

    Tham số:
        vertices       : numpy array (N, 3) - tọa độ đỉnh mesh gốc
        faces          : numpy array (M, 3) - chỉ số tam giác mesh gốc
        overhang_mask  : numpy array (M,) bool - mask mặt lơ lửng
        face_normals   : numpy array (M, 3) - pháp tuyến INWARD đơn vị tất cả mặt
        gap            : float - khoảng cách từ vật thể đến lớp trong (mm)
        thickness      : float - độ dày vỏ shell (mm)

    Trả về:
        shell_verts   : numpy array (V, 3) float32 - triangle soup vertices
        shell_normals : numpy array (V, 3) float32 - triangle soup normals
    """

    oh_face_indices = np.where(overhang_mask)[0]
    oh_faces = faces[oh_face_indices]        # (K, 3)
    oh_normals = face_normals[oh_face_indices].copy().astype(np.float64)  # (K, 3) inward

    if len(oh_faces) == 0:
        return np.zeros((0, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.float32)

    num_oh_faces = len(oh_faces)

    # --- Bước 1: Ánh xạ vertex index gốc → index cục bộ ---
    unique_vert_indices = np.unique(oh_faces.ravel())
    idx_map = np.full(vertices.shape[0], -1, dtype=np.int64)
    idx_map[unique_vert_indices] = np.arange(len(unique_vert_indices))
    local_faces = idx_map[oh_faces]  # (K, 3)
    vert_pos = vertices[unique_vert_indices].copy().astype(np.float64)  # (U, 3)

    # --- Bước 2: Per-face offset ---
    # Mỗi tam giác offset độc lập theo normal của chính nó → không dùng per-vertex
    # averaging (averaging từ faces có hướng khác nhau gây deform và winding lỗi).
    #
    # Uniform offset giữ nguyên shape và winding của tam giác:
    #   inner: cross(e1, e2) = oh_normals[i] (inward, hướng lên) ✓
    #   outer: flip v1↔v2 → cross(e1, e2) = -oh_normals[i] (outward, hướng xuống) ✓
    outward = -oh_normals  # (K, 3) outward per face

    orig_v = vert_pos[local_faces]  # (K, 3, 3)
    inner_v = orig_v + outward[:, np.newaxis, :] * gap               # (K, 3, 3)
    outer_v = orig_v + outward[:, np.newaxis, :] * (gap + thickness) # (K, 3, 3)

    # Inner surface: v0, v1, v2 → normal = oh_normals[i] (inward/upward)
    inner_soup = inner_v.reshape(-1, 3)  # (K*3, 3)

    # Outer surface: v0, v2, v1 (swap v1↔v2) → normal = -oh_normals[i] (outward/downward)
    outer_flipped = outer_v[:, [0, 2, 1], :]  # (K, 3, 3)
    outer_soup = outer_flipped.reshape(-1, 3)  # (K*3, 3)

    # --- Bước 3: Side walls tại boundary edges ---
    # Boundary edge = cạnh chỉ thuộc 1 face overhang
    # Lưu (fi, i_edge) để lấy đúng inner/outer vertex per-face
    edge_info = defaultdict(list)
    for fi in range(num_oh_faces):
        f = local_faces[fi]
        for i in range(3):
            a, b = int(f[i]), int(f[(i + 1) % 3])
            key = (min(a, b), max(a, b))
            edge_info[key].append((fi, i))

    side_soup_list = []
    for key, entries in edge_info.items():
        if len(entries) != 1:
            continue
        fi, i_edge = entries[0]
        ia = inner_v[fi, i_edge]
        ib = inner_v[fi, (i_edge + 1) % 3]
        oa = outer_v[fi, i_edge]
        ob = outer_v[fi, (i_edge + 1) % 3]
        # Winding đã đúng: tri1=(ib,ia,oa), tri2=(ib,oa,ob) cho normal hướng ra ngoài biên
        # (chứng minh: cross(ia-ib, oa-ib) ∝ cross(edge_a→b, outward) = outward hướng biên)
        side_soup_list.append(np.array([ib, ia, oa], dtype=np.float64))
        side_soup_list.append(np.array([ib, oa, ob], dtype=np.float64))

    if side_soup_list:
        side_soup = np.vstack(side_soup_list)
    else:
        side_soup = np.zeros((0, 3), dtype=np.float64)

    # --- Bước 4: Ghép và tính normals ---
    all_soup = np.concatenate([inner_soup, outer_soup, side_soup], axis=0)

    if len(all_soup) == 0:
        return np.zeros((0, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.float32)

    sv0 = all_soup[0::3]
    sv1 = all_soup[1::3]
    sv2 = all_soup[2::3]
    fn = np.cross(sv1 - sv0, sv2 - sv0)
    fn_len = np.linalg.norm(fn, axis=1, keepdims=True)
    fn_len = np.maximum(fn_len, 1e-10)
    fn /= fn_len

    all_normals = np.zeros_like(all_soup)
    all_normals[0::3] = fn
    all_normals[1::3] = fn
    all_normals[2::3] = fn

    return all_soup.astype(np.float32), all_normals.astype(np.float32)


def build_interface_tents(vertices, faces, overhang_mask, face_normals,
                          tip_points, tip_normals, shell_gap, shell_thickness,
                          cone_height):
    """
    Tạo mesh "lều" phủ nhựa từ đáy bé nón ra toàn bộ shell.

    Mỗi tam giác overhang trên shell outer → tìm tip gần nhất →
    nối 3 đỉnh outer về cone_bottom (đáy bé nón) → tạo hình lều.

    Tham số:
        vertices, faces   : mesh gốc
        overhang_mask      : mask mặt overhang
        face_normals       : pháp tuyến INWARD tất cả mặt
        tip_points         : (K, 3) vị trí tip trên shell outer surface
        tip_normals        : (K, 3) inward normal tại mỗi tip
        shell_gap, shell_thickness : tham số shell
        cone_height : float - chiều dài nón cụt (mm)

    Trả về:
        tent_verts   : numpy array (V, 3) float32 - triangle soup
        tent_normals : numpy array (V, 3) float32 - triangle soup normals
    """

    oh_face_indices = np.where(overhang_mask)[0]
    oh_faces = faces[oh_face_indices]
    oh_normals = face_normals[oh_face_indices]  # inward

    if len(oh_faces) == 0 or len(tip_points) == 0:
        return np.zeros((0, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.float32)

    # --- Tính per-vertex outward normal (giống OverhangShellBuilder) ---
    unique_vert_indices = np.unique(oh_faces.ravel())
    num_unique = len(unique_vert_indices)
    idx_map = np.full(vertices.shape[0], -1, dtype=np.int64)
    idx_map[unique_vert_indices] = np.arange(num_unique)
    local_faces = idx_map[oh_faces]

    vert_pos = vertices[unique_vert_indices].copy().astype(np.float64)

    vert_normals = np.zeros((num_unique, 3), dtype=np.float64)
    np.add.at(vert_normals, local_faces[:, 0], oh_normals)
    np.add.at(vert_normals, local_faces[:, 1], oh_normals)
    np.add.at(vert_normals, local_faces[:, 2], oh_normals)
    lengths = np.linalg.norm(vert_normals, axis=1, keepdims=True)
    lengths = np.maximum(lengths, 1e-10)
    vert_normals /= lengths
    outward = -vert_normals  # ra xa vật thể

    # Shell outer surface vertices
    outer_verts = vert_pos + outward * (shell_gap + shell_thickness)

    # --- Tính cone_bottom cho mỗi tip ---
    departure_dist = cone_height
    tip_outward = -tip_normals.astype(np.float64)
    tip_out_lens = np.linalg.norm(tip_outward, axis=1, keepdims=True)
    tip_out_lens = np.maximum(tip_out_lens, 1e-10)
    tip_outward /= tip_out_lens
    cone_bottoms = tip_points.astype(np.float64) + tip_outward * departure_dist  # (K, 3)

    # --- Cho mỗi overhang face, tìm cone_bottom gần nhất → tạo lều ---
    tent_soup_list = []
    for fi in range(len(local_faces)):
        f = local_faces[fi]
        v0 = outer_verts[f[0]]
        v1 = outer_verts[f[1]]
        v2 = outer_verts[f[2]]

        # Tâm tam giác outer
        center = (v0 + v1 + v2) / 3.0

        # Tìm cone_bottom gần nhất
        dists = np.linalg.norm(cone_bottoms - center, axis=1)
        nearest_idx = np.argmin(dists)
        apex = cone_bottoms[nearest_idx]

        # 3 tam giác lều: (apex, v0, v1), (apex, v1, v2), (apex, v2, v0)
        # Winding: apex phía dưới, base phía trên → normal hướng ra ngoài
        tent_soup_list.append(np.array([apex, v1, v0], dtype=np.float64))
        tent_soup_list.append(np.array([apex, v2, v1], dtype=np.float64))
        tent_soup_list.append(np.array([apex, v0, v2], dtype=np.float64))

    if not tent_soup_list:
        return np.zeros((0, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.float32)

    all_soup = np.vstack(tent_soup_list)  # (N*3, 3)

    # --- Tính face normals ---
    num_tris = len(all_soup) // 3
    sv0 = all_soup[0::3]
    sv1 = all_soup[1::3]
    sv2 = all_soup[2::3]
    e1 = sv1 - sv0
    e2 = sv2 - sv0
    fn = np.cross(e1, e2)
    fn_len = np.linalg.norm(fn, axis=1, keepdims=True)
    fn_len = np.maximum(fn_len, 1e-10)
    fn /= fn_len

    all_normals = np.zeros_like(all_soup)
    all_normals[0::3] = fn
    all_normals[1::3] = fn
    all_normals[2::3] = fn

    return all_soup.astype(np.float32), all_normals.astype(np.float32)
