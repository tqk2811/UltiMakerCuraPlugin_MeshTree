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
        self.steps_taken = 0  # Đếm số bước routing (dùng để ramp up convergence)
        self.merge_target = None        # (3,) array - điểm hội tụ đã cam kết
        self.merge_partner_idx = -1     # Chỉ số nhánh đối tác merge


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


# ==============================================================================
# PHẦN 2: THUẬT TOÁN SPACE COLONIZATION BOTTOM-UP
#
# Quy trình chính:
# 1. Khởi tạo mỗi tip point thành 1 BranchTip
# 2. Lặp (sweep plane từ trên xuống, bước = step_size):
#    a. Tính hướng di chuyển cho mỗi nhánh:
#       - Hướng chính: xuống dưới (-Z)
#       - Lực hút: về phía trọng tâm các nhánh (hội tụ)
#       - Tránh va chạm: đẩy ra xa mesh nếu quá gần
#    b. Di chuyển mỗi nhánh 1 bước
#    c. Kiểm tra merge: nếu 2 nhánh gần nhau → gộp thành 1
#    d. Kiểm tra straight drop: nếu Z < threshold → rơi thẳng đứng
# 3. Kết thúc khi tất cả nhánh đạt Z=0
# ==============================================================================

def route_branches(tip_points, collision_field,
                   step_size=1.0, merge_distance=5.0, min_clearance=2.0,
                   cone_top_radius=0.5, cone_bottom_radius=0.2,
                   min_merge_height=20.0,
                   straight_drop_height=10.0, convergence_strength=0.3,
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
        min_merge_height : float - chiều cao Z tối thiểu để merge (mm)
                          Dưới mức này, nhánh chỉ rơi thẳng, không merge
        straight_drop_height : float - chiều cao Z bắt đầu rơi thẳng đứng (mm)
        convergence_strength : float - lực hút về trọng tâm (0-1)
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

    # --- Chiều cao Z ban đầu lớn nhất (dùng cho adaptive merge) ---
    initial_max_z = float(np.max(tip_points[:, 2])) if len(tip_points) > 0 else 100.0

    # --- Danh sách chỉ số nhánh đang hoạt động ---
    active_indices = list(range(len(branches)))

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

        # --- Tính trọng tâm XY của tất cả nhánh hoạt động ---
        # Dùng làm "attraction point" cho lực hội tụ
        active_positions = np.array([branches[i].position for i in active_indices])
        centroid_xy = np.mean(active_positions[:, :2], axis=0)  # Trọng tâm XY

        # --- Tìm nearest neighbor cho mỗi nhánh (dùng cho convergence) ---
        # Tính 1 lần cho toàn bộ active, dùng cho tất cả nhánh trong bước này
        nearest_neighbor = {}  # idx → (neighbor_idx, distance)
        if len(active_indices) > 1:
            active_pos_array = np.array([branches[i].position for i in active_indices])
            for ai in range(len(active_indices)):
                idx_i = active_indices[ai]
                pos_i = active_pos_array[ai]
                best_dist = float('inf')
                best_idx = -1
                for aj in range(len(active_indices)):
                    if ai == aj:
                        continue
                    d = np.linalg.norm(pos_i[:2] - active_pos_array[aj][:2])
                    if d < best_dist:
                        best_dist = d
                        best_idx = active_indices[aj]
                if best_idx >= 0:
                    nearest_neighbor[idx_i] = (best_idx, best_dist)

        # --- Tính vị trí mới cho mỗi nhánh ---
        new_positions = {}    # idx → new_position
        new_node_indices = {} # idx → new_node_index

        for idx in active_indices:
            branch = branches[idx]
            pos = branch.position
            current_z = pos[2]

            # === Committed merge: đi thẳng đến điểm hội tụ ===
            # Khi đã cam kết merge, giữ nguyên hướng, không convergence/smoothing
            if branch.merge_target is not None:
                to_target = branch.merge_target - pos
                dist_to_target = np.linalg.norm(to_target)
                if dist_to_target > step_size:
                    direction = to_target / dist_to_target
                    new_pos = pos + direction * step_size
                else:
                    new_pos = branch.merge_target.copy()
                new_pos[2] = max(0.0, new_pos[2])
                step_dir = new_pos - pos
                step_len = np.linalg.norm(step_dir)
                if step_len > 1e-6:
                    branch.prev_direction = (step_dir / step_len).copy()
                branch.steps_taken += 1
                if radius_growth_rate > 0:
                    branch.radius *= (1.0 + radius_growth_rate)
                new_positions[idx] = new_pos
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

            # === Tính hướng di chuyển (Space Colonization) ===

            # Thành phần 1: Hướng chính - đi xuống (-Z)
            direction = np.array([0.0, 0.0, -1.0])

            # Thành phần 2: Lực hội tụ (convergence)
            # Ramp up: trong 15 bước đầu, convergence tăng dần từ 0 → full
            # để tránh bẻ góc đột ngột ngay sau đoạn departure vuông góc
            ramp_steps = 15
            ramp_factor = min(1.0, branch.steps_taken / ramp_steps)
            effective_convergence = convergence_strength * ramp_factor

            # 2a: Lực kéo về trọng tâm chung (global centroid)
            to_center = np.zeros(3)
            to_center[0] = centroid_xy[0] - pos[0]
            to_center[1] = centroid_xy[1] - pos[1]

            center_dist_xy = np.linalg.norm(to_center[:2])
            if center_dist_xy > 0.1:
                to_center[:2] /= center_dist_xy
                pull = min(effective_convergence * 0.5, 0.03 * center_dist_xy)
                direction[:2] += to_center[:2] * pull

            # 2b: Lực kéo về nhánh gần nhất (nearest-neighbor convergence)
            # Mạnh hơn centroid → 2 nhánh gần nhau sẽ nhanh chóng hội tụ
            if idx in nearest_neighbor:
                nn_idx, nn_dist = nearest_neighbor[idx]
                nn_pos = branches[nn_idx].position
                to_nn = np.zeros(3)
                to_nn[0] = nn_pos[0] - pos[0]
                to_nn[1] = nn_pos[1] - pos[1]
                nn_dist_xy = np.linalg.norm(to_nn[:2])
                if nn_dist_xy > 0.1:
                    to_nn[:2] /= nn_dist_xy
                    # Lực kéo NN mạnh hơn khi gần, yếu khi xa
                    nn_pull = min(effective_convergence * 0.7, 0.04 * nn_dist_xy)
                    direction[:2] += to_nn[:2] * nn_pull

            # Thành phần 3: Tránh va chạm (collision avoidance)
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
            # Giai đoạn ramp: smoothing rất mạnh (70% cũ) để chuyển tiếp mềm
            # từ departure → routing. Sau đó: 30% cũ, 70% mới.
            if branch.steps_taken < ramp_steps:
                old_weight = 0.7
            else:
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
        # Committed merge: nhánh đi thẳng đến điểm hội tụ qua nhiều bước.
        # Không cho bẻ góc thêm khi đang bẻ góc.
        merged_set = set()     # Tập nhánh bị merge (hủy)
        merge_pairs = []       # Danh sách cặp (nhánh sống, nhánh hủy)

        if len(active_indices) > 1:
            positions_array = np.array([
                new_positions.get(i, branches[i].position) for i in active_indices
            ])

            # --- Bước A: Kiểm tra committed merge đã đến đích ---
            # Hai nhánh committed cùng target → khi cả hai gần target → merge thật
            committed_pairs_done = []
            for ai in range(len(active_indices)):
                idx_i = active_indices[ai]
                br_i = branches[idx_i]
                if br_i.merge_partner_idx < 0 or idx_i in merged_set:
                    continue
                partner_idx = br_i.merge_partner_idx
                # Chỉ xử lý mỗi cặp 1 lần (idx nhỏ hơn xử lý)
                if idx_i > partner_idx:
                    continue
                if partner_idx in merged_set:
                    continue
                br_p = branches[partner_idx]
                pos_i = new_positions.get(idx_i, br_i.position)
                pos_p = new_positions.get(partner_idx, br_p.position)
                dist_between = np.linalg.norm(pos_i - pos_p)
                if dist_between < step_size * 1.5:
                    # Đã đến gần nhau → merge thật
                    if br_i.tip_count >= br_p.tip_count:
                        s_idx, v_idx = idx_i, partner_idx
                    else:
                        s_idx, v_idx = partner_idx, idx_i
                    merge_pairs.append((s_idx, v_idx))
                    merged_set.add(v_idx)
                    # Tính merge_pos = trung điểm
                    merge_pos = (pos_i + pos_p) / 2.0
                    new_positions[s_idx] = merge_pos
                    s_br = branches[s_idx]
                    v_br = branches[v_idx]
                    edge_dir = merge_pos - np.asarray(all_nodes[s_br.node_index][0], dtype=np.float64)
                    edge_len = np.linalg.norm(edge_dir)
                    if edge_len > 1e-6:
                        s_br.prev_direction = edge_dir / edge_len
                    s_br.radius = _murray_radius(s_br.radius, v_br.radius)
                    s_br.tip_count += v_br.tip_count
                    # Xoá cam kết
                    s_br.merge_target = None
                    s_br.merge_partner_idx = -1
                    v_br.merge_target = None
                    v_br.merge_partner_idx = -1

            # --- Bước B: Phát hiện merge mới → commit (không nhảy ngay) ---
            for ai in range(len(active_indices)):
                idx_i = active_indices[ai]
                if idx_i in merged_set:
                    continue
                # Bỏ qua nhánh đã committed
                if branches[idx_i].merge_partner_idx >= 0:
                    continue

                pos_i = positions_array[ai]

                if pos_i[2] <= min_merge_height:
                    continue
                if branches[idx_i].steps_taken < departure_steps:
                    continue

                height_ratio = pos_i[2] / initial_max_z if initial_max_z > 0 else 0
                height_ratio = min(1.0, max(0.0, height_ratio))
                effective_merge_dist = merge_distance * (1.0 + 2.0 * (1.0 - height_ratio))

                for aj in range(ai + 1, len(active_indices)):
                    idx_j = active_indices[aj]
                    if idx_j in merged_set:
                        continue
                    if branches[idx_j].merge_partner_idx >= 0:
                        continue

                    pos_j = positions_array[aj]

                    if pos_j[2] <= min_merge_height:
                        continue
                    if branches[idx_j].steps_taken < departure_steps:
                        continue

                    dist = np.linalg.norm(pos_i - pos_j)

                    if dist < effective_merge_dist:
                        # Tính merge target
                        br_i = branches[idx_i]
                        br_j = branches[idx_j]
                        prev_pos_i = np.asarray(all_nodes[br_i.node_index][0], dtype=np.float64)
                        prev_pos_j = np.asarray(all_nodes[br_j.node_index][0], dtype=np.float64)

                        total_tips = br_i.tip_count + br_j.tip_count
                        w_i = br_i.tip_count / total_tips
                        w_j = br_j.tip_count / total_tips
                        merge_xy = w_i * prev_pos_i[:2] + w_j * prev_pos_j[:2]

                        dxy_i = np.linalg.norm(prev_pos_i[:2] - merge_xy)
                        dxy_j = np.linalg.norm(prev_pos_j[:2] - merge_xy)

                        tan_limit = sin_angle_limit / cos_angle_limit
                        if tan_limit > 1e-6:
                            merge_z_i = prev_pos_i[2] - dxy_i / tan_limit
                            merge_z_j = prev_pos_j[2] - dxy_j / tan_limit
                            merge_z = max(0.0, min(merge_z_i, merge_z_j))
                        else:
                            merge_z = 0.0

                        merge_target = np.array([merge_xy[0], merge_xy[1], merge_z])

                        # Commit cả hai nhánh → đi thẳng đến target
                        br_i.merge_target = merge_target.copy()
                        br_i.merge_partner_idx = idx_j
                        br_j.merge_target = merge_target.copy()
                        br_j.merge_partner_idx = idx_i
                        break  # Nhánh i đã có partner, tìm nhánh khác

        # --- Tạo nút và cạnh mới trong skeleton ---
        for idx in active_indices:
            if idx in merged_set:
                victim = branches[idx]
                survivor_idx = None
                for s, v in merge_pairs:
                    if v == idx:
                        survivor_idx = s
                        break
                if survivor_idx is not None:
                    pass
                continue

            branch = branches[idx]
            new_pos = new_positions.get(idx, branch.position)

            # Tăng bán kính mỗi bước (nhánh mập dần xuống dưới)
            # (committed merge branches đã tăng ở movement phase)
            if branch.merge_target is None and radius_growth_rate > 0:
                branch.radius *= (1.0 + radius_growth_rate)

            # Tạo nút mới trong skeleton
            new_node_idx = len(all_nodes)
            all_nodes.append((new_pos.copy(), branch.radius))

            # Tạo cạnh từ nút cũ đến nút mới
            all_edges.append((branch.node_index, new_node_idx))

            # Nối các nhánh victim vào nút merge này
            for s, v in merge_pairs:
                if s == idx:
                    victim = branches[v]
                    all_edges.append((victim.node_index, new_node_idx))

            # Cập nhật trạng thái nhánh
            branch.position = new_pos.copy()
            branch.node_index = new_node_idx

        # --- Cập nhật danh sách active (loại bỏ nhánh đã merge) ---
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
