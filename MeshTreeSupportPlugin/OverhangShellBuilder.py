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
    oh_normals = face_normals[oh_face_indices]  # (K, 3) inward normals

    if len(oh_faces) == 0:
        return np.zeros((0, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.float32)

    # --- Bước 1: Ánh xạ vertex index gốc → index cục bộ ---
    unique_vert_indices = np.unique(oh_faces.ravel())
    num_unique = len(unique_vert_indices)

    # Bảng ánh xạ: global_idx → local_idx
    idx_map = np.full(vertices.shape[0], -1, dtype=np.int64)
    idx_map[unique_vert_indices] = np.arange(num_unique)

    # Remap face indices sang local
    local_faces = idx_map[oh_faces]  # (K, 3)

    # Lấy tọa độ vertex
    vert_pos = vertices[unique_vert_indices].copy().astype(np.float64)  # (U, 3)

    # --- Bước 2: Tính per-vertex normal ---
    # Trung bình pháp tuyến các mặt kề cho mỗi đỉnh
    vert_normals = np.zeros((num_unique, 3), dtype=np.float64)
    np.add.at(vert_normals, local_faces[:, 0], oh_normals)
    np.add.at(vert_normals, local_faces[:, 1], oh_normals)
    np.add.at(vert_normals, local_faces[:, 2], oh_normals)

    # Chuẩn hóa
    lengths = np.linalg.norm(vert_normals, axis=1, keepdims=True)
    lengths = np.maximum(lengths, 1e-10)
    vert_normals /= lengths

    # Hướng outward = -inward (ra xa vật thể, hướng xuống cho overhang)
    outward = -vert_normals

    # --- Bước 3: Tạo inner và outer vertices ---
    inner_verts = vert_pos + outward * gap                # (U, 3)
    outer_verts = vert_pos + outward * (gap + thickness)  # (U, 3)

    num_oh_faces = len(local_faces)

    # --- Bước 4: Tạo inner surface (mặt hướng về vật thể) ---
    # Giữ nguyên winding gốc → cross(e1,e2) cho inward normal (hướng lên = về vật thể)
    # Trong hệ Z-up left-handed, winding CW khi nhìn từ trên → normal hướng lên
    inner_v0 = inner_verts[local_faces[:, 0]]
    inner_v1 = inner_verts[local_faces[:, 1]]
    inner_v2 = inner_verts[local_faces[:, 2]]

    inner_soup = np.zeros((num_oh_faces * 3, 3), dtype=np.float64)
    inner_soup[0::3] = inner_v0
    inner_soup[1::3] = inner_v1
    inner_soup[2::3] = inner_v2

    # --- Bước 5: Tạo outer surface (mặt hướng ra ngoài = về phía tree tip) ---
    # Đảo winding → normal hướng xuống (ra xa vật thể)
    outer_v0 = outer_verts[local_faces[:, 0]]
    outer_v1 = outer_verts[local_faces[:, 1]]
    outer_v2 = outer_verts[local_faces[:, 2]]

    outer_soup = np.zeros((num_oh_faces * 3, 3), dtype=np.float64)
    outer_soup[0::3] = outer_v0
    outer_soup[1::3] = outer_v2  # đảo v1 ↔ v2
    outer_soup[2::3] = outer_v1

    # --- Bước 6: Tạo side walls tại boundary edges ---
    # Boundary edge = cạnh chỉ thuộc 1 mặt overhang (biên vùng overhang)
    edge_info = defaultdict(list)  # sorted_edge → [(directed_a, directed_b), ...]
    for fi in range(num_oh_faces):
        f = local_faces[fi]
        for i in range(3):
            a, b = int(f[i]), int(f[(i + 1) % 3])
            key = (min(a, b), max(a, b))
            edge_info[key].append((a, b))

    side_soup_list = []
    for key, entries in edge_info.items():
        if len(entries) != 1:
            continue
        # Boundary edge: lấy thứ tự directed từ face gốc
        a, b = entries[0]
        # Side wall quad: inner_a, inner_b, outer_a, outer_b
        # 2 tam giác tạo thành quad nối biên inner ↔ outer
        # Winding: nhìn từ ngoài biên (phía exterior) để normal hướng ra ngoài
        #
        # Trong hệ Z-up left-handed, face edge traversal a→b:
        # - Interior patch ở bên phải (CW traversal)
        # - Exterior ở bên trái → side wall normal hướng ra bên trái
        #
        # Quad: inner_b → inner_a → outer_a → outer_b
        # Tri 1: (inner_b, inner_a, outer_a)
        # Tri 2: (inner_b, outer_a, outer_b)
        ia = inner_verts[a]
        ib = inner_verts[b]
        oa = outer_verts[a]
        ob = outer_verts[b]

        tri1 = np.array([ib, ia, oa], dtype=np.float64)
        tri2 = np.array([ib, oa, ob], dtype=np.float64)
        side_soup_list.append(tri1)
        side_soup_list.append(tri2)

    # Ghép side walls
    if side_soup_list:
        side_soup = np.vstack(side_soup_list)  # (S*3, 3)
    else:
        side_soup = np.zeros((0, 3), dtype=np.float64)

    # --- Bước 7: Ghép tất cả ---
    all_soup = np.concatenate([inner_soup, outer_soup, side_soup], axis=0)

    if len(all_soup) == 0:
        return np.zeros((0, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.float32)

    # --- Bước 8: Tính face normals cho triangle soup ---
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

    # Gán cùng normal cho 3 đỉnh mỗi tam giác (flat shading)
    all_normals = np.zeros_like(all_soup)
    all_normals[0::3] = fn
    all_normals[1::3] = fn
    all_normals[2::3] = fn

    return all_soup.astype(np.float32), all_normals.astype(np.float32)
