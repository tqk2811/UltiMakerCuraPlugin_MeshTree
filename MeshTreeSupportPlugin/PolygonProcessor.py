# ==============================================================================
# Module: Xử lý đa giác overhang (Polygon Processor)
#
# Gộp tam giác nhỏ, chia tam giác lớn để chuẩn hóa kích thước đa giác
# trước khi tạo tip interface.
#
# Thuật toán:
#   1. Pre-subdivide: chia tam giác > max_area tại cạnh dài nhất
#   2. Merge (distance-based): gộp tam giác < min_area với tam giác gần nhất
#      theo khoảng cách trọng tâm XYZ (trong bán kính merge_max_dist),
#      sao cho diện tích chiếu Z nằm trong [min_area, max_area]
#   3. Output: danh sách polygon, mỗi cái có centroid, area, normal, n_sides
#
# Đầu vào: vertices, faces, overhang_mask, face_normals, min/max_area
# Đầu ra: list[PolygonInfo] — thông tin mỗi đa giác đã chuẩn hóa
#
# Luồng thực thi: worker thread (trong Job.run())
# ==============================================================================

import numpy as np


class PolygonInfo:
    """Thông tin một đa giác đã xử lý (merge/split)."""
    __slots__ = ['centroid', 'area', 'normal', 'n_sides',
                 'face_indices', 'outer_position', 'boundary_verts',
                 'cap_triangles']

    def __init__(self, centroid, area, normal, n_sides, face_indices):
        self.centroid = centroid          # (3,) vị trí trọng tâm
        self.area = area                  # float, diện tích (mm²)
        self.normal = normal              # (3,) outward normal đơn vị
        self.n_sides = n_sides            # int, số cạnh (= len(boundary_verts))
        self.face_indices = face_indices  # list[int] chỉ số face gốc trong overhang
        self.outer_position = None        # (3,) sẽ tính sau = centroid + outward*(gap+thickness)
        self.boundary_verts = None        # (K, 3) đỉnh biên thực tế trên outer surface, theo thứ tự
        self.cap_triangles = None         # (T*3, 3) triangle soup các mặt gốc trên outer surface


def process_polygons(vertices, faces, overhang_mask, face_normals,
                     min_area=0.5, max_area=10.0, gap=0.1, thickness=0.5,
                     merge_max_dist=5.0):
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
        merge_max_dist: float - khoảng cách trọng tâm tối đa để merge (mm)

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

    # --- Khởi tạo groups: mỗi tam giác subdivision là 1 group ---
    group_of = list(range(num_sub))
    groups = {i: [i] for i in range(num_sub)}

    # --- Merge: gộp tam giác nhỏ hơn min_area (distance-based) ---
    _merge_small_polygons(groups, group_of, areas, centroids,
                          sub_normals, min_area, max_area, merge_max_dist)

    # --- Tạo PolygonInfo cho mỗi group ---
    result = []

    for gid, members in groups.items():
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

        # Tạo cap triangles từ các tam giác gốc trên outer surface
        cap_faces = []
        for m in members:
            f = local_sub_faces[m]
            cap_faces.append(outer_verts[f[0]])
            cap_faces.append(outer_verts[f[1]])
            cap_faces.append(outer_verts[f[2]])
        info.cap_triangles = np.array(cap_faces, dtype=np.float64) if cap_faces else None

        result.append(info)

    return result



def _merge_small_polygons(groups, group_of, areas, centroids,
                          normals, min_area, max_area, merge_max_dist):
    """
    Gộp tam giác nhỏ hơn min_area dựa trên khoảng cách trọng tâm XYZ.

    Thuật toán:
      1. Tính trọng tâm tất cả tam giác
      2. Sắp xếp tam giác theo diện tích tăng dần
      3. Với mỗi tam giác nhỏ nhất (chưa merge, area < min_area):
         - Tìm các tam giác khác trong bán kính merge_max_dist (XYZ)
         - Gộp từ gần nhất đến xa nhất
         - Dừng khi diện tích chiếu lên mặt Z >= min_area hoặc > max_area
    """
    num_faces = len(areas)
    if num_faces == 0:
        return

    # Sắp xếp tất cả faces theo diện tích tăng dần
    sorted_faces = sorted(range(num_faces), key=lambda i: areas[i])

    # Duyệt từ nhỏ nhất
    for fi in sorted_faces:
        gid = group_of[fi]

        # Bỏ qua nếu group đã bị xoá (face đã merge vào group khác)
        if gid not in groups:
            continue

        # Tính diện tích chiếu Z hiện tại của group
        cur_proj_area = _projected_z_area(groups[gid], centroids, areas, normals)
        if cur_proj_area >= min_area:
            continue

        # Trọng tâm group hiện tại
        g_members = groups[gid]
        g_areas = areas[g_members]
        total_a = float(np.sum(g_areas))
        if total_a < 1e-12:
            continue
        g_centroid = np.sum(centroids[g_members] * (g_areas / total_a)[:, np.newaxis],
                           axis=0)

        # Tìm tất cả group khác, tính khoảng cách trọng tâm XYZ
        other_gids = []
        other_centroids = []
        for ogid, omembers in groups.items():
            if ogid == gid:
                continue
            oa = areas[omembers]
            ot = float(np.sum(oa))
            if ot < 1e-12:
                continue
            oc = np.sum(centroids[omembers] * (oa / ot)[:, np.newaxis], axis=0)
            other_gids.append(ogid)
            other_centroids.append(oc)

        if not other_gids:
            continue

        other_centroids = np.array(other_centroids)
        dists = np.linalg.norm(other_centroids - g_centroid, axis=1)

        # Lọc trong bán kính merge_max_dist, sắp xếp gần → xa
        within = np.where(dists <= merge_max_dist)[0]
        if len(within) == 0:
            continue
        within = within[np.argsort(dists[within])]

        # Gộp từ gần nhất đến xa nhất
        for idx in within:
            ogid = other_gids[idx]
            if ogid not in groups:
                continue

            # Kiểm tra: tổng diện tích chiếu Z sau merge <= max_area
            merged_members = groups[gid] + groups[ogid]
            merged_proj = _projected_z_area(merged_members, centroids, areas, normals)

            if merged_proj > max_area:
                continue

            # Merge ogid vào gid
            for member in groups[ogid]:
                group_of[member] = gid
            groups[gid] = merged_members
            del groups[ogid]

            if merged_proj >= min_area:
                break


def _projected_z_area(members, centroids, areas, normals):
    """
    Tính diện tích chiếu lên mặt phẳng Z của một nhóm tam giác.

    Diện tích chiếu = Σ (area_i × |nz_i|)
    trong đó nz_i là thành phần Z của normal (đã normalize).
    """
    g_areas = areas[members]
    g_normals = normals[members]
    # |nz| = |cos(góc giữa normal và trục Z)|
    nz_abs = np.abs(g_normals[:, 2])
    # Với normal đã normalize: projected_area = area * |nz|
    nz_lens = np.linalg.norm(g_normals, axis=1)
    nz_unit = np.where(nz_lens > 1e-10, nz_abs / nz_lens, nz_abs)
    return float(np.sum(g_areas * nz_unit))



def _extract_boundary_loop(members, local_faces, outer_verts):
    """
    Trích xuất vòng biên (convex hull) của một nhóm tam giác trên outer surface.

    Lấy tất cả đỉnh của nhóm, chiếu xuống Z = min_z, tính convex hull 2D.

    Tham số:
        members     : list[int] - chỉ số face cục bộ trong nhóm
        local_faces : (K, 3) - mảng face với vertex index cục bộ
        outer_verts : (U, 3) - tọa độ đỉnh trên outer surface

    Trả về:
        numpy array (N, 3) - đỉnh convex hull tại Z=min_z, hoặc None nếu thất bại
    """
    # Thu thập tất cả đỉnh unique của nhóm
    vert_set = set()
    for m in members:
        f = local_faces[m]
        vert_set.add(int(f[0]))
        vert_set.add(int(f[1]))
        vert_set.add(int(f[2]))

    if len(vert_set) < 3:
        return None

    vert_indices = np.array(sorted(vert_set))
    pts = outer_verts[vert_indices]  # (K, 3)

    # Z = min_z của nhóm
    min_z = float(np.min(pts[:, 2]))

    # Convex hull 2D trên XY
    pts_2d = pts[:, :2]
    hull_idx = _convex_hull_2d(pts_2d)
    if len(hull_idx) < 3:
        return None

    # Tạo polygon lồi 3D tại Z = min_z
    result = np.zeros((len(hull_idx), 3), dtype=np.float64)
    for i, hi in enumerate(hull_idx):
        result[i, :2] = pts_2d[hi]
        result[i, 2] = min_z

    return result



def _convex_hull_2d(points_2d):
    """
    Andrew's monotone chain algorithm cho 2D convex hull.
    Trả về danh sách chỉ số đỉnh theo thứ tự CCW.
    """
    n = len(points_2d)
    if n < 3:
        return list(range(n))

    indices = sorted(range(n),
                     key=lambda i: (float(points_2d[i][0]),
                                    float(points_2d[i][1])))

    def cross(o, a, b):
        return ((float(points_2d[a][0]) - float(points_2d[o][0])) *
                (float(points_2d[b][1]) - float(points_2d[o][1])) -
                (float(points_2d[a][1]) - float(points_2d[o][1])) *
                (float(points_2d[b][0]) - float(points_2d[o][0])))

    lower = []
    for i in indices:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], i) <= 0:
            lower.pop()
        lower.append(i)

    upper = []
    for i in reversed(indices):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], i) <= 0:
            upper.pop()
        upper.append(i)

    return lower[:-1] + upper[:-1]


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
