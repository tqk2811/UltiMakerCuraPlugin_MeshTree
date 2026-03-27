# ==============================================================================
# Module: Sinh nhánh cây (Branch Routing)
#
# Thuật toán: Space Colonization Algorithm (biến thể bottom-up)
#
# Thuật toán Space Colonization gốc (Runions et al., 2007):
# - Đặt "attraction points" trong không gian (mô phỏng tán cây)
# - Cây mọc lên TỪ DƯỚI, hướng về các attraction points
# - Dùng để sinh cây thực vật trong đồ họa máy tính
#
# Biến thể bottom-up cho Tree Support:
# - "Attraction points" = bàn in (Z=0) và trọng tâm các nhánh
# - Nhánh bắt đầu TỪ TRÊN (điểm overhang) rồi mọc XUỐNG
# - Các nhánh gần nhau hội tụ (merge) thành thân chính khi đi xuống
# - Áp dụng tránh va chạm (collision avoidance) tại mỗi bước
# - Kết thúc bằng đoạn thẳng đứng (straight drop) xuống bàn in
#
# Hệ tọa độ: Z-up (Z = chiều cao, bàn in tại Z=0)
#
# Đầu vào: tip points (K,3), CollisionField, các tham số
# Đầu ra: skeleton = danh sách (nodes, edges) cho TreeMeshBuilder
#
# Luồng thực thi: Chạy trong worker thread (bên trong Job.run())
# ==============================================================================

import numpy as np


# ==============================================================================
# PHẦN 1: CẤU TRÚC DỮ LIỆU NHÁNH CÂY
# ==============================================================================

class BranchTip:
    """
    Đại diện cho 1 nhánh đang hoạt động (active branch).

    Mỗi nhánh bắt đầu tại 1 điểm overhang (tip) và mọc xuống dưới.
    Khi hai nhánh merge, 1 nhánh bị hủy, nhánh còn lại kế thừa bán kính.

    Thuộc tính:
        position      : numpy array (3,) - vị trí hiện tại của đầu nhánh
        radius        : float - bán kính nhánh hiện tại (mm)
        node_index    : int - chỉ số nút cuối cùng trong skeleton
        tip_count     : int - số lượng tip gốc đã merge vào nhánh này
                        Dùng để tính bán kính theo định luật Murray
        prev_direction : numpy array (3,) - hướng di chuyển bước trước
                        Dùng để smoothing, tránh gấp khúc đột ngột
    """

    def __init__(self, position, radius, node_index, tip_count=1):
        self.position = position.copy()
        self.radius = radius
        self.node_index = node_index
        self.tip_count = tip_count
        self.prev_direction = np.array([0.0, 0.0, -1.0])  # Mặc định: đi xuống
        self.steps_taken = 0  # Đếm số bước routing (dùng để skip merge trong departure)
        self.merge_target = None        # (3,) - điểm hội tụ đã cam kết
        self.merge_group_id = -1        # ID nhóm merge (-1 = chưa có nhóm)


def _murray_radius_n(radii):
    """Murray's Law cho N nhánh: r_parent³ = r1³ + r2³ + ... + rn³"""
    return sum(r ** 3 for r in radii) ** (1.0 / 3.0)


# ==============================================================================
# PHẦN 2: THUẬT TOÁN SPACE COLONIZATION BOTTOM-UP
# ==============================================================================

def route_branches(tip_points, collision_field,
                   step_size=1.0, merge_distance=5.0, min_clearance=2.0,
                   cone_top_radius=0.5, cone_bottom_radius=0.2,
                   straight_drop_height=10.0,
                   tip_normals=None, radius_growth_rate=0.02,
                   max_branch_angle=40.0, cone_height=3.0,
                   departure_straight_down=True,
                   max_merge_count=5,
                   cancel_check=None):
    """
    Sinh nhánh cây support bằng Space Colonization bottom-up.

    Tham số:
        tip_points    : numpy array (K, 3) - điểm overhang (đầu nhánh)
        collision_field : CollisionField - trường va chạm (SDF + gradient)
        step_size     : float - bước di chuyển mỗi lần lặp (mm)
        merge_distance : float - khoảng cách để merge 2 nhánh (mm)
        min_clearance : float - khoảng cách an toàn tối thiểu đến mesh (mm)
        cone_top_radius : float - bán kính đáy lớn nón cụt (mm)
        cone_bottom_radius : float - bán kính đáy bé nón cụt (mm)
        straight_drop_height : float - chiều cao rơi thẳng (mm)
        max_merge_count : int - số nhánh tối đa được gộp cùng lúc
        tip_normals   : numpy array (K, 3) hoặc None - inward normals tại mỗi tip
        radius_growth_rate : float - hệ số tăng bán kính mỗi bước
        max_branch_angle : float - góc lệch tối đa so với trục Z (độ)
        cone_height : float - chiều dài đoạn departure (mm)
        departure_straight_down : bool - True = departure thẳng xuống

    Trả về:
        all_nodes : list of (position, radius) - tất cả nút trong skeleton
        all_edges : list of (parent_idx, child_idx) - các cạnh nối nút
    """

    if len(tip_points) == 0:
        return [], []

    # --- Tính hướng departure ---
    departure_dirs = []
    for i in range(len(tip_points)):
        tip_pos = tip_points[i]
        path_blocked = False
        check_z = tip_pos[2] - step_size
        while check_z > 0:
            check_point = np.array([tip_pos[0], tip_pos[1], check_z])
            dist = collision_field.get_distance(check_point)
            if dist < 0:
                path_blocked = True
                break
            check_z -= step_size

        use_normal = path_blocked or (not departure_straight_down)

        if use_normal and tip_normals is not None and i < len(tip_normals):
            outward = -tip_normals[i]
            n_len = np.linalg.norm(outward)
            if n_len > 1e-6:
                outward /= n_len
            else:
                outward = np.array([0.0, 0.0, -1.0])
            departure_dirs.append(outward)
        else:
            departure_dirs.append(np.array([0.0, 0.0, -1.0]))

    departure_steps = max(1, round(cone_height / step_size))

    # --- Khởi tạo skeleton ---
    all_nodes = []  # [(numpy array (3,), float), ...]
    all_edges = []  # [(int, int), ...]

    # --- Khởi tạo nhánh từ tip points ---
    branches = []
    for i in range(len(tip_points)):
        node_pos = tip_points[i].copy()
        node_idx = len(all_nodes)
        all_nodes.append((node_pos.copy(), cone_top_radius))

        dep_dir = departure_dirs[i]
        prev_idx = node_idx
        current_pos = node_pos.copy()
        for step in range(departure_steps):
            current_pos = current_pos + dep_dir * step_size
            current_pos[2] = max(0.0, current_pos[2])
            new_idx = len(all_nodes)
            t = (step + 1) / departure_steps
            step_radius = cone_top_radius * (1.0 - t) + cone_bottom_radius * t
            all_nodes.append((current_pos.copy(), step_radius))
            all_edges.append((prev_idx, new_idx))
            prev_idx = new_idx

        branch = BranchTip(current_pos, cone_bottom_radius, prev_idx, tip_count=1)
        branch.prev_direction = dep_dir.copy()
        branches.append(branch)

    cos_angle_limit = np.cos(np.radians(max_branch_angle))
    sin_angle_limit = np.sin(np.radians(max_branch_angle))

    active_indices = list(range(len(branches)))
    merge_groups = {}
    next_group_id = 0
    max_iterations = 10000
    iteration = 0

    while active_indices and iteration < max_iterations:
        iteration += 1

        if cancel_check is not None and cancel_check():
            return all_nodes, all_edges

        active_indices = [
            i for i in active_indices
            if branches[i].position[2] > 0.01
        ]

        if not active_indices:
            break

        new_positions = {}

        for idx in active_indices:
            branch = branches[idx]
            pos = branch.position
            current_z = pos[2]

            # Committed merge
            if branch.merge_target is not None:
                to_target = branch.merge_target - pos
                dist_to_target = np.linalg.norm(to_target)
                if dist_to_target > step_size:
                    d = to_target / dist_to_target
                    new_pos = pos + d * step_size
                    new_pos[2] = max(0.0, new_pos[2])
                    sd = new_pos - pos
                    sl = np.linalg.norm(sd)
                    if sl > 1e-6:
                        branch.prev_direction = (sd / sl).copy()
                    branch.steps_taken += 1
                    new_positions[idx] = new_pos
                else:
                    branch.position = branch.merge_target.copy()
                    branch.position[2] = max(0.0, branch.position[2])
                continue

            # Straight drop
            if current_z <= straight_drop_height:
                new_z = max(0.0, current_z - step_size)
                new_pos = np.array([pos[0], pos[1], new_z])
                new_positions[idx] = new_pos
                continue

            # Tính hướng
            direction = np.array([0.0, 0.0, -1.0])
            avoidance, _ = collision_field.get_avoidance_vector(pos, min_clearance)
            direction += avoidance

            dir_length = np.linalg.norm(direction)
            if dir_length > 1e-6:
                direction /= dir_length

            if direction[2] > -cos_angle_limit:
                xy_len = np.linalg.norm(direction[:2])
                if xy_len > 1e-6:
                    direction[:2] = (direction[:2] / xy_len) * sin_angle_limit
                    direction[2] = -cos_angle_limit
                else:
                    direction[2] = -1.0
                dir_length = np.linalg.norm(direction)
                if dir_length > 1e-6:
                    direction /= dir_length

            # Smoothing
            old_weight = 0.3
            smoothed = (1.0 - old_weight) * direction + old_weight * branch.prev_direction
            sm_len = np.linalg.norm(smoothed)
            if sm_len > 1e-6:
                smoothed /= sm_len
            else:
                smoothed = direction

            if smoothed[2] > -cos_angle_limit:
                xy_len = np.linalg.norm(smoothed[:2])
                if xy_len > 1e-6:
                    smoothed[:2] = (smoothed[:2] / xy_len) * sin_angle_limit
                    smoothed[2] = -cos_angle_limit
                else:
                    smoothed[2] = -1.0
                sm_len = np.linalg.norm(smoothed)
                if sm_len > 1e-6:
                    smoothed /= sm_len

            new_pos = pos + smoothed * step_size
            new_pos[2] = max(0.0, new_pos[2])

            post_dist = collision_field.get_distance(new_pos)
            if post_dist < min_clearance:
                push_vec, _ = collision_field.get_avoidance_vector(new_pos, min_clearance)
                push_len = np.linalg.norm(push_vec)
                if push_len > 1e-6:
                    if post_dist < 0:
                        push_amount = min(abs(post_dist) + min_clearance, step_size * 3)
                    else:
                        push_amount = min(min_clearance - post_dist + 0.2, step_size)
                    new_pos += (push_vec / push_len) * push_amount
                    new_pos[2] = max(0.0, new_pos[2])

            actual_step = new_pos - pos
            actual_step_len = np.linalg.norm(actual_step)
            if actual_step_len > 1e-6:
                actual_dir = actual_step / actual_step_len
                if actual_dir[2] > -cos_angle_limit:
                    xy_len = np.linalg.norm(actual_dir[:2])
                    if xy_len > 1e-6:
                        actual_dir[:2] = (actual_dir[:2] / xy_len) * sin_angle_limit
                        actual_dir[2] = -cos_angle_limit
                    else:
                        actual_dir[2] = -1.0
                    ad_len = np.linalg.norm(actual_dir)
                    if ad_len > 1e-6:
                        actual_dir /= ad_len
                    new_pos = pos + actual_dir * step_size
                    new_pos[2] = max(0.0, new_pos[2])

            step_dir = new_pos - pos
            step_dir_len = np.linalg.norm(step_dir)
            if step_dir_len > 1e-6:
                branch.prev_direction = (step_dir / step_dir_len).copy()
            else:
                branch.prev_direction = smoothed.copy()
            branch.steps_taken += 1

            new_positions[idx] = new_pos

        # --- Merge ---
        merged_set = set()
        merge_pairs = []
        down = np.array([0.0, 0.0, -1.0])
        active_set = set(active_indices)

        if len(active_indices) > 1:
            positions_array = np.array([
                new_positions.get(i, branches[i].position) for i in active_indices
            ])

            # Committed groups
            for gid in list(merge_groups.keys()):
                members = merge_groups[gid]
                alive = [i for i in members if i in active_set and i not in merged_set]

                if len(alive) < 2:
                    for i in members:
                        branches[i].merge_target = None
                        branches[i].merge_group_id = -1
                    del merge_groups[gid]
                    continue

                all_arrived = all(
                    np.linalg.norm(branches[i].position - branches[i].merge_target) < step_size
                    for i in alive
                )

                if not all_arrived:
                    continue

                alive_sorted = sorted(alive, key=lambda i: branches[i].tip_count, reverse=True)
                s_idx = alive_sorted[0]
                victims = alive_sorted[1:]

                for v_idx in victims:
                    merge_pairs.append((s_idx, v_idx))
                    merged_set.add(v_idx)

                s_br = branches[s_idx]
                merge_pos = s_br.merge_target.copy()
                new_positions[s_idx] = merge_pos

                edge_dir = merge_pos - np.asarray(all_nodes[s_br.node_index][0], dtype=np.float64)
                edge_len = np.linalg.norm(edge_dir)
                if edge_len > 1e-6:
                    s_br.prev_direction = edge_dir / edge_len
                s_br.radius = _murray_radius_n([branches[i].radius for i in alive])
                s_br.tip_count = sum(branches[i].tip_count for i in alive)

                for i in alive:
                    branches[i].merge_target = None
                    branches[i].merge_group_id = -1
                del merge_groups[gid]

            # Phát hiện merge mới
            tan_limit = sin_angle_limit / cos_angle_limit

            eligible = []
            for ai in range(len(active_indices)):
                idx = active_indices[ai]
                if idx in merged_set or branches[idx].merge_group_id >= 0:
                    continue
                pos = positions_array[ai]
                if pos[2] <= straight_drop_height:
                    continue
                if branches[idx].steps_taken < departure_steps:
                    continue
                eligible.append((ai, idx))

            if len(eligible) >= 2:
                eli_indices = [idx for _, idx in eligible]
                eli_pos = {
                    idx: np.asarray(
                        new_positions.get(idx, branches[idx].position), dtype=np.float64
                    )[:2]
                    for idx in eli_indices
                }

                pairs = []
                for a in range(len(eli_indices)):
                    for b in range(a + 1, len(eli_indices)):
                        ia, ib = eli_indices[a], eli_indices[b]
                        d = np.linalg.norm(eli_pos[ia] - eli_pos[ib])
                        if d < merge_distance:
                            pairs.append((d, ia, ib))
                pairs.sort(key=lambda x: x[0])

                group_of = {}
                groups = {}
                next_gid = 0

                for _, ia, ib in pairs:
                    ga = group_of.get(ia)
                    gb = group_of.get(ib)

                    if ga is None and gb is None:
                        gid = next_gid; next_gid += 1
                        groups[gid] = [ia, ib]
                        group_of[ia] = gid
                        group_of[ib] = gid
                    elif ga is None and gb is not None:
                        if len(groups[gb]) < max_merge_count:
                            groups[gb].append(ia)
                            group_of[ia] = gb
                    elif ga is not None and gb is None:
                        if len(groups[ga]) < max_merge_count:
                            groups[ga].append(ib)
                            group_of[ib] = ga

                pending_groups = [m for m in groups.values() if len(m) >= 2]

                for group in pending_groups:
                    remaining = list(group)
                    pruned = []

                    while len(remaining) >= 2:
                        pp_map = {
                            i: np.asarray(
                                new_positions.get(i, branches[i].position), dtype=np.float64
                            )
                            for i in remaining
                        }

                        total_tips = sum(branches[i].tip_count for i in remaining)
                        m_xy = np.zeros(2)
                        for i in remaining:
                            m_xy += (branches[i].tip_count / total_tips) * pp_map[i][:2]

                        if tan_limit > 1e-6:
                            mz_vals = [pp_map[i][2] - np.linalg.norm(pp_map[i][:2] - m_xy) / tan_limit
                                       for i in remaining]
                            m_z = max(0.0, min(mz_vals))
                        else:
                            m_z = 0.0

                        merge_target = np.array([m_xy[0], m_xy[1], m_z])

                        angle_ok = True
                        for i in remaining:
                            edge = merge_target - pp_map[i]
                            el = np.linalg.norm(edge)
                            if el > 1e-6:
                                cos_a = np.dot(edge / el, down)
                                if cos_a < cos_angle_limit:
                                    angle_ok = False
                                    break

                        if angle_ok:
                            gid = next_group_id
                            next_group_id += 1
                            merge_groups[gid] = list(remaining)
                            for i in remaining:
                                branches[i].merge_target = merge_target.copy()
                                branches[i].merge_group_id = gid
                            break

                        max_dist = -1.0
                        farthest = remaining[0]
                        for i in remaining:
                            d = np.linalg.norm(pp_map[i][:2] - m_xy)
                            if d > max_dist:
                                max_dist = d
                                farthest = i
                        remaining.remove(farthest)
                        pruned.append(farthest)

                    if len(pruned) >= 2:
                        pending_groups.append(pruned)

        # --- Tạo nút và cạnh mới ---
        for idx in active_indices:
            if idx in merged_set:
                continue

            branch = branches[idx]

            if branch.merge_target is not None and idx not in new_positions:
                continue

            new_pos = new_positions.get(idx, branch.position)

            if radius_growth_rate > 0:
                branch.radius *= (1.0 + radius_growth_rate)

            new_node_idx = len(all_nodes)
            all_nodes.append((new_pos.copy(), branch.radius))
            all_edges.append((branch.node_index, new_node_idx))

            for s, v in merge_pairs:
                if s == idx:
                    victim = branches[v]
                    all_edges.append((victim.node_index, new_node_idx))

            branch.position = new_pos.copy()
            branch.node_index = new_node_idx

        active_indices = [i for i in active_indices if i not in merged_set]

    # --- Đảm bảo tất cả nhánh chạm bàn in ---
    for idx in active_indices:
        branch = branches[idx]
        if branch.position[2] > 0.01:
            base_pos = np.array([branch.position[0], branch.position[1], 0.0])
            base_idx = len(all_nodes)
            all_nodes.append((base_pos, branch.radius))
            all_edges.append((branch.node_index, base_idx))

    return all_nodes, all_edges
