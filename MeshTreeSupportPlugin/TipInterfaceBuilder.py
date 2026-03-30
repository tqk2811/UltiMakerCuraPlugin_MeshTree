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


def build_tip_interfaces(polygons, tip_radius=0.4, ring_thickness=0.3, overhang_angle=45.0, max_area_change_pct=10.0):
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

    # Cos của góc overhang tối đa (dùng cho _connect_rings)
    max_overhang_cos = np.cos(np.radians(overhang_angle))

    # Diện tích octagon: A = 2√2 × r²
    target_area = 2.0 * np.sqrt(2.0) * tip_radius ** 2

    for pi, poly in enumerate(polygons):
        start_area = poly.area
        start_pos = poly.outer_position
        direction = poly.normal.copy()

        # Hướng tip: thẳng xuống theo trục Z
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

        # --- Tạo rings và nối mesh ---
        if has_boundary:
            current_pos = np.mean(ring0_verts, axis=0)
        else:
            current_pos = start_pos.copy()

        # === Khối bám shell ===
        # Gồm 3 phần:
        #   - cap_triangles: mặt tiếp xúc shell (trên cùng)
        #   - side faces: vertical quads nối boundary → đáy
        #   - ring0: đáy phẳng (tất cả đỉnh cùng Z = min_z của boundary)
        if has_boundary:
            shell_boundary = ring0_verts.copy()
            if has_cap:
                cap_arr = poly.cap_triangles.copy()
                n_cap_tris = len(cap_arr) // 3
                cap_up = 0
                cap_down = 0
                for ct in range(n_cap_tris):
                    cv0 = cap_arr[ct * 3]
                    cv1 = cap_arr[ct * 3 + 1]
                    cv2 = cap_arr[ct * 3 + 2]
                    cfn = np.cross(cv1 - cv0, cv2 - cv0)
                    if cfn[2] >= 0:
                        cap_up += 1
                    else:
                        cap_down += 1
                Logger.log("d", "  Cap faces: %d tris, UP(Z+)=%d, DOWN(Z-)=%d", n_cap_tris, cap_up, cap_down)
                all_soup.append(cap_arr)

            min_z = np.min(shell_boundary[:, 2])
            ring0 = shell_boundary.copy()
            ring0[:, 2] = min_z

            # Side faces: vertical quads nối shell_boundary → ring0
            side_verts = []
            nv = len(shell_boundary)
            for k in range(nv):
                k_next = (k + 1) % nv
                top0 = shell_boundary[k]
                top1 = shell_boundary[k_next]
                bot0 = ring0[k]
                bot1 = ring0[k_next]
                side_verts.extend([top0, bot0, top1])
                side_verts.extend([top1, bot0, bot1])
            if side_verts:
                side_arr = np.array(side_verts, dtype=np.float64)
                # Debug: check side face winding
                n_side_tris = len(side_arr) // 3
                side_center = np.mean(shell_boundary, axis=0)
                side_out = 0
                side_in = 0
                for st in range(n_side_tris):
                    sv0 = side_arr[st * 3]
                    sv1 = side_arr[st * 3 + 1]
                    sv2 = side_arr[st * 3 + 2]
                    sfn = np.cross(sv1 - sv0, sv2 - sv0)
                    stc = (sv0 + sv1 + sv2) / 3.0
                    srad = stc - side_center
                    if np.dot(sfn, srad) >= 0:
                        side_out += 1
                    else:
                        side_in += 1
                Logger.log("d", "  Side faces: %d tris, OUT=%d, IN=%d", n_side_tris, side_out, side_in)
                if side_in > side_out:
                    Logger.log("d", "  Side faces: majority IN → flipping all")
                    for st in range(n_side_tris):
                        side_arr[st * 3 + 1], side_arr[st * 3 + 2] = side_arr[st * 3 + 2].copy(), side_arr[st * 3 + 1].copy()
                all_soup.append(side_arr)

            # Cập nhật start_area = diện tích thực của ring0 (sau project)
            start_area = _polygon_area_3d(ring0)
            if start_area < 1e-10:
                start_area = poly.area  # fallback

            prev_ring = ring0
            current_pos[2] = min_z

            # DEBUG: log ring0
            Logger.log("d", "  Ring0: n=%d, area=%.3f, center=(%.2f,%.2f,%.2f), Z_range=[%.3f,%.3f]",
                       len(ring0), start_area,
                       np.mean(ring0, axis=0)[0], np.mean(ring0, axis=0)[1], np.mean(ring0, axis=0)[2],
                       np.min(ring0[:, 2]), np.max(ring0[:, 2]))
            for vi in range(len(ring0)):
                Logger.log("d", "    v%d: (%.3f, %.3f, %.3f)", vi,
                           ring0[vi][0], ring0[vi][1], ring0[vi][2])
        else:
            prev_ring = _make_ring(current_pos, tip_dir, start_n,
                                   _radius_from_area(start_area, start_n))
            prev_ring[:, 2] = current_pos[2]

        # === Số ring: tính từ max_area_change_pct ===
        # Mỗi ring thay đổi tối đa max_area_change_pct% diện tích
        max_change_frac = max_area_change_pct / 100.0
        if max_change_frac > 0 and abs(start_area - target_area) > 1e-10:
            # Số ring tối thiểu để không vượt quá max_change_frac mỗi bước
            min_rings_by_area = int(np.ceil(
                abs(start_area - target_area) / (start_area * max_change_frac)
            ))
            num_rings = max(3, min(min_rings_by_area, 30))
        else:
            num_rings = max(3, min(abs(start_n - 8) + 1, 8))

        # === Ring 1..num_rings: lerp đều từ start → target, clamp mỗi bước ===
        prev_area = start_area
        for ri in range(1, num_rings + 1):
            t = ri / num_rings  # 0 < t <= 1.0

            n = max(round(start_n + (8 - start_n) * t), 3)
            a = start_area + (target_area - start_area) * t

            # Clamp: diện tích chỉ thay đổi tối đa max_area_change_pct% so với ring trước
            max_delta = prev_area * max_change_frac
            a = np.clip(a, prev_area - max_delta, prev_area + max_delta)
            prev_area = a

            r = _radius_from_area(a, n)

            current_pos = current_pos + tip_dir * ring_thickness
            ring = _make_ring(current_pos, tip_dir, n, r)
            ring[:, 2] = current_pos[2]

            # DEBUG: log ring info
            ring_area_actual = _polygon_area_3d(ring)
            ring_center = np.mean(ring, axis=0)
            Logger.log("d", "  Ring %d: n=%d, target_a=%.3f, actual_a=%.3f, r=%.3f, "
                       "center=(%.2f,%.2f,%.2f), Z_range=[%.3f,%.3f], blend=%s",
                       ri, n, a, ring_area_actual, r,
                       ring_center[0], ring_center[1], ring_center[2],
                       np.min(ring[:, 2]), np.max(ring[:, 2]),
                       "no")
            if ri <= 2:
                for vi in range(len(ring)):
                    Logger.log("d", "    v%d: (%.3f, %.3f, %.3f)", vi,
                               ring[vi][0], ring[vi][1], ring[vi][2])

            # Đảm bảo ring_thickness trên trục Z
            prev_min_z = np.min(prev_ring[:, 2])
            ring_max_z = np.max(ring[:, 2])
            z_gap = prev_min_z - ring_max_z
            if z_gap < ring_thickness:
                dz = ring_thickness - z_gap
                ring[:, 2] -= dz
                current_pos[2] -= dz

            tris = _connect_rings(prev_ring, ring, max_overhang_cos)
            all_soup.append(tris)
            prev_ring = ring

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


def _align_ring(ring, target):
    """Xoay vòng (cyclic shift) ring sao cho tổng khoảng cách đỉnh-đỉnh tới target nhỏ nhất."""
    n = len(ring)
    if n != len(target):
        return ring
    best_shift = 0
    best_dist = np.inf
    for shift in range(n):
        d = np.sum(np.linalg.norm(np.roll(ring, shift, axis=0) - target, axis=1))
        if d < best_dist:
            best_dist = d
            best_shift = shift
    return np.roll(ring, best_shift, axis=0)


def _polygon_area_3d(ring):
    """Tính diện tích polygon 3D bằng Shoelace (cross product sum)."""
    n = len(ring)
    if n < 3:
        return 0.0
    total = np.zeros(3)
    for i in range(n):
        total += np.cross(ring[i], ring[(i + 1) % n])
    return 0.5 * np.linalg.norm(total)


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


def _connect_rings(ring0, ring1, max_overhang_cos=0.7071):
    """
    Nối 2 ring bằng triangle strip, căn chỉnh theo đỉnh gần nhất.
    Đảm bảo cả 2 ring đi cùng chiều (CCW nhìn từ ngoài) trước khi nối.
    Ưu tiên chọn tam giác có góc normal với Z trong giới hạn overhang.

    max_overhang_cos: cos(overhang_angle), mặc định cos(45°) ≈ 0.7071

    Trả về: numpy array (T*3, 3) triangle soup
    """
    n0 = len(ring0)
    n1 = len(ring1)

    ring0_center = np.mean(ring0, axis=0)
    ring1_center = np.mean(ring1, axis=0)
    axis_mid = (ring0_center + ring1_center) * 0.5
    axis_vec = ring1_center - ring0_center
    axis_len = np.linalg.norm(axis_vec)
    axis_dir = axis_vec / axis_len if axis_len > 1e-10 else np.array([0.0, 0.0, -1.0])

    # Đảm bảo cả 2 ring cùng chiều (CCW nhìn từ axis_dir)
    def _signed_area_on_axis(ring, center, axis):
        total = 0.0
        for k in range(len(ring)):
            v0 = ring[k] - center
            v1 = ring[(k + 1) % len(ring)] - center
            total += np.dot(np.cross(v0, v1), axis)
        return total

    if _signed_area_on_axis(ring0, ring0_center, axis_dir) < 0:
        ring0 = ring0[::-1].copy()
    if _signed_area_on_axis(ring1, ring1_center, axis_dir) < 0:
        ring1 = ring1[::-1].copy()

    # Tìm ring1 vertex gần ring0[0] nhất (3D) → starting index
    dists = np.linalg.norm(ring1 - ring0[0], axis=1)
    idx = int(np.argmin(dists))

    # Zipper: bước qua cả 2 ring theo tỷ lệ
    # Mỗi bước tạo 2 triangle (1 quad) giữa ring0[i]→ring0[i+1] và ring1[j]→ring1[j+1]
    tris = []
    n_max = max(n0, n1)
    for step in range(n_max):
        i0 = step * n0 // n_max
        i0_next = ((step + 1) * n0 // n_max) % n0
        j1 = (idx + step * n1 // n_max) % n1
        j1_next = (idx + (step + 1) * n1 // n_max) % n1

        # Triangle 1: ring0[i0], ring1[j1], ring0[i0_next]
        tris.append([ring0[i0], ring1[j1], ring0[i0_next]])
        # Triangle 2: ring0[i0_next], ring1[j1], ring1[j1_next]
        tris.append([ring0[i0_next], ring1[j1], ring1[j1_next]])

    result = np.array(tris, dtype=np.float64).reshape(-1, 3)

    # Post-process: check winding bằng majority vote, flip tất cả nếu sai
    num_tris_out = len(result) // 3
    if num_tris_out > 0:
        vote = 0
        tri_info = []
        for t in range(num_tris_out):
            v0 = result[t * 3]
            v1 = result[t * 3 + 1]
            v2 = result[t * 3 + 2]
            fn = np.cross(v1 - v0, v2 - v0)
            fn_len = np.linalg.norm(fn)
            fn_unit = fn / fn_len if fn_len > 1e-10 else np.array([0.0, 0.0, 0.0])
            tc = (v0 + v1 + v2) / 3.0
            radial = tc - axis_mid
            dot_val = np.dot(fn, radial)
            tri_info.append((t, fn_unit, fn_len, dot_val))
            if dot_val >= 0:
                vote += 1
            else:
                vote -= 1

        Logger.log("d", "[_connect_rings] vote=%d, axis_mid=%s, axis_dir=%s", vote, axis_mid, axis_dir)
        for t, fn_unit, fn_len, dot_val in tri_info:
            Logger.log("d", "  tri[%d]: normal=(%.3f,%.3f,%.3f) area=%.4f radial_dot=%.4f %s",
                        t, fn_unit[0], fn_unit[1], fn_unit[2], fn_len * 0.5, dot_val,
                        "OUT" if dot_val >= 0 else "IN")

        if vote < 0:
            Logger.log("d", "[_connect_rings] flipping all triangles (vote < 0)")
            for t in range(num_tris_out):
                result[t * 3 + 1], result[t * 3 + 2] = result[t * 3 + 2].copy(), result[t * 3 + 1].copy()

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
