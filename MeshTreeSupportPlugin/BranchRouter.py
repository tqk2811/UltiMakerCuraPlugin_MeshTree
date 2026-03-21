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
                   tip_radius=0.5, min_merge_height=20.0,
                   straight_drop_height=10.0, convergence_strength=0.3,
                   tip_normals=None, radius_growth_rate=0.02):
    """
    Sinh nhánh cây support bằng Space Colonization bottom-up.

    Tham số:
        tip_points    : numpy array (K, 3) - điểm overhang (đầu nhánh)
        collision_field : CollisionField - trường va chạm (SDF + gradient)
        step_size     : float - bước di chuyển mỗi lần lặp (mm)
        merge_distance : float - khoảng cách để merge 2 nhánh (mm)
        min_clearance : float - khoảng cách an toàn tối thiểu đến mesh (mm)
        tip_radius    : float - bán kính nhánh tại ngọn (mm)
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

    Trả về:
        all_nodes : list of (position, radius) - tất cả nút trong skeleton
        all_edges : list of (parent_idx, child_idx) - các cạnh nối nút
    """

    # Trường hợp đặc biệt: không có tip nào
    if len(tip_points) == 0:
        return [], []

    # --- Tính hướng departure cho mỗi tip ---
    # Pháp tuyến từ OverhangDetector là INWARD normal (do left-handed coords).
    # Outward normal = -inward_normal = hướng vuông góc ra xa bề mặt.
    # Đoạn departure đi theo outward normal để tạo chân vuông góc dễ bẻ.
    departure_dirs = []
    if tip_normals is not None and len(tip_normals) == len(tip_points):
        for i in range(len(tip_normals)):
            # Outward normal = đảo chiều inward normal
            outward = -tip_normals[i]
            n_len = np.linalg.norm(outward)
            if n_len > 1e-6:
                outward /= n_len
            else:
                outward = np.array([0.0, 0.0, -1.0])
            departure_dirs.append(outward)
    else:
        # Không có normal → departure mặc định đi xuống
        for i in range(len(tip_points)):
            departure_dirs.append(np.array([0.0, 0.0, -1.0]))

    # Số bước departure: đi vuông góc bề mặt trước khi bắt đầu routing
    # Khoảng 2-3 bước (2-3mm với step_size mặc định) đủ để tạo chân bẻ
    departure_steps = 3

    # --- Khởi tạo skeleton ---
    # all_nodes: danh sách (position, radius) cho mỗi nút
    # all_edges: danh sách (idx_parent, idx_child) cho mỗi cạnh
    all_nodes = []  # [(numpy array (3,), float), ...]
    all_edges = []  # [(int, int), ...]

    # --- Khởi tạo các nhánh từ tip points ---
    # Mỗi nhánh bắt đầu bằng đoạn departure vuông góc bề mặt
    branches = []
    for i in range(len(tip_points)):
        # Tạo nút gốc tại điểm overhang (tip)
        node_pos = tip_points[i].copy()
        node_radius = tip_radius
        node_idx = len(all_nodes)
        all_nodes.append((node_pos.copy(), node_radius))

        # Tạo đoạn departure: vài nút đi theo outward normal
        dep_dir = departure_dirs[i]
        prev_idx = node_idx
        current_pos = node_pos.copy()
        for step in range(departure_steps):
            current_pos = current_pos + dep_dir * step_size
            current_pos[2] = max(0.0, current_pos[2])
            new_idx = len(all_nodes)
            all_nodes.append((current_pos.copy(), node_radius))
            all_edges.append((prev_idx, new_idx))
            prev_idx = new_idx

        # Tạo BranchTip bắt đầu từ cuối đoạn departure
        branch = BranchTip(current_pos, node_radius, prev_idx, tip_count=1)
        branch.prev_direction = dep_dir.copy()  # Khởi tạo smoothing từ hướng departure
        branches.append(branch)

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
            # Ramp up: trong 8 bước đầu, convergence tăng dần từ 0 → full
            # để tránh bẻ góc đột ngột ngay sau đoạn departure vuông góc
            ramp_steps = 8
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

            # === Chuẩn hóa và áp dụng bước di chuyển ===
            dir_length = np.linalg.norm(direction)
            if dir_length > 1e-6:
                direction /= dir_length

            # Đảm bảo luôn có thành phần đi xuống (tránh nhánh đi ngang mãi)
            if direction[2] > -0.3:
                direction[2] = -0.3
                # Chuẩn hóa lại sau khi điều chỉnh
                dir_length = np.linalg.norm(direction)
                if dir_length > 1e-6:
                    direction /= dir_length

            # === Smoothing: trộn với hướng bước trước ===
            # Tránh thay đổi hướng đột ngột gây gấp khúc zíc-zắc
            # Vài bước đầu: smoothing mạnh hơn (50% cũ) để chuyển tiếp mềm
            # từ departure → routing. Sau đó: 30% cũ, 70% mới.
            if branch.steps_taken < ramp_steps:
                old_weight = 0.5
            else:
                old_weight = 0.3
            smoothed = (1.0 - old_weight) * direction + old_weight * branch.prev_direction
            sm_len = np.linalg.norm(smoothed)
            if sm_len > 1e-6:
                smoothed /= sm_len
            else:
                smoothed = direction

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

            # Lưu hướng cho smoothing bước sau
            branch.prev_direction = smoothed.copy()
            branch.steps_taken += 1

            new_positions[idx] = new_pos

        # --- Kiểm tra và thực hiện merge ---
        # Chỉ merge khi Z > min_merge_height (tránh merge quá gần bàn in)
        merged_set = set()     # Tập nhánh bị merge (hủy)
        merge_pairs = []       # Danh sách cặp (nhánh sống, nhánh hủy)

        if len(active_indices) > 1:
            # Xây dựng ma trận khoảng cách giữa các nhánh active
            positions_array = np.array([
                new_positions.get(i, branches[i].position) for i in active_indices
            ])

            for ai in range(len(active_indices)):
                idx_i = active_indices[ai]
                if idx_i in merged_set:
                    continue

                pos_i = positions_array[ai]

                # Chỉ merge nếu Z > min_merge_height
                if pos_i[2] <= min_merge_height:
                    continue

                # Adaptive merge distance: càng xuống thấp, khoảng cách merge càng lớn
                # Tại Z cao (gần tip): dùng merge_distance gốc
                # Tại Z thấp (gần bàn): merge_distance * 3 (gộp mạnh hơn)
                # Công thức: effective = base * (1 + 2 * (1 - z/max_z))
                height_ratio = pos_i[2] / initial_max_z if initial_max_z > 0 else 0
                height_ratio = min(1.0, max(0.0, height_ratio))
                effective_merge_dist = merge_distance * (1.0 + 2.0 * (1.0 - height_ratio))

                for aj in range(ai + 1, len(active_indices)):
                    idx_j = active_indices[aj]
                    if idx_j in merged_set:
                        continue

                    pos_j = positions_array[aj]

                    if pos_j[2] <= min_merge_height:
                        continue

                    # Tính khoảng cách 3D giữa 2 nhánh
                    dist = np.linalg.norm(pos_i - pos_j)

                    if dist < effective_merge_dist:
                        # Merge: nhánh có nhiều tip hơn sống sót
                        if branches[idx_i].tip_count >= branches[idx_j].tip_count:
                            survivor, victim = idx_i, idx_j
                        else:
                            survivor, victim = idx_j, idx_i

                        merge_pairs.append((survivor, victim))
                        merged_set.add(victim)

        # --- Áp dụng merge ---
        for survivor_idx, victim_idx in merge_pairs:
            survivor = branches[survivor_idx]
            victim = branches[victim_idx]

            # Điểm merge = trung điểm giữa 2 nhánh
            merge_pos = (
                new_positions.get(survivor_idx, survivor.position) +
                new_positions.get(victim_idx, victim.position)
            ) / 2.0

            # Cập nhật vị trí survivor về điểm merge
            new_positions[survivor_idx] = merge_pos

            # Tính bán kính mới theo định luật Murray
            new_radius = _murray_radius(survivor.radius, victim.radius)
            survivor.radius = new_radius
            survivor.tip_count += victim.tip_count

        # --- Tạo nút và cạnh mới trong skeleton ---
        for idx in active_indices:
            if idx in merged_set:
                # Nhánh bị merge: tạo nút merge và cạnh nối đến survivor
                victim = branches[idx]
                # Tìm survivor tương ứng
                survivor_idx = None
                for s, v in merge_pairs:
                    if v == idx:
                        survivor_idx = s
                        break

                if survivor_idx is not None:
                    # Nút merge sẽ được tạo bởi survivor, ta chỉ cần ghi nhận
                    # rằng victim kết nối đến nút merge đó
                    pass
                continue

            branch = branches[idx]
            new_pos = new_positions.get(idx, branch.position)

            # Tăng bán kính mỗi bước (nhánh mập dần xuống dưới)
            if radius_growth_rate > 0:
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
                    # Cạnh từ nút cuối của victim đến nút merge
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
