# Copyright (c) 2024 tqk2811
# MeshTreeTipAdjuster - Điều chỉnh phần ngọn (Tips) của Mesh Tree Support
# Dùng làm Post-Processing Script trong UltiMaker Cura
#
# Cách cài đặt:
#   Sao chép file này vào thư mục:
#   Windows: %appdata%\cura\<version>\scripts\MeshTreeTipAdjuster.py
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
    - Phát hiện các nhóm lớp SUPPORT-INTERFACE liên tiếp
    - Chỉ áp dụng M221 cho top N lớp trên cùng của mỗi nhóm (gần model nhất)
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
                    "default_value": 100,
                    "minimum_value": 10,
                    "maximum_value": 200
                },
                "tip_layer_count": {
                    "label": "Số lớp ngọn áp dụng",
                    "description": "Số lớp trên cùng của mỗi vùng support-interface sẽ được áp dụng flow rate. Ví dụ: 3 = chỉ 3 lớp trên cùng nhận flow thấp. 0 = áp dụng tất cả lớp SUPPORT-INTERFACE.",
                    "type": "int",
                    "default_value": 3,
                    "minimum_value": 0,
                    "maximum_value": 50
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
        # Gom các lớp SUPPORT-INTERFACE liên tiếp thành từng nhóm (mỗi nhóm = 1 vùng tip)
        # Trong mỗi nhóm chỉ lấy top N lớp trên cùng (index cao nhất = gần model nhất)
        # tip_layer_count = 0 → áp dụng toàn bộ nhóm
        tip_layer_indices: set[int] = set()

        groups: list[list[int]] = []
        current_group: list[int] = []
        for i, has_interface in enumerate(layer_has_interface):
            if has_interface:
                current_group.append(i)
            else:
                if current_group:
                    groups.append(current_group)
                    current_group = []
        if current_group:
            groups.append(current_group)

        for group in groups:
            # group đã sorted tăng dần; top N = cuối group (index lớn = gần model)
            selected = group if tip_layer_count == 0 else group[-tip_layer_count:]
            tip_layer_indices.update(selected)

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
