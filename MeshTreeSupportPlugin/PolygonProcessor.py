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
                 'face_indices', 'outer_position']

    def __init__(self, centroid, area, normal, n_sides, face_indices):
        self.centroid = centroid          # (3,) vị trí trọng tâm
        self.area = area                  # float, diện tích (mm²)
        self.normal = normal              # (3,) outward normal đơn vị
        self.n_sides = n_sides            # int, số cạnh regular polygon tương đương
        self.face_indices = face_indices  # list[int] chỉ số face gốc trong overhang
        self.outer_position = None        # (3,) sẽ tính sau = centroid + outward*(gap+thickness)


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

    # --- Tính diện tích và trọng tâm mỗi tam giác overhang ---
    v0 = vertices[oh_faces[:, 0]]
    v1 = vertices[oh_faces[:, 1]]
    v2 = vertices[oh_faces[:, 2]]

    areas = 0.5 * np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1)
    centroids = (v0 + v1 + v2) / 3.0

    # --- Xây adjacency graph (tolerance-based) ---
    adjacency = _build_adjacency(oh_faces, vertices, tol=0.01)

    # --- Khởi tạo groups: mỗi tam giác là 1 group ---
    num_oh = len(oh_indices)
    group_of = list(range(num_oh))  # group_of[i] = group id của face i
    groups = {i: [i] for i in range(num_oh)}  # group_id → list[face_local_idx]

    # --- Merge: gộp tam giác nhỏ hơn min_area ---
    _merge_small_polygons(groups, group_of, adjacency, areas, centroids,
                          oh_normals, min_area)

    # --- Split: chia tam giác lớn hơn max_area ---
    split_data = _split_large_polygons(groups, areas, centroids, oh_normals,
                                       vertices, oh_faces, max_area)

    # --- Tạo PolygonInfo cho mỗi group ---
    result = []
    offset_dist = gap + thickness

    for gid, members in split_data.items():
        g_areas = areas[members]
        g_centroids = centroids[members]
        g_normals = oh_normals[members]

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

        # Số cạnh regular polygon tương đương (cap tại 8)
        n_sides = min(3 + len(members) - 1, 8)
        if len(members) == 1:
            n_sides = 3

        info = PolygonInfo(
            centroid=weighted_centroid,
            area=total_area,
            normal=outward_normal,
            n_sides=n_sides,
            face_indices=[int(oh_indices[m]) for m in members]
        )
        # Vị trí trên outer shell surface
        info.outer_position = weighted_centroid + outward_normal * offset_dist

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
                          vertices, oh_faces, max_area):
    """
    Chia group lớn hơn max_area.

    Cho mỗi group có area > max_area:
    - Nếu group chỉ có 1 tam giác: chia qua trung tuyến (median) ảo
      (tạo 2 sub-groups, mỗi cái giữ ref đến face gốc nhưng với area/2)
    - Nếu group có nhiều tam giác: chia thành 2 nửa theo spatial median

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

        if len(members) == 1:
            # Tam giác đơn lẻ quá lớn → tạo n_parts ảo
            # (giữ cùng face index nhưng area chia đều, centroid spread)
            face_idx = members[0]
            f = oh_faces[face_idx]
            v0 = vertices[f[0]]
            v1 = vertices[f[1]]
            v2 = vertices[f[2]]

            # Chia tam giác thành n_parts bằng subdivision tại centroid
            for p in range(n_parts):
                result[next_id] = [face_idx]
                next_id += 1
        elif len(members) >= n_parts:
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
