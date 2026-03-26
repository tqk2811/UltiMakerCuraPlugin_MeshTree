# ==============================================================================
# Module: Tạo mesh nhánh cây (Branch Mesh Builder)
#
# Chuyển đồ thị nhánh (BranchGraph) thành triangle soup mesh:
#   - Ống octagon (frustum) cho mỗi đoạn nhánh
#   - Junction mượt (Bézier blend) tại điểm gộp
#   - Đĩa đáy (base pad) tại Z=0
#   - Landing shell (pad) khi đáp lên vật thể
#
# Đầu vào: BranchGraph từ BranchRouter
# Đầu ra: triangle soup (verts, normals) cho Cura MeshData
#
# Luồng thực thi: worker thread (trong Job.run())
# ==============================================================================

import numpy as np

# Số cạnh cross-section (octagon)
_N_SIDES = 8


def build_branch_mesh(branch_graph, collision_field=None,
                      shell_gap=0.1, shell_thickness=0.5):
    """
    Tạo mesh từ BranchGraph.

    Tham số:
        branch_graph    : BranchGraph từ BranchRouter
        collision_field : CollisionField (dùng cho landing shell projection)
        shell_gap       : float (mm)
        shell_thickness : float (mm)

    Trả về:
        branch_verts   : numpy array (V, 3) float32 - triangle soup
        branch_normals : numpy array (V, 3) float32 - triangle soup normals
    """
    all_soup = []

    # --- 1. Ống nhánh (tube segments) ---
    for path in branch_graph.paths:
        if path.merged_into is not None and len(path.nodes) < 2:
            continue

        tube_verts = _build_tube_for_path(path)
        if len(tube_verts) > 0:
            all_soup.append(tube_verts)

    # --- 2. Junction mesh tại merge points ---
    for z_val, child_ids, parent_id in branch_graph.merge_events:
        junction_verts = _build_junction(
            branch_graph.paths, child_ids, parent_id
        )
        if junction_verts is not None and len(junction_verts) > 0:
            all_soup.append(junction_verts)

    # --- 3. Base pads (Z=0) ---
    for path in branch_graph.paths:
        if path.merged_into is not None:
            continue
        if path.landed:
            continue
        if not path.nodes:
            continue

        last_node = path.nodes[-1]
        if abs(last_node.position[2]) < 0.5:  # Gần sàn
            base_verts = _build_base_pad(last_node)
            if len(base_verts) > 0:
                all_soup.append(base_verts)

    # --- 4. Landing shells ---
    for branch_id, landing_pos, landing_normal in branch_graph.landing_events:
        path = branch_graph.paths[branch_id]
        if not path.nodes:
            continue
        last_node = path.nodes[-1]
        landing_verts = _build_landing_shell(
            landing_pos, landing_normal, last_node.radius,
            shell_gap, shell_thickness
        )
        if len(landing_verts) > 0:
            all_soup.append(landing_verts)

    # --- Ghép + tính normals ---
    if not all_soup:
        return (np.zeros((0, 3), dtype=np.float32),
                np.zeros((0, 3), dtype=np.float32))

    all_verts = np.concatenate(all_soup, axis=0)
    return _compute_soup_normals(all_verts)


def _build_tube_for_path(path):
    """Tạo ống octagon cho 1 path (chuỗi nodes)."""
    nodes = path.nodes
    if len(nodes) < 2:
        return np.zeros((0, 3), dtype=np.float64)

    soup = []

    # Tạo ring cho mỗi node
    rings = []
    for node in nodes:
        axis = _estimate_axis(node, nodes)
        ring = _make_ring(node.position, axis, _N_SIDES, node.radius)
        rings.append(ring)

    # Nối rings liên tiếp
    for i in range(len(rings) - 1):
        tris = _connect_rings_same(rings[i], rings[i + 1])
        if len(tris) > 0:
            soup.append(tris)

    if not soup:
        return np.zeros((0, 3), dtype=np.float64)
    return np.concatenate(soup, axis=0)


def _estimate_axis(node, all_nodes):
    """Ước lượng hướng trục tại node (dùng cho cross-section orientation)."""
    idx = None
    for i, n in enumerate(all_nodes):
        if n is node:
            idx = i
            break

    if idx is None:
        return np.array([0.0, 0.0, -1.0])

    if idx > 0 and idx < len(all_nodes) - 1:
        # Central difference
        axis = all_nodes[idx + 1].position - all_nodes[idx - 1].position
    elif idx < len(all_nodes) - 1:
        axis = all_nodes[idx + 1].position - node.position
    elif idx > 0:
        axis = node.position - all_nodes[idx - 1].position
    else:
        axis = np.array([0.0, 0.0, -1.0])

    length = np.linalg.norm(axis)
    if length > 1e-10:
        axis /= length
    else:
        axis = np.array([0.0, 0.0, -1.0])

    return axis


def _make_ring(center, axis, n_sides, radius):
    """Tạo ring regular n-gon vuông góc với axis."""
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


def _connect_rings_same(ring0, ring1):
    """Nối 2 ring cùng số đỉnh bằng quad strip."""
    n = len(ring0)
    tris = np.zeros((n * 2 * 3, 3), dtype=np.float64)

    for i in range(n):
        j = (i + 1) % n
        base = i * 6
        # Tri 1
        tris[base] = ring0[i]
        tris[base + 1] = ring1[i]
        tris[base + 2] = ring0[j]
        # Tri 2
        tris[base + 3] = ring0[j]
        tris[base + 4] = ring1[i]
        tris[base + 5] = ring1[j]

    return tris


def _build_junction(paths, child_ids, parent_id):
    """
    Tạo junction mesh mượt (Bézier blend) tại điểm gộp.

    Nối nhánh con → nhánh cha bằng cubic Bézier curve.
    Cross-section nội suy từ r_child → r_parent dọc curve.
    """
    parent_path = paths[parent_id]

    # Tìm merge node trong parent path
    merge_node = None
    merge_idx = None
    for i, node in enumerate(parent_path.nodes):
        if node.is_merge_point:
            merge_node = node
            merge_idx = i
            break

    if merge_node is None:
        return None

    soup = []

    for cid in child_ids:
        if cid == parent_id:
            continue

        child_path = paths[cid]
        if len(child_path.nodes) < 2:
            continue

        # Đầu cuối nhánh con
        c_end = child_path.nodes[-1]
        c_prev = child_path.nodes[-2] if len(child_path.nodes) >= 2 else c_end

        # Hướng nhánh con tại điểm cuối
        c_dir = c_end.position - c_prev.position
        c_len = np.linalg.norm(c_dir)
        if c_len > 1e-10:
            c_dir /= c_len
        else:
            c_dir = np.array([0.0, 0.0, -1.0])

        # Hướng nhánh cha sau merge
        if merge_idx is not None and merge_idx + 1 < len(parent_path.nodes):
            p_next = parent_path.nodes[merge_idx + 1]
            p_dir = p_next.position - merge_node.position
            p_len = np.linalg.norm(p_dir)
            if p_len > 1e-10:
                p_dir /= p_len
            else:
                p_dir = np.array([0.0, 0.0, -1.0])
        else:
            p_dir = np.array([0.0, 0.0, -1.0])

        # Bézier: P0=child_end, P1=child_end+c_dir*L, P2=merge-p_dir*L, P3=merge
        L = np.linalg.norm(c_end.position - merge_node.position) * 0.4
        P0 = c_end.position
        P1 = c_end.position + c_dir * L
        P2 = merge_node.position - p_dir * L
        P3 = merge_node.position

        # Sample Bézier curve
        n_samples = max(4, int(np.linalg.norm(P3 - P0) / 1.0))
        rings = []
        for si in range(n_samples + 1):
            t = si / n_samples
            pos = _cubic_bezier(P0, P1, P2, P3, t)
            tangent = _cubic_bezier_tangent(P0, P1, P2, P3, t)
            tl = np.linalg.norm(tangent)
            if tl > 1e-10:
                tangent /= tl
            else:
                tangent = np.array([0.0, 0.0, -1.0])

            # Radius nội suy
            r = c_end.radius * (1 - t) + merge_node.radius * t
            ring = _make_ring(pos, tangent, _N_SIDES, r)
            rings.append(ring)

        for i in range(len(rings) - 1):
            tris = _connect_rings_same(rings[i], rings[i + 1])
            if len(tris) > 0:
                soup.append(tris)

    if not soup:
        return None
    return np.concatenate(soup, axis=0)


def _cubic_bezier(P0, P1, P2, P3, t):
    """Cubic Bézier tại t."""
    u = 1 - t
    return u**3 * P0 + 3 * u**2 * t * P1 + 3 * u * t**2 * P2 + t**3 * P3


def _cubic_bezier_tangent(P0, P1, P2, P3, t):
    """Đạo hàm Cubic Bézier tại t (tangent vector)."""
    u = 1 - t
    return (3 * u**2 * (P1 - P0) + 6 * u * t * (P2 - P1) +
            3 * t**2 * (P3 - P2))


def _build_base_pad(node):
    """
    Tạo đĩa đáy (base pad) tại Z=0 cho nhánh đã tới sàn.
    Đĩa octagon phẳng, hơi rộng hơn nhánh cho adhesion.
    """
    base_radius = node.radius * 1.5  # Rộng hơn 50% cho bám sàn
    center = node.position.copy()
    center[2] = 0.0

    axis = np.array([0.0, 0.0, -1.0])
    ring = _make_ring(center, axis, _N_SIDES, base_radius)

    # Fan triangulation
    tris = []
    for i in range(_N_SIDES):
        j = (i + 1) % _N_SIDES
        tris.append([center, ring[i], ring[j]])

    return np.array(tris, dtype=np.float64).reshape(-1, 3)


def _build_landing_shell(position, normal, radius, gap, thickness):
    """
    Tạo landing shell (pad mỏng) khi nhánh đáp lên bề mặt vật thể.
    Project lên mặt cong bằng offset theo normal.

    2 lớp: inner (gap) + outer (gap + thickness), hình octagon.
    """
    n_len = np.linalg.norm(normal)
    if n_len < 1e-10:
        normal = np.array([0.0, 0.0, 1.0])
    else:
        normal = normal / n_len

    pad_radius = radius * 1.2
    axis = normal

    # Inner surface (closer to model)
    inner_center = position + normal * gap
    inner_ring = _make_ring(inner_center, axis, _N_SIDES, pad_radius)

    # Outer surface (away from model)
    outer_center = position + normal * (gap + thickness)
    outer_ring = _make_ring(outer_center, axis, _N_SIDES, pad_radius)

    soup = []

    # Inner disc (fan, reversed winding)
    for i in range(_N_SIDES):
        j = (i + 1) % _N_SIDES
        soup.append([inner_center, inner_ring[j], inner_ring[i]])

    # Outer disc
    for i in range(_N_SIDES):
        j = (i + 1) % _N_SIDES
        soup.append([outer_center, outer_ring[i], outer_ring[j]])

    # Side walls
    tris = _connect_rings_same(inner_ring, outer_ring)
    soup_arr = np.array(soup, dtype=np.float64).reshape(-1, 3)
    return np.concatenate([soup_arr, tris], axis=0)


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
