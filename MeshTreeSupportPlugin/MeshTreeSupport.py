# ==============================================================================
# Module: Extension chính của plugin MeshTreeSupport
#
# Lớp MeshTreeSupport kế thừa QObject + Extension:
# - Hiển thị dialog QML để tinh chỉnh thông số + theo dõi tiến độ
# - Tự động lưu/load thông số từ file settings.json
# - Khi người dùng nhấn "Bắt đầu": trích xuất mesh, khởi chạy Job nền
# - Khi Job hoàn thành: dùng callLater() thêm mesh support vào scene
#
# Giao tiếp QML ↔ Python:
# - pyqtProperty: progressValue, statusText, isRunning (reactive)
# - pyqtSlot: getSetting, updateSetting, resetSettings, startGeneration
# - pyqtSignal: settingsChanged, progressChanged, statusTextChanged, isRunningChanged
#
# Luồng thực thi:
# - Tất cả methods trừ _on_progress: Main thread (Qt event loop)
# - _on_progress: có thể từ worker thread → dùng callLater()
# ==============================================================================

import os
import json
import numpy as np

try:
    from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, pyqtProperty
except ImportError:
    from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, pyqtProperty

from UM.Extension import Extension
from UM.Logger import Logger
from UM.Application import Application
from UM.Scene.Iterator.DepthFirstIterator import DepthFirstIterator
from UM.Operations.AddSceneNodeOperation import AddSceneNodeOperation
from UM.Operations.RemoveSceneNodeOperation import RemoveSceneNodeOperation
from UM.Mesh.MeshData import MeshData

from cura.CuraApplication import CuraApplication
from cura.Scene.CuraSceneNode import CuraSceneNode
from cura.Scene.BuildPlateDecorator import BuildPlateDecorator
from cura.Scene.SliceableObjectDecorator import SliceableObjectDecorator

from .MeshTreeSupportJob import MeshTreeSupportJob


# ==============================================================================
# SETTINGS: Giá trị mặc định và đường dẫn file lưu trữ
# ==============================================================================

# Đường dẫn file JSON lưu thông số (cùng thư mục plugin)
_SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")

# Giá trị mặc định cho tất cả tham số
_DEFAULT_SETTINGS = {
    "overhang_angle": 45.0,          # Góc overhang (độ)
    "min_overhang_height": 0.5,      # Chiều cao tối thiểu trên bàn in (mm)
    "shell_thickness": 0.5,          # Độ dày vỏ overhang (mm)
    "shell_gap": 0.3,                # Khoảng cách vỏ đến bề mặt vật thể (mm)
}

# Các key là integer (không phải float)
_INT_SETTINGS = set()


def _load_settings():
    """
    Đọc thông số từ file settings.json.
    Nếu file không tồn tại hoặc lỗi → dùng giá trị mặc định.
    Merge với default để đảm bảo có đủ key (khi thêm setting mới).
    """
    settings = _DEFAULT_SETTINGS.copy()
    try:
        with open(_SETTINGS_FILE, 'r', encoding='utf-8') as f:
            saved = json.load(f)
        # Ghi đè default bằng giá trị đã lưu (chỉ các key hợp lệ)
        for key in _DEFAULT_SETTINGS:
            if key in saved:
                settings[key] = saved[key]
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        pass
    return settings


def _save_settings(settings):
    """Ghi thông số ra file settings.json."""
    try:
        with open(_SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except IOError as e:
        Logger.log("w", "MeshTreeSupport: Không thể lưu settings: %s", str(e))


# ==============================================================================
# LỚP CHÍNH: MeshTreeSupport
#
# Kế thừa QObject (cho pyqtProperty/Signal/Slot giao tiếp QML)
# và Extension (cho menu item trong Cura).
# ==============================================================================

class MeshTreeSupport(QObject, Extension):
    """
    Extension + QObject: giao diện chính của plugin.

    - Hiển thị dialog QML với settings + progress
    - Quản lý lifecycle của MeshTreeSupportJob
    - Tự động lưu/load thông số
    """

    # --- Qt Signals cho QML binding ---
    settingsChanged = pyqtSignal()       # Khi settings thay đổi (update hoặc reset)
    progressChanged = pyqtSignal()       # Khi tiến độ Job thay đổi
    statusTextChanged = pyqtSignal()     # Khi trạng thái thay đổi
    isRunningChanged = pyqtSignal()      # Khi Job bắt đầu/kết thúc

    def __init__(self, parent=None):
        """
        Khởi tạo Extension: load settings, đăng ký menu item.
        Chạy trên Main thread khi Cura khởi động.
        """
        QObject.__init__(self, parent)
        Extension.__init__(self)

        # Load thông số từ file (hoặc dùng mặc định)
        self._settings = _load_settings()

        # Trạng thái tiến độ cho QML
        self._progress_value = 0.0      # 0-100
        self._status_text = "Sẵn sàng"
        self._is_running = False

        # Tham chiếu đến Job đang chạy và dialog QML
        self._job = None
        self._dialog = None

        # Đăng ký menu item trong Extensions menu
        self.setMenuName("Mesh Tree Support")
        self.addMenuItem("Cài đặt và Sinh Support", self._show_dialog)

        Logger.log("i", "MeshTreeSupport Extension da khoi tao (settings loaded)")

    # ==========================================================================
    # PYQT PROPERTIES - để QML binding reactive
    # ==========================================================================

    @pyqtProperty(float, notify=progressChanged)
    def progressValue(self):
        """Tiến độ hiện tại (0-100), QML ProgressBar bind vào đây."""
        return self._progress_value

    @pyqtProperty(str, notify=statusTextChanged)
    def statusText(self):
        """Mô tả trạng thái hiện tại, QML Label bind vào đây."""
        return self._status_text

    @pyqtProperty(bool, notify=isRunningChanged)
    def isRunning(self):
        """True nếu Job đang chạy, QML dùng để disable/enable nút."""
        return self._is_running

    # ==========================================================================
    # PYQT SLOTS - QML gọi các hàm này
    # ==========================================================================

    @pyqtSlot(str, result=float)
    def getSetting(self, key):
        """
        QML gọi để lấy giá trị setting theo key.
        Luôn trả về float (QML tự format bằng .toFixed()).
        """
        return float(self._settings.get(key, 0))

    @pyqtSlot(str, float)
    def updateSetting(self, key, value):
        """
        QML gọi khi người dùng thay đổi 1 setting.
        Tự động lưu ra file JSON.
        """
        if key not in _DEFAULT_SETTINGS:
            return
        if key in _INT_SETTINGS:
            self._settings[key] = int(value)
        else:
            self._settings[key] = float(value)
        _save_settings(self._settings)
        self.settingsChanged.emit()

    @pyqtSlot()
    def resetSettings(self):
        """
        QML gọi khi nhấn nút "Mặc định".
        Khôi phục tất cả settings về giá trị ban đầu, lưu file, cập nhật UI.
        """
        self._settings = _DEFAULT_SETTINGS.copy()
        _save_settings(self._settings)
        self.settingsChanged.emit()
        Logger.log("i", "MeshTreeSupport: Da khoi phuc settings mac dinh")

    @pyqtSlot()
    def startGeneration(self):
        """
        QML gọi khi nhấn nút "Bắt đầu".
        Kiểm tra không chạy trùng, rồi bắt đầu pipeline.
        """
        if self._is_running:
            return
        self._start_generation()

    @pyqtSlot()
    def cancelGeneration(self):
        """
        QML gọi khi nhấn nút "Huỷ".
        Gửi yêu cầu huỷ đến Job đang chạy (cooperative cancellation).
        """
        if self._job is not None and self._is_running:
            self._job.requestCancel()
            self._status_text = "Đang huỷ..."
            self.statusTextChanged.emit()

    # ==========================================================================
    # QUẢN LÝ DIALOG QML
    # ==========================================================================

    def _show_dialog(self):
        """
        Hiển thị dialog cài đặt QML.
        Tạo dialog lần đầu (lazy init), sau đó tái sử dụng.
        Truyền self (QObject) làm "manager" cho QML truy cập.
        """
        if self._dialog is None:
            qml_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "qml", "SettingsDialog.qml"
            )
            # Truyền mainWindow để QML dùng làm transientParent (cửa sổ con của Cura)
            main_window = CuraApplication.getInstance().getMainWindow()
            self._dialog = CuraApplication.getInstance().createQmlComponent(
                qml_path, {"manager": self, "mainWindow": main_window}
            )
        if self._dialog:
            self._dialog.show()
        else:
            Logger.log("e", "MeshTreeSupport: Khong the tao dialog QML!")

    # ==========================================================================
    # LOGIC SINH CÂY SUPPORT
    # ==========================================================================

    def _start_generation(self):
        """
        Trích xuất mesh từ scene → tạo Job → khởi chạy nền.
        Chạy trên: Main thread
        """
        Logger.log("i", "MeshTreeSupport: Bat dau sinh cay support...")

        # Xoá cây support cũ nếu có
        scene = CuraApplication.getInstance().getController().getScene()
        for node in DepthFirstIterator(scene.getRoot()):
            if node.getName() == "MeshTreeSupport":
                op = RemoveSceneNodeOperation(node)
                op.push()
                Logger.log("i", "MeshTreeSupport: Da xoa cay support cu.")
                break

        # Cập nhật UI: đang chạy
        self._is_running = True
        self._progress_value = 0
        self._status_text = "Đang trích xuất mesh..."
        self.isRunningChanged.emit()
        self.progressChanged.emit()
        self.statusTextChanged.emit()

        # --- Thu thập mesh từ scene ---
        scene = CuraApplication.getInstance().getController().getScene()
        all_vertices = []
        all_faces = []
        vertex_offset = 0

        for node in DepthFirstIterator(scene.getRoot()):
            # Chỉ xử lý node sliceable (mesh in được)
            if not node.callDecoration("isSliceable"):
                continue

            # Bỏ qua support mesh đã có
            per_mesh_stack = node.callDecoration("getStack")
            if per_mesh_stack:
                if per_mesh_stack.getProperty("support_mesh", "value"):
                    continue

            mesh_data = node.getMeshData()
            if mesh_data is None:
                continue

            local_verts = mesh_data.getVertices()
            if local_verts is None or len(local_verts) == 0:
                continue

            # Chuyển sang hệ tọa độ thế giới (world coordinates)
            transform_matrix = node.getWorldTransformation().getData()
            num_verts = len(local_verts)
            homo_verts = np.ones((num_verts, 4), dtype=np.float64)
            homo_verts[:, :3] = local_verts
            world_verts = (transform_matrix @ homo_verts.T).T[:, :3]

            # Chuyển Y-up (Cura/OpenGL) → Z-up (3D printing)
            world_verts_zup = world_verts.copy()
            world_verts_zup[:, 1] = world_verts[:, 2]   # Y_new = Z_old
            world_verts_zup[:, 2] = world_verts[:, 1]   # Z_new = Y_old

            # Lấy face indices
            indices = mesh_data.getIndices()
            if indices is not None:
                local_faces = indices.copy()
            else:
                num_triangles = num_verts // 3
                local_faces = np.arange(num_triangles * 3, dtype=np.int32).reshape(-1, 3)

            offset_faces = local_faces + vertex_offset
            all_vertices.append(world_verts_zup)
            all_faces.append(offset_faces)
            vertex_offset += num_verts

        # Kiểm tra có mesh không
        if not all_vertices:
            Logger.log("w", "MeshTreeSupport: Khong tim thay mesh nao tren ban in!")
            self._is_running = False
            self._status_text = "Không tìm thấy mesh nào!"
            self.isRunningChanged.emit()
            self.statusTextChanged.emit()
            return

        combined_verts = np.vstack(all_vertices).astype(np.float64)
        combined_faces = np.vstack(all_faces).astype(np.int32)

        Logger.log("i", "MeshTreeSupport: Mesh gop co %d dinh, %d tam giac",
                   len(combined_verts), len(combined_faces))

        # --- Tạo và khởi chạy Job ---
        # Truyền bản sao settings để Job không bị ảnh hưởng nếu user thay đổi settings
        self._job = MeshTreeSupportJob(combined_verts, combined_faces, self._settings.copy())

        # Kết nối signals từ Job
        self._job.progress.connect(self._on_progress)
        self._job.finished.connect(self._on_job_finished)

        # Khởi chạy trên worker thread
        self._job.start()

        Logger.log("i", "MeshTreeSupport: Job da duoc khoi chay tren worker thread")

    # ==========================================================================
    # XỬ LÝ TIẾN ĐỘ VÀ KẾT QUẢ TỪ JOB
    # ==========================================================================

    def _on_progress(self, value):
        """
        Callback từ Job.progress signal (có thể từ worker thread).
        Dùng callLater() để chuyển về main thread an toàn.
        """
        Application.getInstance().callLater(lambda v=value: self._update_progress_ui(v))

    def _update_progress_ui(self, value):
        """
        Cập nhật progress + status text trên main thread.
        Suy ra bước hiện tại từ giá trị progress.
        """
        self._progress_value = value

        # Suy ra trạng thái từ giá trị tiến độ
        if value <= 20:
            self._status_text = "Bước 1/2: Phát hiện vùng lơ lửng..."
        elif value < 100:
            self._status_text = "Bước 2/2: Tạo vỏ overhang..."
        else:
            self._status_text = "Hoàn tất!"

        self.progressChanged.emit()
        self.statusTextChanged.emit()

    def _on_job_finished(self, job):
        """
        Callback khi Job hoàn thành (từ worker thread).
        Chuyển về main thread bằng callLater().
        """
        Application.getInstance().callLater(self._handle_job_finished, job)

    def _handle_job_finished(self, job):
        """
        Xử lý kết quả Job trên main thread.
        Thêm mesh support vào scene hoặc báo lỗi.
        """
        self._is_running = False
        self.isRunningChanged.emit()

        # Kiểm tra nếu Job bị huỷ
        if job.isCancelled():
            self._status_text = "Đã huỷ."
            self._progress_value = 0
            self.progressChanged.emit()
            self.statusTextChanged.emit()
            Logger.log("i", "MeshTreeSupport: Job da bi huy boi nguoi dung.")
            return

        mesh_data = job.getResultMeshData()
        if mesh_data is None:
            self._status_text = "Không tìm thấy vùng lơ lửng hoặc xảy ra lỗi."
            self._progress_value = 0
            self.progressChanged.emit()
            self.statusTextChanged.emit()
            Logger.log("w", "MeshTreeSupport: Job hoan thanh nhung khong co mesh.")
            return

        # Thêm mesh support vào scene
        self._add_support_to_scene(mesh_data)

        vertex_count = mesh_data.getVertexCount() if mesh_data else 0
        self._progress_value = 100
        self._status_text = "Hoàn tất! (%d đỉnh)" % vertex_count
        self.progressChanged.emit()
        self.statusTextChanged.emit()

    def _add_support_to_scene(self, mesh_data):
        """
        Thêm mesh cây support vào scene Cura dưới dạng support mesh.
        Chuyển vertices Z-up → Y-up, tạo CuraSceneNode, đánh dấu support_mesh.
        Chạy trên: Main thread
        """

        # Chuyển vertices Z-up → Y-up (Cura)
        original_verts = mesh_data.getVertices()
        if original_verts is None or len(original_verts) == 0:
            return

        converted_verts = original_verts.copy()
        converted_verts[:, 1] = original_verts[:, 2]   # Y_cura = Z_zup
        converted_verts[:, 2] = original_verts[:, 1]   # Z_cura = Y_zup

        # Cắt cụt phần dưới sàn: clamp Y >= 0 (Y = chiều cao trong Cura Y-up)
        converted_verts[:, 1] = np.maximum(converted_verts[:, 1], 0.0)

        # Chuyển normals tương tự
        original_normals = mesh_data.getNormals()
        converted_normals = None
        if original_normals is not None and len(original_normals) > 0:
            converted_normals = original_normals.copy()
            converted_normals[:, 1] = original_normals[:, 2]
            converted_normals[:, 2] = original_normals[:, 1]

        # Giữ indices từ mesh gốc hoặc tạo mới cho triangle soup
        original_indices = mesh_data.getIndices()
        if original_indices is None:
            original_indices = np.arange(len(converted_verts), dtype=np.int32).reshape(-1, 3)

        cura_mesh_data = MeshData(
            vertices=converted_verts.astype(np.float32),
            normals=converted_normals.astype(np.float32) if converted_normals is not None else None,
            indices=original_indices
        )

        # Tạo CuraSceneNode
        support_node = CuraSceneNode()
        support_node.setName("MeshTreeSupport")
        support_node.setSelectable(True)
        support_node.setMeshData(cura_mesh_data)

        # Không cho BuildVolume đánh dấu outside_buildarea
        # (nhánh support có thể vượt nhẹ ra ngoài build volume,
        #  nhưng CuraEngine tự clip — không cần skip toàn bộ mesh)
        support_node.setOutsideBuildArea = lambda new_value: None

        active_build_plate = CuraApplication.getInstance().getMultiBuildPlateModel().activeBuildPlate
        support_node.addDecorator(BuildPlateDecorator(active_build_plate))
        support_node.addDecorator(SliceableObjectDecorator())

        # ConvexHullDecorator cần thiết để Cura tính vùng in và gửi mesh đến CuraEngine
        from cura.Scene.ConvexHullDecorator import ConvexHullDecorator
        support_node.addDecorator(ConvexHullDecorator())

        # Thêm vào scene
        scene = CuraApplication.getInstance().getController().getScene()
        op = AddSceneNodeOperation(support_node, scene.getRoot())
        op.push()

        Logger.log("i", "MeshTreeSupport: Da them mesh cay support vao scene! (%d dinh)",
                   cura_mesh_data.getVertexCount())
