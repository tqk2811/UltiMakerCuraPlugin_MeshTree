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


def _murray_radius(r1, r2):
    """
    Tính bán kính nhánh cha khi 2 nhánh con merge.

    Định luật Murray (Murray's Law, 1926):
    Trong hệ mạch máu/cây thực vật, bán kính nhánh cha tuân theo:
        r_parent³ = r_child1³ + r_child2³

    Áp dụng: khi 2 nhánh support merge, nhánh kết quả dày hơn
    nhưng không bằng tổng, tạo hình dáng tự nhiên (organic).

    Tham số:
        r1, r2 : float - bán kính hai nhánh con

    Trả về:
        float - bán kính nhánh cha
    """
    return (r1 ** 3 + r2 ** 3) ** (1.0 / 3.0)


def _murray_radius_n(radii):
    """
    Murray's Law cho N nhánh: r_parent³ = r1³ + r2³ + ... + rn³

    Tham số:
        radii : iterable of float - bán kính các nhánh con

    Trả về:
        float - bán kính nhánh cha
    """
    return sum(r ** 3 for r in radii) ** (1.0 / 3.0)


# ==============================================================================
# PHẦN 2: THUẬT TOÁN SPACE COLONIZATION BOTTOM-UP
#
# Quy trình chính:
# 1. Khởi tạo mỗi tip point thành 1 BranchTip
# 2. Lặp (sweep plane từ trên xuống, bước = step_size):
#    a. Tính hướng di chuyển cho mỗi nhánh:
#       - Hướng chính: xuống dưới (-Z)
#       - Tránh va chạm: đẩy ra xa mesh nếu quá gần
#    b. Di chuyển mỗi nhánh 1 bước
#    c. Kiểm tra merge: nhánh gần nhau → gom cluster (Union-Find) → gộp
#    d. Kiểm tra straight drop: nếu Z < threshold → rơi thẳng đứng
# 3. Kết thúc khi tất cả nhánh đạt Z=0
# ==============================================================================

def route_branches(tip_points, collision_field,
                   step_size=1.0, merge_distance=5.0, min_clearance=2.0,
                   cone_top_radius=0.5, cone_bottom_radius=0.2,
                   straight_drop_height=10.0,
                   tip_normals=None, radius_growth_rate=0.02,
                   max_branch_angle=40.0, cone_height=3.0,
                   departure_straight_down=True,
                   cancel_check=None):
    """
    Sinh nhánh cây support bằng Space Colonization bottom-up.

    Tham số:
        tip_points    : numpy array (K, 3) - điểm overhang (đầu nhánh)
        collision_field : CollisionField - trường va chạm (SDF + gradient)
        step_size     : float - bước di chuyển mỗi lần lặp (mm)
        merge_distance : float - khoảng cách để merge 2 nhánh (mm)
        min_clearance : float - khoảng cách an toàn tối thiểu đến mesh (mm)
        cone_top_radius : float - bán kính đáy lớn nón cụt (mm), tiếp xúc vỏ overhang
        cone_bottom_radius : float - bán kính đáy bé nón cụt (mm), chỗ mọc nhánh cây
        straight_drop_height : float - chiều cao rơi thẳng (mm)
                          Dưới mức này: nhánh rơi thẳng đứng, không merge
                          (điểm gộp dưới chiều cao này sẽ bị bỏ qua)
        tip_normals   : numpy array (K, 3) hoặc None - pháp tuyến bề mặt tại mỗi tip
                        (inward normal từ OverhangDetector). Dùng để tạo đoạn departure
                        vuông góc bề mặt, giúp dễ bẻ support sau khi in.
        radius_growth_rate : float - hệ số tăng bán kính mỗi bước (0-0.1)
                        Mỗi bước: radius *= (1 + growth_rate)
                        0 = chỉ tăng khi merge (Murray thuần túy)
                        0.02 = tăng 2%/bước → nhánh 50 bước mập gấp ~2.7x
                        0.05 = tăng 5%/bước → nhánh 50 bước mập gấp ~11x
        max_branch_angle : float - góc lệch tối đa so với trục Z (độ, 5-85)
                        Giới hạn hướng di chuyển nhánh trong hình nón quanh -Z.
                        40° → nhánh không được đi ngang quá 40° so với phương đứng.
        cone_height : float - chiều dài nón cụt (mm, 0.5-20)
                        Đoạn xuất phát đi theo outward normal trước khi routing.
                        Số bước = max(1, round(cone_height / step_size)).
                        Giúp tạo chân vuông góc dễ bẻ support sau khi in.

    Trả về:
        all_nodes : list of (position, radius) - tất cả nút trong skeleton
        all_edges : list of (parent_idx, child_idx) - các cạnh nối nút
    """

    # Trường hợp đặc biệt: không có tip nào
    if len(tip_points) == 0:
        return [], []

    # --- Tính hướng departure cho mỗi tip ---
    # Logic:
    # 1. Chiếu thẳng xuống (-Z) từ tip, kiểm tra có va chạm vật thể không
    # 2. Nếu KHÔNG va chạm:
    #    - departure_straight_down=True → đi thẳng xuống (-Z) cho gọn
    #    - departure_straight_down=False → đi vuông góc bề mặt overhang
    # 3. Nếu CÓ va chạm → luôn đi theo outward normal (vuông góc bề mặt)
    #    để nhánh tránh xuyên vào vật thể phía dưới
    departure_dirs = []
    for i in range(len(tip_points)):
        # Kiểm tra đường thẳng xuống có va chạm không
        # Lấy mẫu SDF tại các điểm dưới tip, cách nhau step_size
        tip_pos = tip_points[i]
        path_blocked = False
        check_z = tip_pos[2] - step_size
        while check_z > 0:
            check_point = np.array([tip_pos[0], tip_pos[1], check_z])
            dist = collision_field.get_distance(check_point)
            if dist < 0:  # Bên trong mesh → đường xuống bị chặn
                path_blocked = True
                break
            check_z -= step_size

        # Dùng outward normal khi: đường xuống bị chặn HOẶC user chọn vuông góc bề mặt
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
            # Đường xuống thông thoáng + user chọn thẳng xuống → đi thẳng xuống
            departure_dirs.append(np.array([0.0, 0.0, -1.0]))

    # Số bước departure: tính từ chiều dài nón cụt / bước di chuyển
    departure_steps = max(1, round(cone_height / step_size))

    # --- Khởi tạo skeleton ---
    # all_nodes: danh sách (position, radius) cho mỗi nút
    # all_edges: danh sách (idx_parent, idx_child) cho mỗi cạnh
    all_nodes = []  # [(numpy array (3,), float), ...]
    all_edges = []  # [(int, int), ...]

    # --- Khởi tạo các nhánh từ tip points ---
    # Mỗi nhánh bắt đầu bằng đoạn departure vuông góc bề mặt
    branches = []
    for i in range(len(tip_points)):
        # Tạo nút gốc tại điểm overhang (tip) — đáy lớn nón cụt
        node_pos = tip_points[i].copy()
        node_idx = len(all_nodes)
        all_nodes.append((node_pos.copy(), cone_top_radius))

        # Tạo đoạn departure hình nón cụt:
        # Bán kính giảm tuyến tính: cone_top_radius → cone_bottom_radius
        dep_dir = departure_dirs[i]
        prev_idx = node_idx
        current_pos = node_pos.copy()
        for step in range(departure_steps):
            current_pos = current_pos + dep_dir * step_size
            current_pos[2] = max(0.0, current_pos[2])
            new_idx = len(all_nodes)
            t = (step + 1) / departure_steps  # 0→1
            step_radius = cone_top_radius * (1.0 - t) + cone_bottom_radius * t
            all_nodes.append((current_pos.copy(), step_radius))
            all_edges.append((prev_idx, new_idx))
            prev_idx = new_idx

        # Tạo BranchTip bắt đầu từ đáy bé nón cụt
        branch = BranchTip(current_pos, cone_bottom_radius, prev_idx, tip_count=1)
        branch.prev_direction = dep_dir.copy()  # Khởi tạo smoothing từ hướng departure
        branches.append(branch)

    # --- Giới hạn góc nhánh so với trục Z ---
    # cos_angle_limit: thành phần Z tối thiểu (âm) để đảm bảo nhánh
    # không lệch quá max_branch_angle so với phương thẳng đứng
    cos_angle_limit = np.cos(np.radians(max_branch_angle))  # VD: cos(40°)≈0.766
    sin_angle_limit = np.sin(np.radians(max_branch_angle))  # VD: sin(40°)≈0.643



    # --- Danh sách chỉ số nhánh đang hoạt động ---
    active_indices = list(range(len(branches)))

    # --- Nhóm merge (multi-branch) ---
    # merge_groups[group_id] = set of branch indices trong nhóm
    merge_groups = {}
    next_group_id = 0

    # --- Vòng lặp chính: sweep plane từ trên xuống ---
    # Giới hạn số bước lặp để tránh vòng lặp vô hạn
    max_iterations = 10000
    iteration = 0

    while active_indices and iteration < max_iterations:
        iteration += 1

        # Kiểm tra huỷ mỗi vòng lặp
        if cancel_check is not None and cancel_check():
            return all_nodes, all_edges

        # Loại bỏ nhánh đã đạt Z=0 (hoàn thành)
        active_indices = [
            i for i in active_indices
            if branches[i].position[2] > 0.01  # Ngưỡng gần bàn in
        ]

        if not active_indices:
            break

        # --- Tính vị trí mới cho mỗi nhánh ---
        new_positions = {}    # idx → new_position
        new_node_indices = {} # idx → new_node_index

        for idx in active_indices:
            branch = branches[idx]
            pos = branch.position
            current_z = pos[2]

            # === Committed merge: đi thẳng đến merge_pos, KHÔNG can thiệp ===
            if branch.merge_target is not None:
                to_target = branch.merge_target - pos
                dist_to_target = np.linalg.norm(to_target)
                if dist_to_target > step_size:
                    # Còn xa target → đi 1 bước
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
                    # Đã đến target → đứng yên chờ partner (không tạo node)
                    branch.position = branch.merge_target.copy()
                    branch.position[2] = max(0.0, branch.position[2])
                continue

            # === Chế độ rơi thẳng (straight drop) ===
            # Khi nhánh đã xuống đủ thấp, rơi thẳng đứng xuống bàn in
            # Mục đích: tạo chân đế ổn định cho cây support
            if current_z <= straight_drop_height:
                # Rơi thẳng xuống: chỉ giảm Z, giữ nguyên XY
                new_z = max(0.0, current_z - step_size)
                new_pos = np.array([pos[0], pos[1], new_z])
                new_positions[idx] = new_pos
                continue

            # === Tính hướng di chuyển ===

            # Hướng chính: đi xuống (-Z)
            direction = np.array([0.0, 0.0, -1.0])

            # Tránh va chạm (collision avoidance)
            # Dùng CollisionField (SDF + gradient) để kiểm tra
            avoidance, dist_to_mesh = collision_field.get_avoidance_vector(
                pos, min_clearance
            )
            direction += avoidance

            # === Chuẩn hóa ===
            dir_length = np.linalg.norm(direction)
            if dir_length > 1e-6:
                direction /= dir_length

            # === Giới hạn góc so với trục Z (max_branch_angle) ===
            # Nếu hướng lệch quá góc cho phép → kẹp lại trong hình nón
            if direction[2] > -cos_angle_limit:
                xy_len = np.linalg.norm(direction[:2])
                if xy_len > 1e-6:
                    # Giữ hướng XY, scale về đúng góc giới hạn
                    direction[:2] = (direction[:2] / xy_len) * sin_angle_limit
                    direction[2] = -cos_angle_limit
                else:
                    direction[2] = -1.0
                dir_length = np.linalg.norm(direction)
                if dir_length > 1e-6:
                    direction /= dir_length

            # === Smoothing: trộn với hướng bước trước ===
            # Tránh thay đổi hướng đột ngột gây gấp khúc zíc-zắc
            old_weight = 0.3
            smoothed = (1.0 - old_weight) * direction + old_weight * branch.prev_direction
            sm_len = np.linalg.norm(smoothed)
            if sm_len > 1e-6:
                smoothed /= sm_len
            else:
                smoothed = direction

            # === Giới hạn góc lần nữa SAU smoothing ===
            # Smoothing có thể làm lệch góc → kẹp lại
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

            # Di chuyển 1 bước
            new_pos = pos + smoothed * step_size

            # Không cho đi dưới bàn in
            new_pos[2] = max(0.0, new_pos[2])

            # === Kiểm tra collision SAU khi di chuyển ===
            # SDF có dấu: âm = bên trong mesh, dương = bên ngoài
            # Nếu vị trí mới quá gần hoặc bên trong mesh → đẩy ra theo gradient
            post_dist = collision_field.get_distance(new_pos)
            if post_dist < min_clearance:
                # Lấy vector đẩy ra xa mesh
                push_vec, _ = collision_field.get_avoidance_vector(
                    new_pos, min_clearance
                )
                push_len = np.linalg.norm(push_vec)
                if push_len > 1e-6:
                    if post_dist < 0:
                        # BÊN TRONG mesh: đẩy ra mạnh hơn
                        # Cần đẩy ít nhất |post_dist| + min_clearance để ra ngoài
                        push_amount = min(abs(post_dist) + min_clearance, step_size * 3)
                    else:
                        # Bên ngoài nhưng gần: đẩy nhẹ
                        push_amount = min(min_clearance - post_dist + 0.2, step_size)
                    new_pos += (push_vec / push_len) * push_amount
                    new_pos[2] = max(0.0, new_pos[2])

            # === Giới hạn góc cuối cùng: kiểm tra hướng bước thực tế ===
            # Collision push có thể đẩy nhánh đi ngang quá góc cho phép → kẹp lại
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

            # Lưu hướng bước thực tế cho smoothing bước sau
            step_dir = new_pos - pos
            step_dir_len = np.linalg.norm(step_dir)
            if step_dir_len > 1e-6:
                branch.prev_direction = (step_dir / step_dir_len).copy()
            else:
                branch.prev_direction = smoothed.copy()
            branch.steps_taken += 1

            new_positions[idx] = new_pos

        # --- Kiểm tra và thực hiện merge ---
        merged_set = set()
        merge_pairs = []  # (survivor_idx, victim_idx) — dùng cho skeleton
        down = np.array([0.0, 0.0, -1.0])
        active_set = set(active_indices)

        if len(active_indices) > 1:
            positions_array = np.array([
                new_positions.get(i, branches[i].position) for i in active_indices
            ])

            # === Bước A: committed groups đã đến đích? ===
            for gid in list(merge_groups.keys()):
                members = merge_groups[gid]
                # Loại thành viên đã chết (Z=0, bị merge khác)
                alive = [i for i in members if i in active_set and i not in merged_set]

                if len(alive) < 2:
                    # Nhóm tan rã → huỷ cam kết
                    for i in members:
                        branches[i].merge_target = None
                        branches[i].merge_group_id = -1
                    del merge_groups[gid]
                    continue

                # Tất cả thành viên sống đã đến gần target?
                all_arrived = True
                for i in alive:
                    dist = np.linalg.norm(branches[i].position - branches[i].merge_target)
                    if dist >= step_size:
                        all_arrived = False
                        break

                if not all_arrived:
                    continue

                # === Merge thật: survivor = nhánh có tip_count cao nhất ===
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

                # Xoá trạng thái merge
                for i in alive:
                    branches[i].merge_target = None
                    branches[i].merge_group_id = -1
                del merge_groups[gid]

            # === Bước B: phát hiện merge mới (multi-branch clustering) ===
            tan_limit = sin_angle_limit / cos_angle_limit

            # Lọc nhánh đủ điều kiện merge
            eligible = []  # (ai, idx) — ai = vị trí trong positions_array
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
                # Union-Find để gom cluster
                uf_parent = {}
                for _, idx in eligible:
                    uf_parent[idx] = idx

                def uf_find(x):
                    while uf_parent[x] != x:
                        uf_parent[x] = uf_parent[uf_parent[x]]
                        x = uf_parent[x]
                    return x

                def uf_union(x, y):
                    rx, ry = uf_find(x), uf_find(y)
                    if rx != ry:
                        uf_parent[rx] = ry

                # Gom cặp gần nhau vào cùng cluster
                for a in range(len(eligible)):
                    ai_a, idx_a = eligible[a]
                    pos_a = positions_array[ai_a]

                    for b in range(a + 1, len(eligible)):
                        ai_b, idx_b = eligible[b]
                        pos_b = positions_array[ai_b]

                        dist = np.linalg.norm(pos_a[:2] - pos_b[:2])
                        if dist < merge_distance:
                            uf_union(idx_a, idx_b)

                # Trích xuất clusters (≥2 thành viên)
                clusters = {}
                for _, idx in eligible:
                    root = uf_find(idx)
                    clusters.setdefault(root, []).append(idx)

                # Xử lý từng cluster — chia nhỏ nếu cluster quá rộng
                # Dùng queue để xử lý cả sub-groups từ cluster bị chia
                pending_groups = []
                for root, members in clusters.items():
                    if len(members) >= 2:
                        pending_groups.append(list(members))

                for group in pending_groups:
                    remaining = list(group)
                    pruned = []  # Thành viên bị loại, sẽ thử tạo sub-group

                    while len(remaining) >= 2:
                        # Tính merge_target cho nhóm hiện tại
                        pp_map = {}
                        for i in remaining:
                            pp_map[i] = np.asarray(
                                new_positions.get(i, branches[i].position), dtype=np.float64
                            )

                        total_tips = sum(branches[i].tip_count for i in remaining)
                        m_xy = np.zeros(2)
                        for i in remaining:
                            m_xy += (branches[i].tip_count / total_tips) * pp_map[i][:2]

                        if tan_limit > 1e-6:
                            mz_vals = []
                            for i in remaining:
                                dxy = np.linalg.norm(pp_map[i][:2] - m_xy)
                                mz_vals.append(pp_map[i][2] - dxy / tan_limit)
                            m_z = max(0.0, min(mz_vals))
                        else:
                            m_z = 0.0

                        merge_target = np.array([m_xy[0], m_xy[1], m_z])

                        # Kiểm tra góc cho tất cả thành viên
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
                            # Commit nhóm merge
                            gid = next_group_id
                            next_group_id += 1
                            merge_groups[gid] = list(remaining)
                            for i in remaining:
                                branches[i].merge_target = merge_target.copy()
                                branches[i].merge_group_id = gid
                            break  # Nhóm đã commit xong

                        # Angle fail → loại thành viên xa nhất khỏi centroid, thử lại
                        max_dist = -1.0
                        farthest = remaining[0]
                        for i in remaining:
                            d = np.linalg.norm(pp_map[i][:2] - m_xy)
                            if d > max_dist:
                                max_dist = d
                                farthest = i
                        remaining.remove(farthest)
                        pruned.append(farthest)

                    # Thành viên bị loại → thêm vào queue để thử tạo sub-group
                    if len(pruned) >= 2:
                        pending_groups.append(pruned)

        # --- Tạo nút và cạnh mới trong skeleton ---
        for idx in active_indices:
            if idx in merged_set:
                continue

            branch = branches[idx]

            # Nhánh đang chờ ở target → KHÔNG tạo node mới
            if branch.merge_target is not None and idx not in new_positions:
                continue

            new_pos = new_positions.get(idx, branch.position)

            # Tăng bán kính mỗi bước
            if radius_growth_rate > 0:
                branch.radius *= (1.0 + radius_growth_rate)

            new_node_idx = len(all_nodes)
            all_nodes.append((new_pos.copy(), branch.radius))
            all_edges.append((branch.node_index, new_node_idx))

            # Nối tất cả victim vào nút merge của survivor
            for s, v in merge_pairs:
                if s == idx:
                    victim = branches[v]
                    all_edges.append((victim.node_index, new_node_idx))

            branch.position = new_pos.copy()
            branch.node_index = new_node_idx

        # --- Cập nhật active (loại bỏ merged) ---
        active_indices = [i for i in active_indices if i not in merged_set]

    # --- Kết thúc: đảm bảo tất cả nhánh chạm bàn in ---
    # Nếu có nhánh chưa đến Z=0 (do giới hạn iteration), nối thẳng xuống
    for idx in active_indices:
        branch = branches[idx]
        if branch.position[2] > 0.01:
            # Tạo nút tại Z=0 (chân cây)
            base_pos = np.array([branch.position[0], branch.position[1], 0.0])
            base_idx = len(all_nodes)
            all_nodes.append((base_pos, branch.radius))
            all_edges.append((branch.node_index, base_idx))

    return all_nodes, all_edges
