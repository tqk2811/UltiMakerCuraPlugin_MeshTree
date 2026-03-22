# ==============================================================================
# Module: Phát hiện vùng lơ lửng (Overhang Detection)
#
# Thuật toán: Facet Normal Angle Detection
# - Tính pháp tuyến (normal) của từng mặt tam giác bằng tích chéo (cross product)
# - So sánh góc giữa pháp tuyến và hướng xuống dưới (-Z) với ngưỡng overhang
# - Mặt có pháp tuyến chỉ xuống quá ngưỡng → vùng lơ lửng cần chống đỡ
#
# Hệ tọa độ: Z-up (Z là trục đứng, bàn in tại Z=0)
#
# Đầu vào: vertices (N,3), faces (M,3), ngưỡng góc (độ)
# Đầu ra: tọa độ trọng tâm các mặt lơ lửng, pháp tuyến tương ứng
#
# Luồng thực thi: Chạy trong worker thread (bên trong Job.run())
# ==============================================================================

import numpy as np


def detect_overhangs(vertices, faces, threshold_angle_deg=45.0, min_height=0.5):
    """
    Phát hiện các mặt tam giác lơ lửng (overhang) trên mesh 3D.

    Thuật toán Facet Normal Angle Detection:
    1. Tính pháp tuyến mỗi mặt bằng tích chéo hai cạnh
    2. So sánh góc giữa pháp tuyến và hướng xuống (-Z)
    3. Nếu góc < ngưỡng → mặt đó lơ lửng, cần support

    Tham số:
        vertices    : numpy array (N, 3) - tọa độ đỉnh mesh
        faces       : numpy array (M, 3) - chỉ số đỉnh cho mỗi tam giác
        threshold_angle_deg : float - ngưỡng góc overhang (độ), mặc định 45°
        min_height  : float - chiều cao tối thiểu trên bàn in (mm) để lọc mặt sát đáy

    Trả về:
        overhang_centroids : numpy array (K, 3) - trọng tâm các mặt lơ lửng
        overhang_normals   : numpy array (K, 3) - pháp tuyến đơn vị các mặt lơ lửng
        overhang_mask      : numpy array (M,) bool - mask đánh dấu mặt lơ lửng
        all_normals        : numpy array (M, 3) - pháp tuyến đơn vị tất cả mặt
    """

    # --- Bước 1: Trích xuất 3 đỉnh của mỗi tam giác ---
    # v0, v1, v2 có shape (M, 3), mỗi hàng là tọa độ 1 đỉnh
    v0 = vertices[faces[:, 0]]  # Đỉnh thứ nhất của mỗi tam giác
    v1 = vertices[faces[:, 1]]  # Đỉnh thứ hai
    v2 = vertices[faces[:, 2]]  # Đỉnh thứ ba

    # --- Bước 2: Tính pháp tuyến mặt bằng tích chéo (cross product) ---
    # Hai cạnh của tam giác: edge1 = v1-v0, edge2 = v2-v0
    edge1 = v1 - v0  # Cạnh 1: vector từ v0 đến v1, shape (M, 3)
    edge2 = v2 - v0  # Cạnh 2: vector từ v0 đến v2, shape (M, 3)

    # Pháp tuyến = tích chéo hai cạnh (vuông góc với mặt tam giác)
    normals = np.cross(edge1, edge2)  # shape (M, 3)

    # --- Bước 3: Chuẩn hóa pháp tuyến về vector đơn vị ---
    # Tính độ dài (magnitude) của từng pháp tuyến
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)  # shape (M, 1)

    # Tránh chia cho 0 (tam giác suy biến có diện tích ≈ 0)
    lengths = np.maximum(lengths, 1e-10)

    # Chuẩn hóa: chia mỗi vector cho độ dài của nó → vector đơn vị
    normals = normals / lengths  # shape (M, 3), mỗi hàng có ||n|| = 1

    # --- Bước 4: Xác định mặt lơ lửng bằng góc pháp tuyến ---
    # Lưu ý: dữ liệu đang ở hệ tọa độ Z-up left-handed (sau hoán đổi Y↔Z),
    # nên cross(edge1, edge2) cho INWARD normal (ngược chiều outward).
    #
    # Mặt overhang: outward normal chỉ XUỐNG → inward normal chỉ LÊN (nz > 0)
    # Điều kiện: nz > cos(threshold)  (inward nz dương, mạnh lên trên)
    #
    # Ví dụ threshold = 45°:
    #   cos(45°) ≈ 0.707
    #   Điều kiện: nz > 0.707 (inward normal chỉ mạnh lên → outward chỉ mạnh xuống)

    # Thành phần Z của pháp tuyến (chính là cos góc với trục Z)
    nz = normals[:, 2]  # shape (M,)

    # Ngưỡng cosine tương ứng với góc overhang
    overhang_cos = np.cos(np.radians(threshold_angle_deg))

    # Sau phép hoán đổi Y↔Z để chuyển Cura (Y-up, right-handed) sang Z-up,
    # hệ tọa độ trở thành left-handed. Do đó cross(edge1, edge2) tính ra
    # INWARD normal thay vì outward normal.
    #
    # Mặt overhang có outward normal chỉ XUỐNG (nz_outward < 0),
    # tức inward normal chỉ LÊN (nz_inward > 0).
    # Điều kiện đúng: nz > +cos(threshold) (inward normal mạnh lên trên)
    overhang_mask = nz > overhang_cos  # shape (M,)

    # --- Bước 5: Tính trọng tâm (centroid) của mỗi tam giác ---
    # Trọng tâm = trung bình cộng 3 đỉnh
    centroids = (v0 + v1 + v2) / 3.0  # shape (M, 3)

    # --- Bước 6: Lọc bỏ mặt quá gần bàn in ---
    # Mặt có trọng tâm Z < min_height không cần support (đã nằm trên bàn in)
    height_mask = centroids[:, 2] > min_height  # shape (M,)

    # --- Bước 7: Kết hợp hai điều kiện ---
    # Mặt lơ lửng VÀ đủ cao trên bàn in
    final_mask = overhang_mask & height_mask  # shape (M,)

    # --- Bước 8: Trích xuất kết quả ---
    overhang_centroids = centroids[final_mask]  # shape (K, 3)
    overhang_normals = normals[final_mask]      # shape (K, 3)

    return overhang_centroids, overhang_normals, final_mask, normals
