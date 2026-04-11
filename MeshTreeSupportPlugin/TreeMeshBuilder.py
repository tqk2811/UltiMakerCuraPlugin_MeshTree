# ==============================================================================
# Module: Tạo mesh cây support bằng Bézier tube
#
# Mỗi edge trong skeleton là 1 ống Bézier bậc 3:
#   - P0 = vị trí node đầu (gần overhang)
#   - P3 = vị trí node cuối (gần gốc)
#   - P1 = P0 + tangent_start * len/3  (tiếp tuyến tại node đầu)
#   - P2 = P3 - tangent_end   * len/3  (tiếp tuyến tại node cuối)
#
# Tiếp tuyến tại mỗi node = hướng outgoing (đi xuống gốc) → dùng chung
# cho tất cả edge gặp nhau tại node → C1 continuity tại junction.
#
# Đầu vào: skeleton (nodes, edges) từ BranchRouter
# Đầu ra: MeshData cho Cura (triangle soup + normals)
# ==============================================================================

import numpy as np
from UM.Mesh.MeshData import MeshData


# ==============================================================================
# PHẦN 1: RING TẠI MỘT ĐIỂM
# ==============================================================================

def _make_ring(center, direction, radius, segments):
    """Tạo 1 ring tròn gồm `segments` đỉnh vuông góc với direction."""
    d = direction / (np.linalg.norm(direction) + 1e-12)
    ref = np.array([0.0, 0.0, 1.0]) if abs(d[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    perp1 = np.cross(d, ref); perp1 /= np.linalg.norm(perp1)
    perp2 = np.cross(d, perp1)
    angles = np.linspace(0.0, 2.0 * np.pi, segments, endpoint=False)
    return (center
            + radius * np.outer(np.cos(angles), perp1)
            + radius * np.outer(np.sin(angles), perp2))  # (segments, 3)


# ==============================================================================
# PHẦN 2: NỐI 2 RING THÀNH TRIANGLE STRIP
# ==============================================================================

def _connect_rings(ring_a, ring_b):
    """Nối 2 ring thành triangle soup (outward normals, Z-up left-handed)."""
    n = len(ring_a)
    tris = []
    for i in range(n):
        j = (i + 1) % n
        a0, a1 = ring_a[i], ring_a[j]
        b0, b1 = ring_b[i], ring_b[j]
        tris.append(a0); tris.append(b1); tris.append(a1)
        tris.append(a0); tris.append(b0); tris.append(b1)
    return np.array(tris, dtype=np.float64)


# ==============================================================================
# PHẦN 3: BÉZIER BẬC 3
# ==============================================================================

def _bezier_pt(p0, p1, p2, p3, t):
    """Điểm trên Bézier bậc 3 tại tham số t."""
    mt = 1.0 - t
    return mt**3 * p0 + 3.0*mt**2*t * p1 + 3.0*mt*t**2 * p2 + t**3 * p3


def _bezier_tang(p0, p1, p2, p3, t):
    """Tiếp tuyến (đạo hàm) Bézier bậc 3 tại t."""
    mt = 1.0 - t
    return 3.0*mt**2*(p1-p0) + 6.0*mt*t*(p2-p1) + 3.0*t**2*(p3-p2)


def _rings_along_bezier(p0, p1, p2, p3, r_start, r_end, segments, max_ring_length):
    """
    Lấy mẫu đường Bézier, tạo ring tại mỗi mẫu.
    Không bao gồm t=0 (dùng node_ring của idx1 thay thế).
    Không bao gồm t=1 (dùng node_ring của idx2 thay thế).

    Trả về: list of (segments, 3) arrays
    """
    # Ước tính độ dài cung bằng 20 đoạn thẳng
    N_est = 20
    pts_est = [_bezier_pt(p0, p1, p2, p3, i / N_est) for i in range(N_est + 1)]
    arc_len = sum(np.linalg.norm(pts_est[i+1] - pts_est[i]) for i in range(N_est))

    n_seg = max(1, int(np.ceil(arc_len / max_ring_length)))
    if n_seg == 1:
        return []  # chỉ 1 đoạn → nối thẳng 2 node ring

    rings = []
    for i in range(1, n_seg):          # t = 1/n .. (n-1)/n  (bỏ t=0 và t=1)
        t = i / n_seg
        pos  = _bezier_pt(p0, p1, p2, p3, t)
        tang = _bezier_tang(p0, p1, p2, p3, t)
        l = np.linalg.norm(tang)
        tang = tang / l if l > 1e-6 else (p3 - p0) / (np.linalg.norm(p3 - p0) + 1e-12)
        r = r_start + t * (r_end - r_start)
        rings.append(_make_ring(pos, tang, r, segments))

    return rings


# ==============================================================================
# PHẦN 4: NẮP ĐẦU
# ==============================================================================

def _build_cap(center, radius, direction, segments, flip=False):
    """Đĩa tròn đóng đầu nhánh."""
    ring = _make_ring(center, direction, radius, segments)
    tris = []
    for i in range(segments):
        j = (i + 1) % segments
        if not flip:
            tris.append(center); tris.append(ring[i]); tris.append(ring[j])
        else:
            tris.append(center); tris.append(ring[j]); tris.append(ring[i])
    return np.array(tris, dtype=np.float64)


# ==============================================================================
# PHẦN 5: TÍNH TIẾP TUYẾN TẠI MỖI NODE
# ==============================================================================

def _compute_node_tangents(all_nodes, outgoing_edges, incoming_edges):
    """
    Tiếp tuyến tại mỗi node:
      - Có outgoing: dùng hướng trung bình outgoing (đi xuống gốc)
      - Chỉ có incoming (base): dùng hướng incoming
    """
    tangents = {}
    for node_idx in range(len(all_nodes)):
        pos = np.asarray(all_nodes[node_idx][0], dtype=np.float64)
        out_children = outgoing_edges.get(node_idx, [])
        in_parents   = incoming_edges.get(node_idx, [])

        if out_children:
            dirs = []
            for child in out_children:
                d = np.asarray(all_nodes[child][0], dtype=np.float64) - pos
                l = np.linalg.norm(d)
                if l > 1e-6: dirs.append(d / l)
            avg = np.mean(dirs, axis=0) if dirs else np.array([0.0, 0.0, -1.0])
        elif in_parents:
            dirs = []
            for parent in in_parents:
                d = pos - np.asarray(all_nodes[parent][0], dtype=np.float64)
                l = np.linalg.norm(d)
                if l > 1e-6: dirs.append(d / l)
            avg = np.mean(dirs, axis=0) if dirs else np.array([0.0, 0.0, -1.0])
        else:
            avg = np.array([0.0, 0.0, -1.0])

        l = np.linalg.norm(avg)
        tangents[node_idx] = avg / l if l > 1e-6 else np.array([0.0, 0.0, -1.0])

    return tangents


# ==============================================================================
# PHẦN 6: BUILD TOÀN BỘ CÂY
# ==============================================================================

def build_tree_mesh(all_nodes, all_edges, segments=8,
                    base_brim_multiplier=3.0, base_brim_height=0.5,
                    max_ring_length=2.0,
                    cancel_check=None):
    """
    Tạo mesh 3D từ skeleton cây support bằng Bézier tube.

    Tham số:
        all_nodes           : list of (position, radius)
        all_edges           : list of (idx1, idx2)
        segments            : int - số cạnh ring
        base_brim_multiplier: float - hệ số mở rộng đế
        base_brim_height    : float - chiều cao đế (mm)
        max_ring_length     : float - khoảng cách tối đa giữa 2 ring (mm)
        cancel_check        : callable hoặc None
    """
    if not all_nodes or not all_edges:
        return MeshData(vertices=np.zeros((3, 3), dtype=np.float32))

    # --- Bước 1: Topology ---
    child_set      = set()
    parent_set     = set()
    incoming_edges = {}
    outgoing_edges = {}

    for idx1, idx2 in all_edges:
        parent_set.add(idx1)
        child_set.add(idx2)
        outgoing_edges.setdefault(idx1, []).append(idx2)
        incoming_edges.setdefault(idx2, []).append(idx1)

    tip_nodes  = parent_set - child_set
    base_nodes = child_set  - parent_set

    # --- Bước 2: Tiếp tuyến và node rings ---
    node_tangents = _compute_node_tangents(all_nodes, outgoing_edges, incoming_edges)

    node_rings = {}
    for node_idx in range(len(all_nodes)):
        pos    = np.asarray(all_nodes[node_idx][0], dtype=np.float64)
        radius = all_nodes[node_idx][1]
        node_rings[node_idx] = _make_ring(pos, node_tangents[node_idx], radius, segments)

    # --- Bước 3: Bézier tube cho mỗi edge ---
    all_soup = []

    for edge in all_edges:
        if cancel_check is not None and cancel_check():
            return MeshData(vertices=np.zeros((3, 3), dtype=np.float32))

        idx1, idx2 = edge
        p0 = np.asarray(all_nodes[idx1][0], dtype=np.float64)
        p3 = np.asarray(all_nodes[idx2][0], dtype=np.float64)
        r0 = all_nodes[idx1][1]
        r3 = all_nodes[idx2][1]

        tang_start = node_tangents[idx1]   # outgoing từ idx1
        tang_end   = node_tangents[idx2]   # outgoing từ idx2 (tiếp tuyến đến idx2)

        seg_len = np.linalg.norm(p3 - p0)
        ctrl    = seg_len / 3.0
        p1 = p0 + tang_start * ctrl
        p2 = p3 - tang_end   * ctrl       # ngược chiều outgoing của idx2

        ring_start = node_rings[idx1]
        ring_end   = node_rings[idx2]

        mid_rings = _rings_along_bezier(p0, p1, p2, p3, r0, r3, segments, max_ring_length)

        if not mid_rings:
            all_soup.append(_connect_rings(ring_start, ring_end))
        else:
            all_soup.append(_connect_rings(ring_start, mid_rings[0]))
            for k in range(len(mid_rings) - 1):
                all_soup.append(_connect_rings(mid_rings[k], mid_rings[k + 1]))
            all_soup.append(_connect_rings(mid_rings[-1], ring_end))

    # --- Bước 4: Nắp tip và đế base ---
    for tip_idx in tip_nodes:
        pos    = np.asarray(all_nodes[tip_idx][0], dtype=np.float64)
        radius = all_nodes[tip_idx][1]
        all_soup.append(_build_cap(pos, radius, np.array([0.0, 0.0, 1.0]), segments, flip=False))

    for base_idx in base_nodes:
        if cancel_check is not None and cancel_check():
            return MeshData(vertices=np.zeros((3, 3), dtype=np.float32))

        pos    = np.asarray(all_nodes[base_idx][0], dtype=np.float64)
        radius = all_nodes[base_idx][1]

        brim_r      = radius * base_brim_multiplier
        brim_bottom = pos.copy()
        brim_bottom[2] = max(0.0, pos[2] - base_brim_height)

        ring_top = node_rings[base_idx]
        ring_bot = _make_ring(brim_bottom, np.array([0.0, 0.0, -1.0]), brim_r, segments)
        all_soup.append(_connect_rings(ring_top, ring_bot))
        all_soup.append(_build_cap(brim_bottom, brim_r, np.array([0.0, 0.0, -1.0]),
                                   segments, flip=True))

    # --- Bước 5: Ghép và tính normals ---
    if not all_soup:
        return MeshData(vertices=np.zeros((3, 3), dtype=np.float32))

    soup = np.concatenate(all_soup, axis=0).astype(np.float32)
    v0 = soup[0::3]; v1 = soup[1::3]; v2 = soup[2::3]
    face_normals = np.cross(v1 - v0, v2 - v0)
    nlen = np.linalg.norm(face_normals, axis=1, keepdims=True)
    face_normals /= np.maximum(nlen, 1e-10)
    normals = np.zeros_like(soup)
    normals[0::3] = face_normals
    normals[1::3] = face_normals
    normals[2::3] = face_normals

    return MeshData(vertices=soup, normals=normals.astype(np.float32))
