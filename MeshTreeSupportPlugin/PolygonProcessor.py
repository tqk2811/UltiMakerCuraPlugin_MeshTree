# ==============================================================================
# Module: Xử lý đa giác overhang (Polygon Processor)
#
# Gộp tam giác nhỏ, chia tam giác lớn để chuẩn hóa kích thước đa giác
# trước khi tạo tip interface.
#
# Thuật toán:
#   1. Xây adjacency graph giữa các tam giác overhang (tolerance-based)
#   2. Merge: gộp tam giác < min_area với hàng xóm nhỏ nhất sát bên
#   3. Split: chia tam giác > max_area qua trung tuyến (median)
#   4. Output: danh sách polygon, mỗi cái có centroid, area, normal, n_sides
#
# Đầu vào: vertices, faces, overhang_mask, face_normals, min/max_area
# Đầu ra: list[PolygonInfo] — thông tin mỗi đa giác đã chuẩn hóa
#
# Luồng thực thi: worker thread (trong Job.run())
# ==============================================================================

import numpy as np
from collections import defaultdict


class PolygonInfo:
    """Thông tin một đa giác đã xử lý (merge/split)."""
    __slots__ = ['centroid', 'area', 'normal', 'n_sides',
                 'face_indices', 'outer_position', 'boundary_verts']

    def __init__(self, centroid, area, normal, n_sides, face_indices):
        self.centroid = centroid          # (3,) vị trí trọng tâm
        self.area = area                  # float, diện tích (mm²)
        self.normal = normal              # (3,) outward normal đơn vị
        self.n_sides = n_sides            # int, số cạnh (= len(boundary_verts))
        self.face_indices = face_indices  # list[int] chỉ số face gốc trong overhang
        self.outer_position = None        # (3,) sẽ tính sau = centroid + outward*(gap+thickness)
        self.boundary_verts = None        # (K, 3) đỉnh biên thực tế trên outer surface, theo thứ tự


def process_polygons(vertices, faces, overhang_mask, face_normals,
                     min_area=0.5, max_area=10.0, gap=0.1, thickness=0.5):
    """
    Xử lý đa giác overhang: merge nhỏ, split lớn, chuẩn hóa.

    Tham số:
        vertices      : (N, 3) tọa độ đỉnh mesh
        faces         : (M, 3) chỉ số tam giác mesh
        overhang_mask : (M,) bool mask overhang
        face_normals  : (M, 3) inward normals
        min_area      : float - diện tích tối thiểu (mm²)
        max_area      : float - diện tích tối đa (mm²)
        gap           : float - khoảng cách shell gap (mm)
        thickness     : float - độ dày shell (mm)

    Trả về:
        list[PolygonInfo] — mỗi đa giác đã chuẩn hóa
    """

    oh_indices = np.where(overhang_mask)[0]
    if len(oh_indices) == 0:
        return []

    oh_faces = faces[oh_indices]       # (K, 3)
    oh_normals = face_normals[oh_indices]  # (K, 3) inward

    # --- Pre-subdivide: chia nhỏ tam giác > max_area bằng midpoint ---
    ext_vertices, sub_faces, sub_normals, parent_map = \
        _subdivide_large_faces(vertices, oh_faces, oh_normals, max_area)

    num_sub = len(sub_faces)
    if num_sub == 0:
        return []

    # --- Tính diện tích và trọng tâm mỗi tam giác ---
    v0 = ext_vertices[sub_faces[:, 0]]
    v1 = ext_vertices[sub_faces[:, 1]]
    v2 = ext_vertices[sub_faces[:, 2]]

    areas = 0.5 * np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1)
    centroids = (v0 + v1 + v2) / 3.0

    # --- Tính per-vertex outward normal + outer surface positions ---
    unique_vert_indices = np.unique(sub_faces.ravel())
    num_unique = len(unique_vert_indices)
    idx_map = np.full(ext_vertices.shape[0], -1, dtype=np.int64)
    idx_map[unique_vert_indices] = np.arange(num_unique)
    local_sub_faces = idx_map[sub_faces]  # remapped to local vertex indices

    vert_pos = ext_vertices[unique_vert_indices].copy().astype(np.float64)
    vert_normals = np.zeros((num_unique, 3), dtype=np.float64)
    np.add.at(vert_normals, local_sub_faces[:, 0], sub_normals)
    np.add.at(vert_normals, local_sub_faces[:, 1], sub_normals)
    np.add.at(vert_normals, local_sub_faces[:, 2], sub_normals)
    lengths = np.linalg.norm(vert_normals, axis=1, keepdims=True)
    vert_normals /= np.maximum(lengths, 1e-10)
    outward = -vert_normals
    offset_dist = gap + thickness
    outer_verts = vert_pos + outward * offset_dist

    # --- Xây adjacency graph (tolerance-based) ---
    adjacency = _build_adjacency(sub_faces, ext_vertices, tol=0.01)

    # --- Khởi tạo groups: mỗi tam giác subdivision là 1 group ---
    group_of = list(range(num_sub))
    groups = {i: [i] for i in range(num_sub)}

    # --- Merge: gộp tam giác nhỏ hơn min_area ---
    _merge_small_polygons(groups, group_of, adjacency, areas, centroids,
                          sub_normals, min_area)

    # --- Split: chia group lớn hơn max_area (multi-face spatial) ---
    split_data = _split_large_polygons(groups, areas, centroids, sub_normals,
                                       ext_vertices, sub_faces, max_area)

    # --- Tạo PolygonInfo cho mỗi group ---
    result = []

    for gid, members in split_data.items():
        g_areas = areas[members]
        g_centroids = centroids[members]
        g_normals = sub_normals[members]

        total_area = float(np.sum(g_areas))
        if total_area < 1e-8:
            continue

        # Trọng tâm trọng số theo diện tích
        weights = g_areas / total_area
        weighted_centroid = np.sum(g_centroids * weights[:, np.newaxis], axis=0)

        # Normal trung bình (inward → đảo thành outward)
        avg_normal = np.sum(g_normals * weights[:, np.newaxis], axis=0)
        nlen = np.linalg.norm(avg_normal)
        if nlen > 1e-10:
            avg_normal /= nlen
        outward_normal = -avg_normal

        # Trích boundary vertices thực tế trên outer surface
        boundary = _extract_boundary_loop(members, local_sub_faces, outer_verts)

        # Số cạnh = số đỉnh boundary thực tế
        if boundary is not None:
            n_sides = len(boundary)
        else:
            n_sides = min(3 + len(members) - 1, 8)
            if len(members) == 1:
                n_sides = 3

        info = PolygonInfo(
            centroid=weighted_centroid,
            area=total_area,
            normal=outward_normal,
            n_sides=n_sides,
            face_indices=list(set(int(oh_indices[parent_map[m]]) for m in members))
        )
        # Vị trí trên outer shell surface
        info.outer_position = weighted_centroid + outward_normal * offset_dist
        info.boundary_verts = boundary

        result.append(info)

    return result


def _build_adjacency(oh_faces, vertices, tol=0.01):
    """
    Xây adjacency graph giữa các tam giác overhang.
    Hai tam giác kề nhau nếu chia chung cạnh (tolerance-based vertex matching).

    Trả về:
        dict: face_local_idx → set[face_local_idx] — danh sách hàng xóm
    """
    num_faces = len(oh_faces)
    adjacency = defaultdict(set)

    # Lấy tọa độ và quantize để tolerance matching
    inv_tol = 1.0 / tol
    edge_map = defaultdict(list)  # quantized_edge → [(face_idx, v_a, v_b)]

    for fi in range(num_faces):
        f = oh_faces[fi]
        for i in range(3):
            va_idx, vb_idx = int(f[i]), int(f[(i + 1) % 3])
            va = vertices[va_idx]
            vb = vertices[vb_idx]

            # Quantize vertex positions
            qa = tuple(np.round(va * inv_tol).astype(np.int64))
            qb = tuple(np.round(vb * inv_tol).astype(np.int64))

            # Sorted key để 2 face cùng cạnh match
            key = tuple(sorted([qa, qb]))
            edge_map[key].append(fi)

    # Xây adjacency từ shared edges
    for key, face_list in edge_map.items():
        for i in range(len(face_list)):
            for j in range(i + 1, len(face_list)):
                adjacency[face_list[i]].add(face_list[j])
                adjacency[face_list[j]].add(face_list[i])

    return adjacency


def _merge_small_polygons(groups, group_of, adjacency, areas, centroids,
                          normals, min_area):
    """
    Gộp tam giác nhỏ hơn min_area với hàng xóm nhỏ nhất sát bên cạnh.
    Lặp cho đến khi không còn group nào < min_area có thể merge.
    """
    changed = True
    while changed:
        changed = False

        # Tính diện tích mỗi group
        group_areas = {}
        for gid, members in groups.items():
            group_areas[gid] = float(np.sum(areas[members]))

        # Sắp xếp groups theo diện tích tăng dần
        sorted_gids = sorted(groups.keys(), key=lambda g: group_areas.get(g, 0))

        for gid in sorted_gids:
            if gid not in groups:
                continue
            if group_areas.get(gid, 0) >= min_area:
                continue

            # Tìm group hàng xóm nhỏ nhất
            neighbor_gids = set()
            for member in groups[gid]:
                for adj_face in adjacency.get(member, set()):
                    adj_gid = group_of[adj_face]
                    if adj_gid != gid and adj_gid in groups:
                        neighbor_gids.add(adj_gid)

            if not neighbor_gids:
                continue

            # Chọn hàng xóm nhỏ nhất
            best_neighbor = min(neighbor_gids, key=lambda g: group_areas.get(g, 0))

            # Merge gid vào best_neighbor
            for member in groups[gid]:
                group_of[member] = best_neighbor
            groups[best_neighbor].extend(groups[gid])
            group_areas[best_neighbor] = group_areas.get(best_neighbor, 0) + \
                                          group_areas.get(gid, 0)
            del groups[gid]
            changed = True


def _split_large_polygons(groups, areas, centroids, normals,
                          vertices, sub_faces, max_area):
    """
    Chia group (sau merge) lớn hơn max_area bằng spatial median split.

    Pre-subdivision đã đảm bảo mỗi face đơn lẻ <= max_area,
    nên chỉ cần xử lý groups có nhiều face bị merge lại > max_area.

    Trả về:
        dict: group_id → list[face_local_idx]
    """
    result = {}
    next_id = max(groups.keys()) + 1 if groups else 0

    for gid, members in groups.items():
        total_area = float(np.sum(areas[members]))

        if total_area <= max_area:
            result[gid] = members
            continue

        # Chia thành N phần để mỗi phần <= max_area
        n_parts = max(2, int(np.ceil(total_area / max_area)))

        if len(members) >= n_parts:
            # Chia spatial bằng KD-split
            member_centroids = centroids[members]
            parts = _spatial_split(members, member_centroids, n_parts)
            for part in parts:
                result[next_id] = part
                next_id += 1
        else:
            # Ít member hơn n_parts → mỗi member thành 1 group
            for m in members:
                result[next_id] = [m]
                next_id += 1

    return result


def _extract_boundary_loop(members, local_faces, outer_verts):
    """
    Trích xuất vòng biên (boundary loop) của một nhóm tam giác trên outer surface.

    Tìm các cạnh chỉ thuộc 1 tam giác trong nhóm (boundary edges),
    rồi nối chúng thành vòng đỉnh có thứ tự.

    Tham số:
        members     : list[int] - chỉ số face cục bộ trong nhóm
        local_faces : (K, 3) - mảng face với vertex index cục bộ
        outer_verts : (U, 3) - tọa độ đỉnh trên outer surface

    Trả về:
        numpy array (N, 3) - đỉnh biên theo thứ tự, hoặc None nếu thất bại
    """
    # Đếm số lần mỗi cạnh (undirected) xuất hiện trong nhóm
    edge_face_count = defaultdict(int)
    edge_directed = defaultdict(list)

    for m in members:
        f = local_faces[m]
        for i in range(3):
            a, b = int(f[i]), int(f[(i + 1) % 3])
            key = (min(a, b), max(a, b))
            edge_face_count[key] += 1
            edge_directed[key].append((a, b))

    # Cạnh biên = xuất hiện đúng 1 lần
    boundary_edges = []
    for key, count in edge_face_count.items():
        if count == 1:
            boundary_edges.append(edge_directed[key][0])

    if len(boundary_edges) < 3:
        return None

    # Xây map: vertex → vertex tiếp theo
    next_map = {}
    for a, b in boundary_edges:
        next_map[a] = b

    # Đi vòng theo thứ tự
    start = boundary_edges[0][0]
    loop = [start]
    current = next_map.get(start)
    for _ in range(len(boundary_edges)):
        if current is None or current == start:
            break
        loop.append(current)
        current = next_map.get(current)

    if len(loop) < 3:
        return None

    # Giữ nguyên thứ tự CCW (khớp với _make_ring) để _connect_rings tạo
    # winding nhất quán. Không reverse vì ring0 và ring1 cần cùng chiều.
    return outer_verts[np.array(loop)].copy()


def _spatial_split(members, member_centroids, n_parts):
    """
    Chia danh sách members thành n_parts phần bằng recursive median split.
    """
    if n_parts <= 1 or len(members) <= 1:
        return [list(members)]

    # Tìm trục có spread lớn nhất
    spread = member_centroids.max(axis=0) - member_centroids.min(axis=0)
    axis = int(np.argmax(spread))

    # Sort theo trục
    order = np.argsort(member_centroids[:, axis])
    sorted_members = [members[i] for i in order]
    sorted_centroids = member_centroids[order]

    # Chia tại median
    mid = len(sorted_members) // 2
    left_members = sorted_members[:mid]
    right_members = sorted_members[mid:]
    left_centroids = sorted_centroids[:mid]
    right_centroids = sorted_centroids[mid:]

    n_left = n_parts // 2
    n_right = n_parts - n_left

    left_parts = _spatial_split(left_members, left_centroids, n_left)
    right_parts = _spatial_split(right_members, right_centroids, n_right)

    return left_parts + right_parts


def _subdivide_large_faces(vertices, oh_faces, oh_normals, max_area):
    """
    Chia nhỏ đệ quy các tam giác overhang có diện tích > max_area.
    Tách cạnh dài nhất tại trung điểm để tạo 2 tam giác con.
    Mỗi tam giác con có boundary riêng → mọc tip riêng.

    Trả về:
        ext_vertices : (N', 3) vertices gốc + midpoint mới
        new_faces    : (K', 3) faces sau subdivision (global vertex index)
        new_normals  : (K', 3) normals tương ứng
        parent_map   : (K',) index trong oh_faces cho mỗi face mới
    """
    extra_verts = []  # list of (3,) float64
    base_count = len(vertices)

    def get_vert(idx):
        idx = int(idx)
        if idx < base_count:
            return vertices[idx].astype(np.float64)
        return extra_verts[idx - base_count]

    def add_vert(pos):
        new_idx = base_count + len(extra_verts)
        extra_verts.append(np.array(pos, dtype=np.float64))
        return new_idx

    # Stack: (face[3], normal[3], parent_oh_index)
    stack = []
    for i in range(len(oh_faces)):
        stack.append((oh_faces[i].copy().astype(np.int64),
                      oh_normals[i].copy(),
                      i))

    result_faces = []
    result_normals = []
    result_parents = []

    while stack:
        face, normal, parent = stack.pop()
        v0 = get_vert(face[0])
        v1 = get_vert(face[1])
        v2 = get_vert(face[2])

        area = 0.5 * np.linalg.norm(np.cross(v1 - v0, v2 - v0))

        if area <= max_area:
            result_faces.append([int(face[0]), int(face[1]), int(face[2])])
            result_normals.append(normal.tolist())
            result_parents.append(parent)
            continue

        # Tìm cạnh dài nhất
        e_lens = [
            np.linalg.norm(v1 - v0),
            np.linalg.norm(v2 - v1),
            np.linalg.norm(v0 - v2),
        ]
        longest = int(np.argmax(e_lens))

        if longest == 0:       # cạnh v0-v1
            mid_idx = add_vert((v0 + v1) / 2)
            stack.append((np.array([face[0], mid_idx, face[2]]), normal.copy(), parent))
            stack.append((np.array([mid_idx, face[1], face[2]]), normal.copy(), parent))
        elif longest == 1:     # cạnh v1-v2
            mid_idx = add_vert((v1 + v2) / 2)
            stack.append((np.array([face[0], face[1], mid_idx]), normal.copy(), parent))
            stack.append((np.array([face[0], mid_idx, face[2]]), normal.copy(), parent))
        else:                  # cạnh v2-v0
            mid_idx = add_vert((v2 + v0) / 2)
            stack.append((np.array([face[0], face[1], mid_idx]), normal.copy(), parent))
            stack.append((np.array([mid_idx, face[1], face[2]]), normal.copy(), parent))

    # Ghép vertices
    if extra_verts:
        ext_verts = np.vstack([vertices.astype(np.float64),
                               np.array(extra_verts, dtype=np.float64)])
    else:
        ext_verts = vertices.astype(np.float64)

    if result_faces:
        new_faces = np.array(result_faces, dtype=np.int64)
        new_normals = np.array(result_normals, dtype=np.float64)
        parent_map = np.array(result_parents, dtype=np.int64)
    else:
        new_faces = np.zeros((0, 3), dtype=np.int64)
        new_normals = np.zeros((0, 3), dtype=np.float64)
        parent_map = np.zeros(0, dtype=np.int64)

    return ext_verts, new_faces, new_normals, parent_map
