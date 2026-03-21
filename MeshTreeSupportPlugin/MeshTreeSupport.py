# ==============================================================================
# Module: Extension chính của plugin MeshTreeSupport
#
# Lớp MeshTreeSupport kế thừa UM.Extension.Extension:
# - Thêm mục "Sinh cây Support hữu cơ" vào menu Extensions của Cura
# - Khi người dùng nhấn: trích xuất mesh, khởi chạy Job nền
# - Khi Job hoàn thành: dùng callLater() thêm mesh support vào scene
#
# Hệ tọa độ:
# - Cura sử dụng hệ tọa độ Y-up (quy ước OpenGL)
# - Plugin chuyển sang Z-up khi xử lý (quy ước 3D printing)
# - Khi thêm mesh vào scene: chuyển ngược Z-up → Y-up
#
# Luồng thực thi:
# - __init__(), _start_generation(), _on_job_finished(): Main thread (Qt)
# - MeshTreeSupportJob.run(): Worker thread (Cura JobQueue)
# ==============================================================================

import numpy as np

from UM.Extension import Extension
from UM.Logger import Logger
from UM.Application import Application
from UM.Scene.Iterator.DepthFirstIterator import DepthFirstIterator
from UM.Operations.AddSceneNodeOperation import AddSceneNodeOperation
from UM.Mesh.MeshData import MeshData

from cura.CuraApplication import CuraApplication
from cura.Scene.CuraSceneNode import CuraSceneNode
from cura.Scene.BuildPlateDecorator import BuildPlateDecorator
from cura.Scene.SliceableObjectDecorator import SliceableObjectDecorator

from .MeshTreeSupportJob import MeshTreeSupportJob


class MeshTreeSupport(Extension):
    """
    Extension plugin: thêm chức năng sinh cây support hữu cơ vào menu Cura.

    Chức năng:
    1. Quét tất cả mesh trên bàn in
    2. Phát hiện vùng lơ lửng
    3. Sinh cấu trúc cây chống đỡ
    4. Thêm mesh support vào scene

    Thuộc tính:
        _job : MeshTreeSupportJob - Job đang chạy (hoặc None)
    """

    def __init__(self):
        """
        Khởi tạo Extension: đăng ký menu item trong Cura.
        Chạy trên Main thread khi Cura khởi động.
        """
        super().__init__()

        # Đặt tên menu và thêm mục
        self.setMenuName("Mesh Tree Support")
        self.addMenuItem("Sinh cây Support hữu cơ", self._start_generation)

        # Tham chiếu đến Job đang chạy (nếu có)
        self._job = None

        Logger.log("i", "MeshTreeSupport Extension đã khởi tạo")

    def _start_generation(self):
        """
        Callback khi người dùng nhấn menu item.
        Trích xuất mesh từ scene → khởi chạy Job nền.

        Chạy trên: Main thread (Qt event loop)
        """

        Logger.log("i", "MeshTreeSupport: Bắt đầu sinh cây support...")

        # --- Bước 1: Thu thập tất cả mesh trên bàn in ---
        scene = CuraApplication.getInstance().getController().getScene()
        all_vertices = []   # Danh sách mảng vertices từ mỗi node
        all_faces = []      # Danh sách mảng faces (đã offset chỉ số)
        vertex_offset = 0   # Offset chỉ số khi ghép nhiều mesh

        # Duyệt toàn bộ scene tree bằng DepthFirstIterator
        for node in DepthFirstIterator(scene.getRoot()):
            # Chỉ xử lý node có thể slice (mesh in được)
            if not node.callDecoration("isSliceable"):
                continue

            # Bỏ qua mesh support đã có (tránh tạo support cho support)
            per_mesh_stack = node.callDecoration("getStack")
            if per_mesh_stack:
                if per_mesh_stack.getProperty("support_mesh", "value"):
                    continue

            mesh_data = node.getMeshData()
            if mesh_data is None:
                continue

            # Lấy vertices ở hệ tọa độ cục bộ (local coordinates)
            local_verts = mesh_data.getVertices()
            if local_verts is None or len(local_verts) == 0:
                continue

            # --- Chuyển vertices sang hệ tọa độ thế giới (world coordinates) ---
            # Áp dụng ma trận biến đổi thế giới 4x4 của node
            transform_matrix = node.getWorldTransformation().getData()  # numpy 4x4

            # Chuyển sang tọa độ đồng nhất: thêm cột w=1
            num_verts = len(local_verts)
            homo_verts = np.ones((num_verts, 4), dtype=np.float64)
            homo_verts[:, :3] = local_verts

            # Nhân ma trận: [4x4] × [4xN]^T = [4xN]^T → lấy 3 thành phần đầu
            world_verts = (transform_matrix @ homo_verts.T).T[:, :3]

            # --- Chuyển từ Y-up (Cura) sang Z-up (3D printing) ---
            # Cura: X=phải, Y=cao, Z=trước
            # 3D printing: X=phải, Y=trước, Z=cao
            # Hoán đổi: new_Y = old_Z, new_Z = old_Y
            world_verts_zup = world_verts.copy()
            world_verts_zup[:, 1] = world_verts[:, 2]  # Y_new = Z_old
            world_verts_zup[:, 2] = world_verts[:, 1]  # Z_new = Y_old

            # --- Lấy chỉ số tam giác (face indices) ---
            indices = mesh_data.getIndices()
            if indices is not None:
                # Mesh có chỉ số: dịch theo offset
                local_faces = indices.copy()
            else:
                # Triangle soup: mỗi 3 đỉnh liên tiếp = 1 tam giác
                num_triangles = num_verts // 3
                local_faces = np.arange(num_triangles * 3, dtype=np.int32).reshape(-1, 3)

            # Dịch chỉ số faces theo offset (khi ghép nhiều mesh)
            offset_faces = local_faces + vertex_offset

            all_vertices.append(world_verts_zup)
            all_faces.append(offset_faces)
            vertex_offset += num_verts

        # --- Kiểm tra: có mesh nào không? ---
        if not all_vertices:
            Logger.log("w", "MeshTreeSupport: Không tìm thấy mesh nào trên bàn in!")
            return

        # Ghép tất cả mesh thành 1
        combined_verts = np.vstack(all_vertices).astype(np.float64)   # (N, 3)
        combined_faces = np.vstack(all_faces).astype(np.int32)        # (M, 3)

        Logger.log("i", "MeshTreeSupport: Mesh gộp có %d đỉnh, %d tam giác",
                   len(combined_verts), len(combined_faces))

        # --- Bước 2: Tạo và khởi chạy Job nền ---
        self._job = MeshTreeSupportJob(combined_verts, combined_faces)

        # Kết nối signal finished → callback trên main thread
        self._job.finished.connect(self._on_job_finished)

        # Khởi chạy Job trên worker thread (không block UI)
        self._job.start()

        Logger.log("i", "MeshTreeSupport: Job đã được khởi chạy trên worker thread")

    def _on_job_finished(self, job):
        """
        Callback khi Job hoàn thành.
        Được gọi từ worker thread → dùng callLater() để chuyển về main thread.

        Tham số:
            job : MeshTreeSupportJob - Job vừa hoàn thành
        """

        # Chuyển sang main thread bằng callLater (an toàn cho Qt)
        Application.getInstance().callLater(self._add_support_to_scene, job)

    def _add_support_to_scene(self, job):
        """
        Thêm mesh cây support vào scene Cura.
        Chạy trên: Main thread (được gọi từ callLater)

        Quy trình:
        1. Lấy MeshData từ Job
        2. Chuyển vertices từ Z-up → Y-up (Cura)
        3. Tạo CuraSceneNode với MeshData
        4. Đánh dấu là support_mesh = True
        5. Thêm vào scene
        """

        mesh_data = job.getResultMeshData()
        if mesh_data is None:
            Logger.log("w", "MeshTreeSupport: Job hoàn thành nhưng không có mesh.")
            return

        # --- Chuyển vertices từ Z-up → Y-up (Cura) ---
        # Hoán đổi ngược: Y_cura = Z_zup, Z_cura = Y_zup
        original_verts = mesh_data.getVertices()
        if original_verts is None or len(original_verts) == 0:
            Logger.log("w", "MeshTreeSupport: Mesh rỗng.")
            return

        converted_verts = original_verts.copy()
        converted_verts[:, 1] = original_verts[:, 2]  # Y_cura = Z_zup
        converted_verts[:, 2] = original_verts[:, 1]  # Z_cura = Y_zup

        # Chuyển đổi normals tương tự (nếu có)
        original_normals = mesh_data.getNormals()
        converted_normals = None
        if original_normals is not None and len(original_normals) > 0:
            converted_normals = original_normals.copy()
            converted_normals[:, 1] = original_normals[:, 2]
            converted_normals[:, 2] = original_normals[:, 1]

        # Tạo MeshData mới với tọa độ Y-up
        cura_mesh_data = MeshData(
            vertices=converted_verts.astype(np.float32),
            normals=converted_normals.astype(np.float32) if converted_normals is not None else None
        )

        # --- Tạo CuraSceneNode ---
        support_node = CuraSceneNode()
        support_node.setName("MeshTreeSupport")
        support_node.setSelectable(True)
        support_node.setMeshData(cura_mesh_data)

        # Thêm decorator để Cura nhận diện node
        active_build_plate = CuraApplication.getInstance().getMultiBuildPlateModel().activeBuildPlate
        support_node.addDecorator(BuildPlateDecorator(active_build_plate))
        support_node.addDecorator(SliceableObjectDecorator())

        # --- Đánh dấu là support mesh ---
        # Cura sẽ xử lý node này như support khi slice
        scene = CuraApplication.getInstance().getController().getScene()
        op = AddSceneNodeOperation(support_node, scene.getRoot())
        op.push()

        # Đặt thuộc tính support_mesh = True qua per-object settings
        stack = support_node.callDecoration("getStack")
        if stack:
            settings = stack.getTop()
            definition = stack.getSettingDefinition("support_mesh")
            if definition:
                from UM.Settings.SettingInstance import SettingInstance
                instance = SettingInstance(definition, settings)
                instance.setProperty("value", True)
                instance.resetState()
                settings.addInstance(instance)
                Logger.log("i", "MeshTreeSupport: Đã đánh dấu support_mesh = True")

        Logger.log("i", "MeshTreeSupport: Đã thêm mesh cây support vào scene! "
                   "(%d đỉnh)", cura_mesh_data.getVertexCount())
