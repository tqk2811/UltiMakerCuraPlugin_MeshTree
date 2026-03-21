# ==============================================================================
# Tệp khởi tạo plugin MeshTreeSupport
# Đăng ký Extension với hệ thống plugin của Cura
# ==============================================================================

from . import MeshTreeSupport


def getMetaData():
    """Trả về metadata bổ sung cho plugin (không cần thiết ở đây)."""
    return {}


def register(app):
    """
    Đăng ký plugin với Cura.
    Trả về dict chứa instance Extension để Cura gắn vào menu Extensions.
    """
    return {"extension": MeshTreeSupport.MeshTreeSupport()}
