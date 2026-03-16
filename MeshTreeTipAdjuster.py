# Copyright (c) 2024 tqk2811
# MeshTreeTipAdjuster - Điều chỉnh phần ngọn (Tips) của Mesh Tree Support
# Dùng làm Post-Processing Script trong UltiMaker Cura
#
# Cách cài đặt:
#   Sao chép file này vào thư mục:
#   Windows: C:\Program Files\UltiMaker Cura <version>\plugins\PostProcessingPlugin\scripts\
#   macOS:   /Applications/UltiMaker Cura.app/Contents/MacOS/plugins/PostProcessingPlugin/scripts/
#   Linux:   ~/.local/share/cura/<version>/scripts/   hoặc   /usr/share/cura/plugins/PostProcessingPlugin/scripts/
#
# Sau khi cài, vào Cura: Extensions > Post Processing > Modify G-Code > Add a script > Mesh Tree Tip Adjuster

try:
    from ..Script import Script  # Khi đặt trong PostProcessingPlugin/scripts/
except (ImportError, SystemError):
    from Script import Script  # Khi đặt trong thư mục user scripts


class MeshTreeTipAdjuster(Script):
    """
    Điều chỉnh lượng nhựa (flow rate) và số lớp cho phần ngọn (tips)
    của Tree Support trong UltiMaker Cura.

    Cách hoạt động:
    - Phát hiện các lớp ngọn (SUPPORT-INTERFACE) và N lớp phía trên support bên dưới
    - Chèn lệnh M221 để thay đổi lượng nhựa khi in phần ngọn
    - Khôi phục lượng nhựa bình thường sau khi kết thúc phần ngọn
    """

    def getSettingDataString(self) -> str:
        return """{
            "name": "Mesh Tree Tip Adjuster",
            "key": "MeshTreeTipAdjuster",
            "metadata": {},
            "version": 2,
            "settings": {
                "tip_flow_rate": {
                    "label": "Tip Flow Rate (%)",
                    "description": "Lượng nhựa phun ra cho phần ngọn (tips). 100 = bình thường, nhỏ hơn = ít nhựa hơn, lớn hơn = nhiều nhựa hơn.",
                    "type": "int",
                    "unit": "%",
                    "default_value": 85,
                    "minimum_value": 10,
                    "maximum_value": 200
                },
                "tip_layer_count": {
                    "label": "Tip Layer Count (Số lớp ngọn)",
                    "description": "Số lớp phần ngọn cần điều chỉnh. 0 = chỉ áp dụng cho lớp SUPPORT-INTERFACE. Tăng lên để áp dụng thêm N lớp support bên dưới interface.",
                    "type": "int",
                    "default_value": 2,
                    "minimum_value": 0,
                    "maximum_value": 20
                },
                "restore_flow": {
                    "label": "Restore Flow After Tips",
                    "description": "Khôi phục lượng nhựa về bình thường (M221 S100) sau khi in xong phần ngọn.",
                    "type": "bool",
                    "default_value": true
                },
                "verbose": {
                    "label": "Add Comments to G-Code",
                    "description": "Thêm chú thích vào G-code để dễ kiểm tra (ví dụ: ; [TipAdjuster] flow 85%).",
                    "type": "bool",
                    "default_value": true
                }
            }
        }"""

    def execute(self, data: list) -> list:
        """
        data: list[str] — mỗi phần tử là một layer block (chuỗi G-code của một lớp).
        data[0] = startup G-code, data[-1] = ending G-code.
        Mỗi layer block chứa nhiều dòng G-code, phân cách bằng '\\n'.
        """
        tip_flow: int = self.getSettingValueByKey("tip_flow_rate")
        tip_layer_count: int = self.getSettingValueByKey("tip_layer_count")
        restore_flow: bool = self.getSettingValueByKey("restore_flow")
        verbose: bool = self.getSettingValueByKey("verbose")

        tag = " ; [MeshTreeTipAdjuster]" if verbose else ""

        # ── Phase 1: Quét toàn bộ G-code để xác định lớp nào chứa support ──────
        # Mỗi phần tử: True nếu layer đó có SUPPORT, SUPPORT-INTERFACE
        layer_has_support: list[bool] = []
        layer_has_interface: list[bool] = []

        for layer in data:
            layer_has_interface.append(";TYPE:SUPPORT-INTERFACE" in layer)
            # Tính có SUPPORT thuần (không phải interface)
            layer_has_support.append(";TYPE:SUPPORT" in layer)

        # ── Phase 2: Xác định tập hợp chỉ số lớp là "ngọn" (tip layers) ────────
        # Tip = lớp SUPPORT-INTERFACE + tip_layer_count lớp support bên dưới
        tip_layer_indices: set[int] = set()

        for i, has_interface in enumerate(layer_has_interface):
            if not has_interface:
                continue
            tip_layer_indices.add(i)
            # Mở rộng thêm tip_layer_count lớp phía dưới (index nhỏ hơn = in trước)
            for offset in range(1, tip_layer_count + 1):
                prev = i - offset
                if prev >= 0 and layer_has_support[prev]:
                    tip_layer_indices.add(prev)

        if not tip_layer_indices:
            # Không tìm thấy support interface → trả về nguyên
            return data

        # ── Phase 3: Chèn lệnh M221 vào các lớp ngọn ───────────────────────────
        result: list[str] = []
        max_tip_index = max(tip_layer_indices)

        for layer_index, layer in enumerate(data):
            if layer_index not in tip_layer_indices:
                result.append(layer)
                continue

            lines = layer.split("\n")
            new_lines: list[str] = []
            in_tip_section = False

            for line in lines:
                stripped = line.strip()

                # Phát hiện bắt đầu vùng tip (SUPPORT-INTERFACE hoặc SUPPORT trong tip layer)
                is_support_type = stripped in (
                    ";TYPE:SUPPORT",
                    ";TYPE:SUPPORT-INTERFACE",
                )
                if is_support_type:
                    new_lines.append(line)
                    if not in_tip_section:
                        comment = f"tip flow {tip_flow}%" if verbose else ""
                        new_lines.append(
                            f"M221 S{tip_flow}{tag} {comment}".rstrip()
                        )
                        in_tip_section = True
                    continue

                # Phát hiện kết thúc vùng tip (chuyển sang loại đường in khác)
                if in_tip_section and stripped.startswith(";TYPE:"):
                    if restore_flow:
                        new_lines.append(
                            f"M221 S100{tag} restore flow".rstrip() if verbose
                            else "M221 S100"
                        )
                    in_tip_section = False

                new_lines.append(line)

            # Nếu vẫn còn trong vùng tip khi hết layer cuối cùng
            if in_tip_section and restore_flow and layer_index == max_tip_index:
                new_lines.append(
                    f"M221 S100{tag} restore flow end".rstrip() if verbose
                    else "M221 S100"
                )

            result.append("\n".join(new_lines))

        return result
