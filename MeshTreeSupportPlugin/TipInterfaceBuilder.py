# ==============================================================================
# Module: Tao Tip Interface (Tip Interface Builder)
#
# Thuat toan:
#   1. Giu nguyen co che gop/chia tam giac (PolygonProcessor)
#   2. Chieu boundary xuong Z=min_z, lap day khoi tu shell xuong mat chieu
#   3. Bien da giac lom -> loi (convex hull)
#   4. Tim trong tam, chieu xuong Z theo tip_height
#   5. Ve hinh tron tai dau tip (ban kinh tip_radius, so canh cylinder_segments)
#   6. Ve duong cong Bezier tu vien da giac loi -> vien hinh tron,
#      tuan thu overhang_angle. Lap day nhua cho khoi nay.
#
# Dau vao: list[PolygonInfo] tu PolygonProcessor
# Dau ra: tip mesh (triangle soup) + danh sach Point A
#
# Luong thuc thi: worker thread (trong Job.run())
# ==============================================================================

import numpy as np
from UM.Logger import Logger


class PointA:
    """Thong tin mot diem A (dau ra tip interface, dau vao branch router)."""
    __slots__ = ['position', 'radius', 'area', 'direction', 'polygon_index']

    def __init__(self, position, radius, area, direction, polygon_index):
        self.position = position      # (3,) toa do Point A
        self.radius = radius          # float, ban kinh octagon
        self.area = area              # float, dien tich cross-section tai Point A
        self.direction = direction    # (3,) huong di ban dau (outward, gravity-biased)
        self.polygon_index = polygon_index  # int, chi so polygon goc


def build_tip_interfaces(polygons, tip_radius=0.4, ring_thickness=0.3,
                         overhang_angle=45.0, tip_height=10.0,
                         cylinder_segments=8):
    """
    Tao tip interface mesh cho tat ca da giac.

    Tham so:
        polygons          : list[PolygonInfo] tu PolygonProcessor
        tip_radius        : float - ban kinh hinh tron dau tip (mm)
        ring_thickness    : float - khoang cach Z giua cac ring trung gian (mm)
        overhang_angle    : float - goc overhang toi da (do)
        tip_height        : float - chieu cao tip tu shell xuong hinh tron (mm)
        cylinder_segments : int - so canh hinh tron dau tip

    Tra ve:
        tip_verts   : numpy array (V, 3) float32 - triangle soup
        tip_normals : numpy array (V, 3) float32 - triangle soup normals
        points_a    : list[PointA] - danh sach Point A cho branch routing
    """
    if not polygons:
        return (np.zeros((0, 3), dtype=np.float32),
                np.zeros((0, 3), dtype=np.float32),
                [])

    all_soup = []
    points_a = []

    target_area = 2.0 * np.sqrt(2.0) * tip_radius ** 2
    tip_dir = np.array([0.0, 0.0, -1.0])
    tan_overhang = np.tan(np.radians(overhang_angle))

    for pi, poly in enumerate(polygons):
        has_boundary = (poly.boundary_verts is not None and
                        len(poly.boundary_verts) >= 3)
        has_cap = (poly.cap_triangles is not None and
                   len(poly.cap_triangles) >= 3)

        # Da giac qua nho: bo qua tip interface, chi tao PointA
        if poly.area <= target_area * 1.1 or not has_boundary:
            pt = PointA(
                position=poly.outer_position.copy(),
                radius=tip_radius,
                area=target_area,
                direction=tip_dir.copy(),
                polygon_index=pi
            )
            points_a.append(pt)
            continue

        shell_boundary = poly.boundary_verts.copy()
        min_z = float(np.min(shell_boundary[:, 2]))

        # =================================================================
        # BUOC 2: Convex hull - bien da giac lom thanh loi
        # =================================================================
        projected = shell_boundary.copy()
        projected[:, 2] = min_z

        convex = _make_convex_polygon(projected)
        if len(convex) < 3:
            convex = projected.copy()

        Logger.log("d", "  Polygon %d: boundary=%d verts, convex=%d verts, "
                   "min_z=%.2f", pi, len(projected), len(convex), min_z)

        # =================================================================
        # BUOC 3: Lap day khoi tu shell xuong convex hull tai Z=min_z
        # =================================================================

        # (a) Cap triangles - mat tren (mat tiep xuc shell)
        if has_cap:
            all_soup.append(poly.cap_triangles.copy())

        # (b) Side walls: thanh ben tu shell_boundary xuong projected (cung so dinh, cung thu tu)
        sides = _make_side_walls(shell_boundary, projected)
        if sides is not None and len(sides) > 0:
            all_soup.append(sides)

        # =================================================================
        # BUOC 4-5: Tim trong tam, tao hinh tron tai dau tip
        # =================================================================
        centroid = np.mean(convex, axis=0)

        # Khoang cach ngang lon nhat tu trong tam toi dinh da giac loi
        d_horiz_arr = np.linalg.norm(convex[:, :2] - centroid[:2], axis=1)
        max_d_horiz = float(np.max(d_horiz_arr))

        # Dieu chinh chieu cao tip de dam bao overhang constraint
        # Tai t=0.5 cua Bezier: horizontal_speed = 1.5 * d_horiz,
        #                        vertical_speed = effective_height
        # Rang buoc: 1.5 * d_horiz / effective_height < tan(overhang)
        if tan_overhang > 1e-10:
            min_required_height = 1.5 * max_d_horiz / tan_overhang
        else:
            min_required_height = max_d_horiz * 100.0
        effective_height = max(tip_height, min_required_height * 1.1)

        circle_center = np.array([centroid[0], centroid[1],
                                  min_z - effective_height])

        # (c) Skirt: lap vung annular giua projected (lom) va convex (loi), face up
        skirt = _fill_ring(projected, convex)
        if skirt is not None and len(skirt) > 0:
            all_soup.append(skirt)

        # (d) Cap tai Z=min_z: lap day toan bo convex, face down (-Z)
        cap_bottom = _triangulate_convex(convex, face_down=True)
        if cap_bottom is not None and len(cap_bottom) > 0:
            all_soup.append(cap_bottom)

        Logger.log("d", "  Circle: center=(%.2f,%.2f,%.2f), r=%.2f, "
                   "effective_h=%.2f, max_d_horiz=%.2f, N=%d",
                   circle_center[0], circle_center[1], circle_center[2],
                   tip_radius, effective_height, max_d_horiz, len(convex))

        # =================================================================
        # BUOC 6: Be mat Bezier tu convex (N dinh) -> hinh tron (cylinder_segments dinh)
        # So dinh tang dan deu theo chieu cao
        # =================================================================
        n_levels = max(8, min(int(effective_height / ring_thickness), 40))
        surface = _build_bezier_surface(convex, circle_center, tip_radius,
                                        effective_height, n_levels,
                                        cylinder_segments,
                                        tan_overhang=tan_overhang)
        if surface is not None and len(surface) > 0:
            all_soup.append(surface)

        # PointA tai tam hinh tron
        pt = PointA(
            position=circle_center.copy(),
            radius=tip_radius,
            area=target_area,
            direction=tip_dir.copy(),
            polygon_index=pi
        )
        points_a.append(pt)

    # --- Ghep tat ca mesh ---
    if all_soup:
        all_verts = np.concatenate(all_soup, axis=0)
    else:
        all_verts = np.zeros((0, 3), dtype=np.float64)

    tip_verts, tip_normals = _compute_soup_normals(all_verts)
    return tip_verts, tip_normals, points_a


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def _fill_ring(inner_ring, outer_ring):
    """
    Lap day vung giua 2 boundary (inner va outer) tai cung Z.
    inner_ring: (M, 3) - boundary trong (co the lom)
    outer_ring: (N, 3) - boundary ngoai (convex hull)
    Tra ve triangle soup, face up (+Z).

    Thuat toan: zipper - di dong dong thoi tren 2 ring,
    chon canh ngan nhat de tao tam giac tiep theo.
    """
    M = len(inner_ring)
    N = len(outer_ring)
    if M < 3 or N < 3:
        return None

    # Tim diem bat dau: dinh inner gan nhat voi outer[0]
    dists = np.linalg.norm(inner_ring[:, :2] - outer_ring[0, :2], axis=1)
    i_start = int(np.argmin(dists))

    # Tong so tam giac = M + N - 2 (zipper M+N dinh, 2 dau noi vong)
    # Moi buoc tien 1 dinh tren inner hoac outer, tong cong M+N lan tien
    tris = []
    i = i_start
    j = 0
    i_count = 0  # so lan da tien tren inner
    j_count = 0  # so lan da tien tren outer

    for _ in range(M + N):
        i_next = (i + 1) % M
        j_next = (j + 1) % N

        can_advance_i = i_count < M
        can_advance_j = j_count < N

        if can_advance_i and can_advance_j:
            d_advance_i = np.linalg.norm(inner_ring[i_next, :2] - outer_ring[j, :2])
            d_advance_j = np.linalg.norm(outer_ring[j_next, :2] - inner_ring[i, :2])
            advance_i = d_advance_i <= d_advance_j
        elif can_advance_i:
            advance_i = True
        else:
            advance_i = False

        if advance_i:
            tris.append([inner_ring[i], inner_ring[i_next], outer_ring[j]])
            i = i_next
            i_count += 1
        else:
            tris.append([inner_ring[i], outer_ring[j], outer_ring[j_next]])
            j = j_next
            j_count += 1

    if not tris:
        return None

    result = np.array(tris, dtype=np.float64).reshape(-1, 3)

    # Per-triangle winding correction: skirt la mat phang Z=min_z,
    # moi tam giac phai co normal +Z. Sua tung tam giac rieng le
    # (majority vote khong du khi inner CW va outer CCW tao mix winding)
    n_tris = len(result) // 3
    for t in range(n_tris):
        v0, v1, v2 = result[t * 3], result[t * 3 + 1], result[t * 3 + 2]
        fn = np.cross(v1 - v0, v2 - v0)
        if fn[2] < 0:
            result[t * 3 + 1], result[t * 3 + 2] = \
                result[t * 3 + 2].copy(), result[t * 3 + 1].copy()

    return result


def _triangulate_convex(convex_ring, face_down=False):
    """
    Tam giac hoa da giac loi bang fan triangulation.
    face_down=True: normal huong xuong (-Z), face_down=False: normal huong len (+Z).
    Convex hull thu tu CCW nhin tu tren.
    """
    n = len(convex_ring)
    if n < 3:
        return None

    tris = []
    for i in range(1, n - 1):
        if face_down:
            # CW nhin tu tren -> normal -Z
            tris.append([convex_ring[0], convex_ring[i + 1], convex_ring[i]])
        else:
            # CCW nhin tu tren -> normal +Z
            tris.append([convex_ring[0], convex_ring[i], convex_ring[i + 1]])

    return np.array(tris, dtype=np.float64).reshape(-1, 3)


def _make_side_walls(ring_top, ring_bottom):
    """
    Tao cac tam giac thanh ben (side walls) giua 2 ring co cung so dinh.
    ring_top: (N, 3) dinh tren (shell boundary, Z khac nhau)
    ring_bottom: (N, 3) dinh duoi (projected, cung Z)
    """
    n = len(ring_top)
    if n < 3 or len(ring_bottom) != n:
        return None

    tris = []
    for k in range(n):
        k_next = (k + 1) % n
        t0, t1 = ring_top[k], ring_top[k_next]
        b0, b1 = ring_bottom[k], ring_bottom[k_next]
        tris.append([t0, b0, t1])
        tris.append([t1, b0, b1])

    result = np.array(tris, dtype=np.float64).reshape(-1, 3)

    # Per-triangle fix: normal phai huong ra ngoai (xa tam)
    center = np.mean(ring_top, axis=0)
    n_tris = len(result) // 3
    for t in range(n_tris):
        v0, v1, v2 = result[t * 3], result[t * 3 + 1], result[t * 3 + 2]
        fn = np.cross(v1 - v0, v2 - v0)
        tc = (v0 + v1 + v2) / 3.0
        if np.dot(fn, tc - center) < 0:
            result[t * 3 + 1], result[t * 3 + 2] = \
                result[t * 3 + 2].copy(), result[t * 3 + 1].copy()

    return result


def _convex_hull_2d(points_2d):
    """
    Andrew's monotone chain algorithm cho 2D convex hull.
    Tra ve danh sach chi so dinh theo thu tu CCW.
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

    # Lower hull
    lower = []
    for i in indices:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], i) <= 0:
            lower.pop()
        lower.append(i)

    # Upper hull
    upper = []
    for i in reversed(indices):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], i) <= 0:
            upper.pop()
        upper.append(i)

    return lower[:-1] + upper[:-1]


def _make_convex_polygon(ring_3d):
    """
    Tinh convex hull cua da giac 3D (chieu xuong XY).
    Tra ve da giac loi 3D tai cung Z.
    """
    if len(ring_3d) < 3:
        return ring_3d.copy()

    z = float(ring_3d[0, 2])
    pts_2d = ring_3d[:, :2]

    hull_indices = _convex_hull_2d(pts_2d)
    if len(hull_indices) < 3:
        return ring_3d.copy()

    result = np.zeros((len(hull_indices), 3), dtype=np.float64)
    for i, hi in enumerate(hull_indices):
        result[i, :2] = pts_2d[hi]
        result[i, 2] = z

    return result


def _make_ring(center, axis, n_sides, radius):
    """
    Tao ring (vong dinh) regular n-gon tai vi tri center,
    vuong goc voi axis, ban kinh radius.
    """
    axis = axis / (np.linalg.norm(axis) + 1e-10)

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


def _eval_cubic_bezier(P0, P1, P2, P3, t):
    """Tinh gia tri duong cong Bezier bac 3 tai tham so t."""
    s = 1.0 - t
    return s * s * s * P0 + 3 * s * s * t * P1 + \
           3 * s * t * t * P2 + t * t * t * P3


def _resample_ring(ring, n_out):
    """
    Resample ring (K, 3) thanh ring moi co n_out dinh,
    bang noi suy tuyen tinh theo chieu dai cung.
    """
    K = len(ring)
    if K == n_out:
        return ring.copy()

    # Tinh chieu dai tich luy
    segs = np.linalg.norm(np.diff(ring, axis=0, append=ring[:1]), axis=1)
    total = np.sum(segs)
    if total < 1e-10:
        # Tat ca dinh trung nhau: chia deu theo chi so
        result = np.zeros((n_out, 3), dtype=np.float64)
        for i in range(n_out):
            result[i] = ring[int(round(i * K / n_out)) % K]
        return result

    cum = np.concatenate([[0.0], np.cumsum(segs)])

    result = np.zeros((n_out, 3), dtype=np.float64)
    for i in range(n_out):
        t_target = total * i / n_out
        # Tim doan chua t_target
        for j in range(K):
            if cum[j] <= t_target <= cum[j + 1]:
                seg_len = cum[j + 1] - cum[j]
                if seg_len < 1e-10:
                    result[i] = ring[j]
                else:
                    frac = (t_target - cum[j]) / seg_len
                    result[i] = ring[j] + frac * (ring[(j + 1) % K] - ring[j])
                break
        else:
            result[i] = ring[-1]

    return result


def _build_bezier_surface(convex_ring, circle_center, tip_radius,
                          effective_height, n_levels, n_target,
                          tan_overhang=1.0):
    """
    Tao be mat Bezier tu da giac loi (N dinh, tren) xuong hinh tron (n_target dinh, duoi).

    Thuat toan:
    1. Z cua tung ring duoc co dinh truoc bang Bezier cubic (tiep tuyen thang dung 2 dau).
    2. XY cua tung ring duoc tinh bang forward greedy: moi ring tien toi da
       |delta_z| * tan_overhang ve phia hinh tron, dam bao goc overhang.
    3. So dinh tang dan deu tu N_start -> n_target.
    """
    N_start = len(convex_ring)
    if N_start < 3:
        return None

    cx, cy, cz = circle_center
    top_z = float(convex_ring[0, 2])  # Z cua ring tren cung (=min_z)
    alpha = effective_height / 3.0
    beta  = effective_height / 3.0
    P1z = top_z - alpha
    P2z = cz + beta

    def bezier_z(t):
        """Z theo Bezier cubic: tiep tuyen thang dung tai t=0 va t=1."""
        s = 1.0 - t
        return s*s*s*top_z + 3*s*s*t*P1z + 3*s*t*t*P2z + t*t*t*cz

    # Goc bat dau cua circle: tinh mot lan duy nhat tu huong convex_ring[0]
    _dx0 = convex_ring[0, 0] - cx
    _dy0 = convex_ring[0, 1] - cy
    _d0 = np.sqrt(_dx0 * _dx0 + _dy0 * _dy0)
    global_start_angle = np.arctan2(_dy0, _dx0) if _d0 > 1e-10 else 0.0

    def make_circle_xy(count):
        """Tao circle XY count dinh: cach deu theo goc, but dau tu convex_ring[0]."""
        xy = np.zeros((count, 2), dtype=np.float64)
        for ci in range(count):
            a = global_start_angle + 2.0 * np.pi * ci / count
            xy[ci] = [cx + tip_radius * np.cos(a), cy + tip_radius * np.sin(a)]
        return xy

    # --- Buoc 1: Tinh Z cho tung ring ---
    z_levels = [bezier_z(level / n_levels) for level in range(n_levels + 1)]

    # --- Buoc 2: Tinh count cho tung ring ---
    level_counts = []
    for level in range(n_levels + 1):
        t = level / n_levels
        count = max(N_start, min(n_target, int(round(
            N_start + t * (n_target - N_start)))))
        level_counts.append(count)

    # --- Buoc 3: Tinh XY theo forward greedy (ràng buộc overhang) ---
    # Ring 0: chinh la convex ring (resampled thanh N_start)
    level_xy = []  # list of (count, xy_array (count, 2))

    xy0 = _resample_ring(convex_ring, N_start)[:, :2].copy()
    level_xy.append((N_start, xy0))

    for level in range(1, n_levels + 1):
        count = level_counts[level]
        dz = abs(z_levels[level] - z_levels[level - 1])
        max_step = dz * tan_overhang  # buoc XY toi da trong 1 ring

        prev_count, prev_xy = level_xy[-1]

        # Resample prev_xy sang count diem neu count thay doi
        if count != prev_count:
            tmp_3d = np.zeros((prev_count, 3), dtype=np.float64)
            tmp_3d[:, :2] = prev_xy
            tmp_3d[:, 2] = z_levels[level - 1]
            resampled = _resample_ring(tmp_3d, count)
            curr_xy = resampled[:, :2].copy()
        else:
            curr_xy = prev_xy.copy()

        # Target XY: circle deu count dinh, huong co dinh tu convex_ring[0]
        target_xy = make_circle_xy(count)

        # Tien toi target_xy, buoc toi da max_step
        new_xy = np.zeros((count, 2), dtype=np.float64)
        for i in range(count):
            direction = target_xy[i] - curr_xy[i]
            d = np.linalg.norm(direction)
            if d <= max_step or d < 1e-10:
                new_xy[i] = target_xy[i]
            else:
                new_xy[i] = curr_xy[i] + direction / d * max_step

        level_xy.append((count, new_xy))

    # --- Ghep XY va Z thanh rings 3D ---
    rings = []
    counts = []
    for level in range(n_levels + 1):
        count, xy = level_xy[level]
        ring = np.zeros((count, 3), dtype=np.float64)
        ring[:, :2] = xy
        ring[:, 2] = z_levels[level]
        rings.append(ring)
        counts.append(count)

    # Noi cac ring lien tiep
    all_tris = []
    for level in range(n_levels):
        r0, r1 = rings[level], rings[level + 1]
        M, N = counts[level], counts[level + 1]

        if M == N:
            for i in range(M):
                i_next = (i + 1) % M
                all_tris.append([r0[i],      r1[i],      r0[i_next]])
                all_tris.append([r0[i_next], r1[i],      r1[i_next]])
        else:
            # Zipper cho truong hop M != N (tang/giam 1 dinh)
            dists = np.linalg.norm(r0[:, :2] - r1[0, :2], axis=1)
            i, j = int(np.argmin(dists)), 0
            i_count = j_count = 0
            for _ in range(M + N):
                i_next = (i + 1) % M
                j_next = (j + 1) % N
                can_i = i_count < M
                can_j = j_count < N
                if can_i and can_j:
                    d_i = np.linalg.norm(r0[i_next, :2] - r1[j, :2])
                    d_j = np.linalg.norm(r1[j_next, :2] - r0[i, :2])
                    adv_i = d_i <= d_j
                elif can_i:
                    adv_i = True
                else:
                    adv_i = False
                if adv_i:
                    all_tris.append([r0[i], r0[i_next], r1[j]])
                    i = i_next; i_count += 1
                else:
                    all_tris.append([r0[i], r1[j], r1[j_next]])
                    j = j_next; j_count += 1

    if not all_tris:
        return None

    result = np.array(all_tris, dtype=np.float64).reshape(-1, 3)

    # Per-triangle outward winding fix (3D outward tu circle_center)
    circle_c = np.array([cx, cy, cz])
    n_tris = len(result) // 3
    for t in range(n_tris):
        v0, v1, v2 = result[t*3], result[t*3+1], result[t*3+2]
        fn = np.cross(v1 - v0, v2 - v0)
        tc = (v0 + v1 + v2) / 3.0
        outward = tc - circle_c  # huong ra ngoai tinh tu tam circle (dau tip)
        if np.dot(fn, outward) < 0:
            result[t*3+1], result[t*3+2] = result[t*3+2].copy(), result[t*3+1].copy()

    return result


def _polygon_area_3d(ring):
    """Tinh dien tich polygon 3D bang Shoelace (cross product sum)."""
    n = len(ring)
    if n < 3:
        return 0.0
    total = np.zeros(3)
    for i in range(n):
        total += np.cross(ring[i], ring[(i + 1) % n])
    return 0.5 * np.linalg.norm(total)


def _compute_soup_normals(all_verts):
    """Tinh face normals cho triangle soup."""
    if len(all_verts) == 0:
        return (np.zeros((0, 3), dtype=np.float32),
                np.zeros((0, 3), dtype=np.float32))

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
