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
from UM.Logger import Logger


class PointA:
    """Thông tin một điểm A (đầu ra tip interface, đầu vào branch router)."""
    __slots__ = ['position', 'radius', 'area', 'direction', 'polygon_index']

    def __init__(self, position, radius, area, direction, polygon_index):
        self.position = position      # (3,) tọa độ Point A
        self.radius = radius          # float, bán kính octagon
        self.area = area              # float, diện tích cross-section tại Point A
        self.direction = direction    # (3,) hướng đi ban đầu (outward, gravity-biased)
        self.polygon_index = polygon_index  # int, chỉ số polygon gốc


def build_tip_interfaces(polygons, tip_radius=0.4, ring_thickness=0.3):
    """
    Tạo tip interface mesh cho tất cả đa giác.

    Tham số:
        polygons       : list[PolygonInfo] từ PolygonProcessor
        tip_radius     : float - bán kính tại Point A (mm)
        ring_thickness : float - độ dày mỗi ring (mm)

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
        # Dùng center thực tế của ring0 (boundary_verts) thay vì outer_position
        # để tránh lệch giữa ring0 và ring1
        if has_boundary:
            current_pos = np.mean(ring0_verts, axis=0)
        else:
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
                regular_ring = _make_ring(current_pos, tip_dir, n, r)

                # Blend: step đầu tiên (step=1) gần ring0 hơn để giảm overhang
                # t=0 → giống ring0, t=1 → regular polygon hoàn toàn
                if has_boundary and step <= 2:
                    resampled = _resample_ring(
                        ring0_verts + (current_pos - np.mean(ring0_verts, axis=0)),
                        n)
                    # Scale resampled về đúng radius
                    res_center = np.mean(resampled, axis=0)
                    res_radii = np.linalg.norm(resampled - res_center, axis=1, keepdims=True)
                    avg_res_r = np.mean(res_radii)
                    if avg_res_r > 1e-10:
                        resampled = res_center + (resampled - res_center) * (r / avg_res_r)
                    blend_t = step / min(3, num_steps)  # blend dần qua 3 steps
                    ring = resampled * (1.0 - blend_t) + regular_ring * blend_t
                else:
                    ring = regular_ring

            if prev_ring is not None:
                tris = _connect_rings(prev_ring, ring)
                # Debug: log ring0→ring1 connection
                num_t = len(tris) // 3
                areas = []
                for tt in range(num_t):
                    tv0, tv1, tv2 = tris[tt*3], tris[tt*3+1], tris[tt*3+2]
                    area = np.linalg.norm(np.cross(tv1 - tv0, tv2 - tv0)) * 0.5
                    areas.append(area)
                areas = np.array(areas)
                degen = np.sum(areas < 1e-6)
                Logger.log("d", f"TipInterface poly={pi} step={step}: "
                           f"ring0={len(prev_ring)} ring1={len(ring)} "
                           f"tris={num_t} degen={degen} "
                           f"area_min={areas.min():.6f} area_max={areas.max():.6f}")
                all_soup.append(tris)

            prev_ring = ring

            if step < num_steps:
                current_pos = current_pos + tip_dir * ring_thickness
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
    Đảm bảo cả 2 ring đi cùng chiều (CCW nhìn từ ngoài) trước khi nối.

    Trả về: numpy array (T*3, 3) triangle soup
    """
    n0 = len(ring0)
    n1 = len(ring1)

    ring0_center = np.mean(ring0, axis=0)
    ring1_center = np.mean(ring1, axis=0)
    axis_vec = ring1_center - ring0_center
    axis_len = np.linalg.norm(axis_vec)
    if axis_len > 1e-10:
        axis_dir = axis_vec / axis_len
    else:
        axis_dir = np.array([0.0, 0.0, 1.0])

    # Đảm bảo ring0 đi CCW khi nhìn từ phía axis_dir
    # Signed area projected lên axis: dương = CCW
    def _signed_area_on_axis(ring, center, axis):
        total = 0.0
        n = len(ring)
        for k in range(n):
            v0 = ring[k] - center
            v1 = ring[(k + 1) % n] - center
            total += np.dot(np.cross(v0, v1), axis)
        return total

    if _signed_area_on_axis(ring0, ring0_center, axis_dir) < 0:
        ring0 = ring0[::-1].copy()
    if _signed_area_on_axis(ring1, ring1_center, axis_dir) < 0:
        ring1 = ring1[::-1].copy()

    # Căn chỉnh điểm bắt đầu: ring1[j] gần ring0[0] nhất
    dists = np.linalg.norm(ring1 - ring0[0], axis=1)
    best_offset = int(np.argmin(dists))
    ring1 = np.roll(ring1, -best_offset, axis=0)

    # Advancing front
    tris = []
    i, j = 0, 0
    steps_i, steps_j = 0, 0

    while steps_i < n0 or steps_j < n1:
        i_next = (i + 1) % n0
        j_next = (j + 1) % n1

        can_i = steps_i < n0
        can_j = steps_j < n1

        if can_i and can_j:
            diag_a = np.linalg.norm(ring0[i_next] - ring1[j])
            diag_b = np.linalg.norm(ring0[i] - ring1[j_next])
            advance_i = diag_a <= diag_b
        else:
            advance_i = can_i

        if advance_i:
            tris.append([ring0[i], ring0[i_next], ring1[j]])
            i = i_next
            steps_i += 1
        else:
            tris.append([ring0[i], ring1[j_next], ring1[j]])
            j = j_next
            steps_j += 1

    result = np.array(tris, dtype=np.float64).reshape(-1, 3)

    # Post-process: cả 2 ring đã CCW → winding nhất quán
    # Chỉ cần check 1 tam giác, nếu sai thì flip TẤT CẢ
    num_tris_out = len(result) // 3
    if num_tris_out > 0:
        # Dùng majority vote từ vài tam giác để tránh sai do 1 tam giác degenerate
        mid_center = (ring0_center + ring1_center) * 0.5
        vote = 0
        check_count = min(num_tris_out, 5)
        step = max(1, num_tris_out // check_count)
        for t in range(0, num_tris_out, step):
            if t >= num_tris_out:
                break
            v0 = result[t * 3]
            v1 = result[t * 3 + 1]
            v2 = result[t * 3 + 2]
            fn = np.cross(v1 - v0, v2 - v0)
            tc = (v0 + v1 + v2) / 3.0
            if np.dot(fn, tc - mid_center) >= 0:
                vote += 1
            else:
                vote -= 1
        Logger.log("d", f"_connect_rings: n0={n0} n1={n1} tris={num_tris_out} vote={vote}")
        if vote < 0:
            for t in range(num_tris_out):
                tmp = result[t * 3 + 1].copy()
                result[t * 3 + 1] = result[t * 3 + 2]
                result[t * 3 + 2] = tmp

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
