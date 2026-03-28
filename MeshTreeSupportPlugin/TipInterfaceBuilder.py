# ==============================================================================
# Module: Tạo Tip Interface (Tip Interface Builder)
#
# Tạo mesh chuyển tiếp từ đa giác shell → octagon r=tip_radius (Point A).
# Morphing: tăng số cạnh dần (n → 8), giảm diện tích theo hệ số.
# Chiều cao mỗi bước tỷ lệ với diện tích tại bước đó.
#
# Đầu vào: list[PolygonInfo] từ PolygonProcessor
# Đầu ra: tip mesh (triangle soup) + danh sách Point A
#
# Luồng thực thi: worker thread (trong Job.run())
# ==============================================================================

import numpy as np


class PointA:
    """Thông tin một điểm A (đầu ra tip interface, đầu vào branch router)."""
    __slots__ = ['position', 'radius', 'area', 'direction', 'polygon_index']

    def __init__(self, position, radius, area, direction, polygon_index):
        self.position = position      # (3,) tọa độ Point A
        self.radius = radius          # float, bán kính octagon
        self.area = area              # float, diện tích cross-section tại Point A
        self.direction = direction    # (3,) hướng đi ban đầu (outward, gravity-biased)
        self.polygon_index = polygon_index  # int, chỉ số polygon gốc


def build_tip_interfaces(polygons, tip_radius=0.4, height_factor=0.5, ring_thickness=0.3):
    """
    Tạo tip interface mesh cho tất cả đa giác.

    Mỗi polygon → morphing frustum từ n-gon (diện tích gốc) → octagon (r=tip_radius).
    Chiều cao mỗi bước tỷ lệ diện tích: step_height = area_at_step × height_factor.

    Tham số:
        polygons       : list[PolygonInfo] từ PolygonProcessor
        tip_radius     : float - bán kính tại Point A (mm)
        height_factor  : float - hệ số chiều cao tip (mm/mm²)
        ring_thickness : float - độ dày cố định mỗi ring (mm)

    Trả về:
        tip_verts   : numpy array (V, 3) float32 - triangle soup
        tip_normals : numpy array (V, 3) float32 - triangle soup normals
        points_a    : list[PointA] - danh sách Point A cho branch routing
    """
    if not polygons:
        return (np.zeros((0, 3), dtype=np.float32),
                np.zeros((0, 3), dtype=np.float32),
                [])

    all_soup = []
    points_a = []

    # Diện tích octagon: A = 2√2 × r²
    target_area = 2.0 * np.sqrt(2.0) * tip_radius ** 2

    for pi, poly in enumerate(polygons):
        start_area = poly.area
        start_pos = poly.outer_position
        direction = poly.normal.copy()

        # Hướng tip: gravity-biased (nghiêng về phía -Z)
        tip_dir = direction * 0.5 + np.array([0.0, 0.0, -1.0]) * 0.5
        tip_len = np.linalg.norm(tip_dir)
        if tip_len > 1e-10:
            tip_dir /= tip_len
        else:
            tip_dir = np.array([0.0, 0.0, -1.0])

        # Ring đầu tiên = boundary thực tế từ shell (đúng góc, đúng số cạnh)
        has_boundary = (poly.boundary_verts is not None and
                        len(poly.boundary_verts) >= 3)
        has_cap = (poly.cap_triangles is not None and
                   len(poly.cap_triangles) >= 3)
        if has_boundary:
            ring0_verts = poly.boundary_verts  # (N, 3) actual shape
            start_n = len(ring0_verts)
        else:
            start_n = min(poly.n_sides, 8)
            ring0_verts = None  # sẽ dùng _make_ring fallback

        # Nếu diện tích bắt đầu nhỏ hơn hoặc bằng target → tip tối giản
        if start_area <= target_area * 1.1:
            pt = PointA(
                position=start_pos.copy(),
                radius=tip_radius,
                area=target_area,
                direction=tip_dir.copy(),
                polygon_index=pi
            )
            points_a.append(pt)
            continue

        # --- Tính các bước morphing ---
        # Số bước dựa trên khoảng cách giữa start_n và 8
        if start_n <= 8:
            num_steps = max(8 - start_n, 1)
        else:
            # Đa giác > 8 cạnh: giảm dần về 8
            num_steps = max(start_n - 8, 1)

        # Hệ số co diện tích mỗi bước
        shrink_factor = (target_area / start_area) ** (1.0 / num_steps)

        # --- Tạo rings và nối mesh ---
        current_pos = start_pos.copy()
        current_area = start_area
        prev_ring = None

        for step in range(num_steps + 1):
            if step == 0 and has_boundary:
                # Bước đầu: dùng boundary thực tế từ shell
                ring = ring0_verts.copy()
                # Thêm cap (mặt phẳng tiếp xúc shell) từ tam giác gốc
                if has_cap:
                    all_soup.append(poly.cap_triangles.copy())
            elif step == num_steps:
                # Bước cuối: chính xác octagon target
                ring = _make_ring(current_pos, tip_dir, 8, tip_radius)
            else:
                # Bước trung gian: regular polygon
                if start_n <= 8:
                    n = min(start_n + step, 8)
                else:
                    n = max(start_n - step, 8)
                a = current_area
                r = _radius_from_area(a, n)
                ring = _make_ring(current_pos, tip_dir, n, r)

            if prev_ring is not None:
                tris = _connect_rings(prev_ring, ring)
                all_soup.append(tris)

            prev_ring = ring

            if step < num_steps:
                # Dùng ring_thickness nếu > 0, ngược lại dùng height_factor * area
                if ring_thickness > 0:
                    step_h = ring_thickness
                else:
                    step_h = max(current_area * height_factor, 0.2)
                current_pos = current_pos + tip_dir * step_h
                current_area *= shrink_factor

        # Point A = vị trí cuối tip
        pt = PointA(
            position=current_pos.copy(),
            radius=tip_radius,
            area=target_area,
            direction=tip_dir.copy(),
            polygon_index=pi
        )
        points_a.append(pt)

    # --- Ghép tất cả mesh ---
    if all_soup:
        all_verts = np.concatenate(all_soup, axis=0)
    else:
        all_verts = np.zeros((0, 3), dtype=np.float64)

    # Tính normals
    tip_verts, tip_normals = _compute_soup_normals(all_verts)

    return tip_verts, tip_normals, points_a


def _radius_from_area(area, n):
    """Tính bán kính regular n-gon từ diện tích. A = (n/2) × r² × sin(2π/n)."""
    if n < 3 or area <= 0:
        return 0.001
    denom = 0.5 * n * np.sin(2.0 * np.pi / n)
    if denom < 1e-10:
        return 0.001
    return np.sqrt(area / denom)


def _make_ring(center, axis, n_sides, radius):
    """
    Tạo ring (vòng đỉnh) regular n-gon tại vị trí center,
    vuông góc với axis, bán kính radius.

    Trả về: numpy array (n_sides, 3)
    """
    # Tìm 2 vector vuông góc với axis
    axis = axis / (np.linalg.norm(axis) + 1e-10)

    # Chọn vector tham chiếu không song song axis
    if abs(axis[0]) < 0.9:
        ref = np.array([1.0, 0.0, 0.0])
    else:
        ref = np.array([0.0, 1.0, 0.0])

    u = np.cross(axis, ref)
    u /= (np.linalg.norm(u) + 1e-10)
    v = np.cross(axis, u)
    v /= (np.linalg.norm(v) + 1e-10)

    angles = np.linspace(0, 2 * np.pi, n_sides, endpoint=False)
    ring = np.zeros((n_sides, 3), dtype=np.float64)
    for i, a in enumerate(angles):
        ring[i] = center + radius * (np.cos(a) * u + np.sin(a) * v)

    return ring


def _connect_rings(ring0, ring1):
    """
    Nối 2 ring bằng triangle strip, căn chỉnh theo đỉnh gần nhất.

    Trả về: numpy array (T*3, 3) triangle soup
    """
    n0 = len(ring0)
    n1 = len(ring1)

    if n0 != n1:
        target_n = max(n0, n1)
        if n0 < n1:
            ring0 = _resample_ring(ring0, target_n)
            n0 = target_n
        else:
            ring1 = _resample_ring(ring1, target_n)
            n1 = target_n

    # Tìm offset tốt nhất: ring1[offset] gần ring0[0] nhất
    dists = np.linalg.norm(ring1 - ring0[0], axis=1)
    best_offset = int(np.argmin(dists))
    ring1 = np.roll(ring1, -best_offset, axis=0)

    # Quad strip
    tris = []
    for i in range(n0):
        i_next = (i + 1) % n0
        tris.append([ring0[i], ring0[i_next], ring1[i]])
        tris.append([ring0[i_next], ring1[i_next], ring1[i]])

    result = np.array(tris, dtype=np.float64).reshape(-1, 3)

    # Post-process: đảm bảo normals hướng ra ngoài
    axis_center = 0.5 * (np.mean(ring0, axis=0) + np.mean(ring1, axis=0))
    num_tris_out = len(result) // 3
    for t in range(num_tris_out):
        v0 = result[t * 3]
        v1 = result[t * 3 + 1]
        v2 = result[t * 3 + 2]
        face_normal = np.cross(v1 - v0, v2 - v0)
        outward = (v0 + v1 + v2) / 3.0 - axis_center
        if np.dot(face_normal, outward) < 0:
            result[t * 3 + 1] = v2
            result[t * 3 + 2] = v1

    return result


def _resample_ring(ring, target_n):
    """
    Resample ring (M đỉnh) thành target_n đỉnh bằng interpolation dọc boundary.
    Giữ hình dạng ring, chỉ thay đổi số đỉnh.
    """
    m = len(ring)
    if m == target_n:
        return ring.copy()

    # Tính cumulative arc length dọc ring (closed loop)
    diffs = np.diff(ring, axis=0, append=ring[:1])  # wrap around
    seg_lengths = np.linalg.norm(diffs, axis=1)
    cum_len = np.cumsum(seg_lengths)
    total_len = cum_len[-1]

    if total_len < 1e-10:
        return np.tile(ring[0], (target_n, 1))

    cum_len_normalized = cum_len / total_len  # [0..1], cum_len_normalized[-1] = 1.0

    # Tạo target_n điểm phân bố đều trên [0, 1)
    target_params = np.linspace(0, 1, target_n, endpoint=False)

    result = np.zeros((target_n, 3), dtype=np.float64)
    for i, t in enumerate(target_params):
        # Tìm segment chứa t
        # cum_len_normalized[j-1] <= t < cum_len_normalized[j]
        idx = np.searchsorted(cum_len_normalized, t, side='right')
        idx = idx % m

        prev_cum = cum_len_normalized[idx - 1] if idx > 0 else 0.0
        next_cum = cum_len_normalized[idx]
        seg_range = next_cum - prev_cum
        if seg_range < 1e-10:
            frac = 0.0
        else:
            frac = (t - prev_cum) / seg_range

        p0 = ring[idx]
        p1 = ring[(idx + 1) % m]
        result[i] = p0 + frac * (p1 - p0)

    return result


def _compute_soup_normals(all_verts):
    """Tính face normals cho triangle soup."""
    if len(all_verts) == 0:
        return (np.zeros((0, 3), dtype=np.float32),
                np.zeros((0, 3), dtype=np.float32))

    num_tris = len(all_verts) // 3
    sv0 = all_verts[0::3]
    sv1 = all_verts[1::3]
    sv2 = all_verts[2::3]

    e1 = sv1 - sv0
    e2 = sv2 - sv0
    fn = np.cross(e1, e2)
    fn_len = np.linalg.norm(fn, axis=1, keepdims=True)
    fn_len = np.maximum(fn_len, 1e-10)
    fn /= fn_len

    all_normals = np.zeros_like(all_verts)
    all_normals[0::3] = fn
    all_normals[1::3] = fn
    all_normals[2::3] = fn

    return all_verts.astype(np.float32), all_normals.astype(np.float32)
