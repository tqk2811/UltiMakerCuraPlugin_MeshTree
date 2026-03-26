# ==============================================================================
# Module: Mô phỏng nhánh cây (Branch Router)
#
# Mô phỏng nhánh support từ Point A đi xuống sàn Z=0 (hoặc đáp lên vật thể).
#
# Thuật toán:
#   - Step-by-step simulation từ Z cao → Z=0
#   - 3 lực: trọng lực, lực hấp dẫn gộp (2D gravity center), chống va chạm
#   - Quán tính (momentum) làm mượt đường đi
#   - Gộp nhánh: closest pair priority, anti-3-merge
#   - Diện tích tăng dần: area = area_head × (1 + coeff × |Δz|)
#   - Landing: nhánh chạm vật thể → tạo landing pad
#   - Da Vinci: tại merge → parent_area = Σ(child_areas)
#
# Đầu vào: list[PointA], CollisionField, settings
# Đầu ra: BranchGraph — đồ thị cây (paths + radii + merge info)
#
# Luồng thực thi: worker thread (trong Job.run())
# ==============================================================================

import numpy as np
from UM.Logger import Logger


class BranchNode:
    """Nút trong đồ thị nhánh cây."""
    __slots__ = ['position', 'radius', 'area', 'parent', 'children',
                 'is_merge_point', 'is_landing', 'landing_normal']

    def __init__(self, position, radius, area):
        self.position = position        # (3,)
        self.radius = radius            # float
        self.area = area                # float, cross-section area
        self.parent = None              # BranchNode hoặc None
        self.children = []              # list[BranchNode]
        self.is_merge_point = False
        self.is_landing = False
        self.landing_normal = None      # (3,) normal bề mặt landing


class BranchPath:
    """Đường đi của 1 nhánh (chuỗi nodes)."""
    __slots__ = ['nodes', 'branch_id', 'merged_into', 'landed']

    def __init__(self, branch_id):
        self.nodes = []               # list[BranchNode]
        self.branch_id = branch_id
        self.merged_into = None       # branch_id đích merge (hoặc None)
        self.landed = False           # True nếu đáp lên vật thể


class BranchGraph:
    """Kết quả toàn bộ branch routing."""

    def __init__(self):
        self.paths = []               # list[BranchPath]
        self.merge_events = []        # list[(z, child_ids, parent_id)]
        self.landing_events = []      # list[(branch_id, position, normal)]


def route_branches(points_a, collision_field, settings, cancel_check=None):
    """
    Mô phỏng nhánh cây từ Point A đi xuống sàn.

    Tham số:
        points_a        : list[PointA] từ TipInterfaceBuilder
        collision_field : CollisionField từ CollisionAvoider
        settings        : dict chứa các tham số
        cancel_check    : callable → True nếu cần huỷ

    Settings cần:
        branch_step_size    : float (mm)
        gravity_weight      : float
        merge_weight        : float
        merge_distance_max  : float (mm)
        area_growth_coeff   : float
        momentum_alpha      : float (0-1)
        collision_weight    : float
        min_clearance       : float (mm)
        tip_radius          : float (mm)

    Trả về:
        BranchGraph
    """
    if not points_a:
        return BranchGraph()

    step_size = float(settings.get("branch_step_size", 0.5))
    gravity_w = float(settings.get("gravity_weight", 1.0))
    merge_w = float(settings.get("merge_weight", 0.3))
    merge_dist_max = float(settings.get("merge_distance_max", 30.0))
    area_growth = float(settings.get("area_growth_coeff", 0.05))
    momentum = float(settings.get("momentum_alpha", 0.3))
    collision_w = float(settings.get("collision_weight", 1.0))
    min_clearance = float(settings.get("min_clearance", 2.0))
    tip_radius = float(settings.get("tip_radius", 0.4))
    # Murray's law exponent: n=2 = Da Vinci (A1+A2), n=2.5 = cây thực vật (nhánh cha nhỏ hơn)
    murray_exp = float(settings.get("murray_exponent", 2.5))

    # Hệ số merge distance: √area × coeff = 10mm tại tip
    tip_area = 2.0 * np.sqrt(2.0) * tip_radius ** 2
    merge_coeff = 10.0 / (np.sqrt(tip_area) + 1e-10)

    graph = BranchGraph()

    # --- Khởi tạo nhánh từ mỗi Point A ---
    N = len(points_a)
    positions = np.zeros((N, 3), dtype=np.float64)
    directions = np.zeros((N, 3), dtype=np.float64)
    areas = np.zeros(N, dtype=np.float64)
    radii = np.zeros(N, dtype=np.float64)
    head_areas = np.zeros(N, dtype=np.float64)
    head_z = np.zeros(N, dtype=np.float64)
    active = np.ones(N, dtype=bool)

    paths = []
    for i, pt in enumerate(points_a):
        positions[i] = pt.position
        directions[i] = pt.direction
        areas[i] = pt.area
        radii[i] = pt.radius
        head_areas[i] = pt.area
        head_z[i] = pt.position[2]

        path = BranchPath(branch_id=i)
        node = BranchNode(pt.position.copy(), pt.radius, pt.area)
        path.nodes.append(node)
        paths.append(path)

    graph.paths = paths

    # --- Simulation loop ---
    max_steps = int(np.max(positions[:, 2]) / step_size) + 100
    stall_counter = np.zeros(N, dtype=np.int32)
    max_stall = 50  # Timeout nếu Z không giảm

    for step_idx in range(max_steps):
        if cancel_check and cancel_check():
            raise InterruptedError()

        n_active = int(np.sum(active))
        if n_active == 0:
            break

        active_idx = np.where(active)[0]
        pos_active = positions[active_idx]

        # --- 1. Trọng lực ---
        gravity = np.zeros_like(pos_active)
        gravity[:, 2] = -gravity_w

        # --- 2. Lực hấp dẫn gộp (2D gravity center trong XY) ---
        merge_force = _compute_merge_forces(
            active_idx, positions, areas, merge_coeff, merge_dist_max, merge_w
        )

        # --- 3. Chống va chạm ---
        avoidance, sdf_dists = collision_field.get_avoidance_vectors_batch(
            pos_active, min_clearance
        )
        avoidance *= collision_w

        # --- 4. Tổng hợp lực + quán tính ---
        net_force = gravity + merge_force + avoidance

        # Normalize
        net_len = np.linalg.norm(net_force, axis=1, keepdims=True)
        net_len = np.maximum(net_len, 1e-10)
        new_dirs = net_force / net_len

        # Quán tính: blend với hướng trước
        old_dirs = directions[active_idx]
        blended = momentum * new_dirs + (1.0 - momentum) * old_dirs
        bl_len = np.linalg.norm(blended, axis=1, keepdims=True)
        bl_len = np.maximum(bl_len, 1e-10)
        blended /= bl_len

        # Đảm bảo Z giảm tối thiểu: clamp Z rồi renorm chỉ phần XY
        # Không renorm toàn bộ vector (sẽ làm Z drift > -0.5)
        z_min = -0.707  # sin(45°) = 0.707 → nhánh nghiêng tối thiểu 45° so với nằm ngang
        z_clamped = np.minimum(blended[:, 2], z_min)
        xy = blended[:, :2]
        xy_len = np.linalg.norm(xy, axis=1, keepdims=True)
        # Tính scale XY sao cho vector tổng thể là đơn vị: xy_scale² + z² = 1
        xy_scale = np.sqrt(np.maximum(1.0 - z_clamped ** 2, 0.0))
        safe_xy = np.where(xy_len > 1e-10,
                           xy / xy_len * xy_scale[:, np.newaxis],
                           np.zeros_like(xy))
        blended = np.concatenate([safe_xy, z_clamped[:, np.newaxis]], axis=1)

        # --- 5. Cập nhật vị trí ---
        new_pos = pos_active + blended * step_size

        # --- 6. Kiểm tra landing / base ---
        for ii, ai in enumerate(active_idx):
            old_z = positions[ai, 2]
            nz = new_pos[ii, 2]

            # Đạt sàn Z=0
            if nz <= 0:
                new_pos[ii, 2] = 0.0
                positions[ai] = new_pos[ii]
                directions[ai] = blended[ii]
                node = BranchNode(new_pos[ii].copy(), radii[ai], areas[ai])
                paths[ai].nodes.append(node)
                active[ai] = False
                continue

            # Kiểm tra SDF: nếu đi vào bên trong mesh → landing
            if sdf_dists[ii] < 0:
                # Binary search tìm bề mặt
                p_safe = pos_active[ii]
                p_inside = new_pos[ii]
                for _ in range(10):
                    mid = (p_safe + p_inside) / 2.0
                    d = collision_field.get_distance(mid.astype(np.float64))
                    if d < 0:
                        p_inside = mid
                    else:
                        p_safe = mid

                landing_pos = (p_safe + p_inside) / 2.0

                # Landing normal = SDF gradient
                _, landing_d = collision_field.get_avoidance_vectors_batch(
                    landing_pos.reshape(1, 3), min_clearance
                )
                av_vec, _ = collision_field.get_avoidance_vectors_batch(
                    landing_pos.reshape(1, 3), 999.0
                )
                landing_normal = av_vec[0]
                ln_len = np.linalg.norm(landing_normal)
                if ln_len > 1e-6:
                    landing_normal /= ln_len
                else:
                    landing_normal = np.array([0.0, 0.0, 1.0])

                node = BranchNode(landing_pos.copy(), radii[ai], areas[ai])
                node.is_landing = True
                node.landing_normal = landing_normal
                paths[ai].nodes.append(node)
                paths[ai].landed = True
                graph.landing_events.append(
                    (ai, landing_pos.copy(), landing_normal.copy())
                )
                active[ai] = False
                continue

            # Cập nhật
            positions[ai] = new_pos[ii]
            directions[ai] = blended[ii]

            # Tăng diện tích: area = head_area × (1 + coeff × |Δz|)
            dz = abs(head_z[ai] - new_pos[ii, 2])
            areas[ai] = head_areas[ai] * (1.0 + area_growth * dz)
            radii[ai] = _radius_from_area_oct(areas[ai])

            node = BranchNode(new_pos[ii].copy(), radii[ai], areas[ai])
            paths[ai].nodes.append(node)

            # Stall detection
            if abs(old_z - nz) < step_size * 0.01:
                stall_counter[ai] += 1
                if stall_counter[ai] > max_stall:
                    active[ai] = False
            else:
                stall_counter[ai] = 0

        # --- 7. Gộp nhánh (closest pair priority) ---
        _process_merges(
            active, positions, areas, radii, directions,
            head_areas, head_z, paths, graph,
            merge_coeff, merge_dist_max, step_size, murray_exp
        )

    Logger.log("i", "BranchRouter: %d nhanh, %d merge events, %d landings",
               len(graph.paths), len(graph.merge_events), len(graph.landing_events))

    return graph


def _compute_merge_forces(active_idx, positions, areas, merge_coeff,
                          merge_dist_max, merge_weight):
    """
    Tính lực hấp dẫn 2D (XY) cho mỗi nhánh active.
    Dùng N-body gravity: F = direction × mass / d² (trong XY).

    Trả về: numpy array (len(active_idx), 3)
    """
    N = len(active_idx)
    forces = np.zeros((N, 3), dtype=np.float64)
    if N <= 1:
        return forces

    pos = positions[active_idx]
    area = areas[active_idx]

    for i in range(N):
        # Merge distance cho nhánh i
        my_merge_dist = min(np.sqrt(area[i]) * merge_coeff, merge_dist_max)

        fx = fy = 0.0
        for j in range(N):
            if i == j:
                continue
            dx = pos[j, 0] - pos[i, 0]
            dy = pos[j, 1] - pos[i, 1]
            d2 = dx * dx + dy * dy
            d = np.sqrt(d2) if d2 > 0 else 1e-6

            if d > my_merge_dist:
                continue

            # Lực hấp dẫn: F = mass_j / d² (inverse-square)
            mass_j = area[j]
            strength = mass_j / (d2 + 1e-6)
            fx += (dx / d) * strength
            fy += (dy / d) * strength

        forces[i, 0] = fx * merge_weight
        forces[i, 1] = fy * merge_weight

    return forces


def _process_merges(active, positions, areas, radii, directions,
                    head_areas, head_z, paths, graph,
                    merge_coeff, merge_dist_max, step_size, murray_exp=2.5):
    """
    Gộp nhánh: closest pair priority, anti-3-merge.
    Mỗi bước Z chỉ gộp 1 cặp gần nhất cho mỗi nhánh.
    """
    active_idx = np.where(active)[0]
    N = len(active_idx)
    if N < 2:
        return

    # Tính khoảng cách tất cả cặp trong XY
    pos_xy = positions[active_idx, :2]
    merged_this_step = set()
    pairs = []

    for i in range(N):
        ai = active_idx[i]
        my_merge_dist = min(np.sqrt(areas[ai]) * merge_coeff, merge_dist_max)

        for j in range(i + 1, N):
            aj = active_idx[j]
            d = np.linalg.norm(pos_xy[i] - pos_xy[j])

            # Khoảng cách gộp = min(merge_dist_i, merge_dist_j)
            other_merge_dist = min(np.sqrt(areas[aj]) * merge_coeff, merge_dist_max)
            threshold = min(my_merge_dist, other_merge_dist)

            # Threshold thực tế cho merge: bán kính tổng + step_size × 6
            actual_threshold = radii[ai] + radii[aj] + step_size * 6
            if d < actual_threshold:
                pairs.append((d, ai, aj))

    if not pairs:
        return

    # Sắp xếp theo khoảng cách tăng dần
    pairs.sort(key=lambda x: x[0])

    for d, ai, aj in pairs:
        if ai in merged_this_step or aj in merged_this_step:
            continue
        if not active[ai] or not active[aj]:
            continue

        # --- Gộp aj vào ai (ai là nhánh nhận) ---
        # Nhánh nhận = nhánh có area lớn hơn
        if areas[aj] > areas[ai]:
            ai, aj = aj, ai

        # Murray's law: r_parent = (r1^n + r2^n)^(1/n)
        # n=2 = Da Vinci (diện tích bảo toàn), n=2.5 = cây thực vật (nhánh cha nhỏ hơn)
        new_radius = (radii[ai] ** murray_exp + radii[aj] ** murray_exp) ** (1.0 / murray_exp)
        new_area = _area_from_radius_oct(new_radius)

        # Vị trí mới = trung bình trọng số XY, Z lấy thấp hơn (nhánh không đi ngược lên)
        w_ai = areas[ai] / new_area
        w_aj = areas[aj] / new_area
        new_pos = positions[ai] * w_ai + positions[aj] * w_aj
        new_pos[2] = min(positions[ai, 2], positions[aj, 2])  # Z không tăng lên

        new_dir = directions[ai] * w_ai + directions[aj] * w_aj
        new_dir[2] = min(new_dir[2], -0.1)  # luôn đi xuống
        d_len = np.linalg.norm(new_dir)
        if d_len > 1e-10:
            new_dir /= d_len

        # Cập nhật nhánh ai
        positions[ai] = new_pos
        areas[ai] = new_area
        radii[ai] = new_radius
        directions[ai] = new_dir
        head_areas[ai] = new_area
        head_z[ai] = new_pos[2]

        # Đánh dấu merge node
        merge_node = BranchNode(new_pos.copy(), new_radius, new_area)
        merge_node.is_merge_point = True
        paths[ai].nodes.append(merge_node)

        # Vô hiệu hóa nhánh aj
        active[aj] = False
        paths[aj].merged_into = ai

        graph.merge_events.append((new_pos[2], [aj, ai], ai))
        merged_this_step.add(ai)
        merged_this_step.add(aj)


def _radius_from_area_oct(area):
    """Bán kính octagon từ diện tích: A = 2√2 × r² → r = √(A / 2√2)."""
    return np.sqrt(max(area, 1e-10) / (2.0 * np.sqrt(2.0)))


def _area_from_radius_oct(r):
    """Diện tích octagon từ bán kính: A = 2√2 × r²."""
    return 2.0 * np.sqrt(2.0) * r * r
