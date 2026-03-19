import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.3
import UM 1.5 as UM
import Cura 1.0 as Cura

Window
{
    id: panel
    title: "Overhang Support Visualizer – Phát hiện vùng Overhang"

    width: 460
    height: 420
    minimumWidth: 380
    minimumHeight: 360

    modality: Qt.NonModal
    flags: Qt.Window | Qt.WindowTitleHint | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint

    color: UM.Theme.getColor("main_background")

    ColumnLayout
    {
        anchors.fill: parent
        anchors.margins: UM.Theme.getSize("default_margin").width
        spacing: UM.Theme.getSize("default_margin").height

        // ── Tiêu đề nhóm cài đặt ──────────────────────────────────────
        UM.Label
        {
            text: "⚙  Cài đặt phát hiện"
            font.bold: true
        }

        // ── Lưới cài đặt ──────────────────────────────────────────────
        GridLayout
        {
            columns: 3
            Layout.fillWidth: true
            columnSpacing: UM.Theme.getSize("default_margin").width
            rowSpacing: UM.Theme.getSize("default_margin").height

            // ── Góc Overhang ──────────────────────────────────────────
            ColumnLayout
            {
                spacing: 2
                UM.Label { text: "Góc Overhang"; font.bold: true }
                UM.Label
                {
                    text: "Mặt có góc nghiêng lớn hơn\ngiá trị này sẽ bị coi là overhang\n(cần điểm chống đỡ)."
                    font.pixelSize: 10
                    color: UM.Theme.getColor("text_inactive")
                    wrapMode: Text.WordWrap
                }
            }
            SpinBox
            {
                id: angleSpinBox
                Layout.fillWidth: true
                from: 0; to: 90
                editable: true
                value: manager.overhangAngle
                onValueModified: manager.overhangAngle = value
                ToolTip.visible: hovered
                ToolTip.text: "Phạm vi: 0° – 90°\n45° là giá trị tiêu chuẩn cho hầu hết máy in."
            }
            UM.Label { text: "°" }

            // ── Khoảng cách điểm ──────────────────────────────────────
            ColumnLayout
            {
                spacing: 2
                UM.Label { text: "Khoảng cách điểm"; font.bold: true }
                UM.Label
                {
                    text: "Khoảng cách tối thiểu giữa\nhai điểm chống đỡ liền kề.\nGiá trị nhỏ → nhiều điểm hơn."
                    font.pixelSize: 10
                    color: UM.Theme.getColor("text_inactive")
                    wrapMode: Text.WordWrap
                }
            }
            SpinBox
            {
                id: spacingSpinBox
                Layout.fillWidth: true
                from: 1; to: 200
                editable: true
                value: manager.pointSpacing
                onValueModified: manager.pointSpacing = value
                ToolTip.visible: hovered
                ToolTip.text: "Phạm vi: 1 – 200 mm\nKhuyến nghị: 5 – 15 mm."
            }
            UM.Label { text: "mm" }

            // ── Đường kính điểm ───────────────────────────────────────
            ColumnLayout
            {
                spacing: 2
                UM.Label { text: "Đường kính điểm"; font.bold: true }
                UM.Label
                {
                    text: "Kích thước hình cầu hiển thị\ncho mỗi điểm chống đỡ\ntrên khung nhìn 3D."
                    font.pixelSize: 10
                    color: UM.Theme.getColor("text_inactive")
                    wrapMode: Text.WordWrap
                }
            }
            SpinBox
            {
                id: diameterSpinBox
                Layout.fillWidth: true
                from: 1; to: 50
                editable: true
                value: manager.pointDiameter
                onValueModified: manager.pointDiameter = value
                ToolTip.visible: hovered
                ToolTip.text: "Phạm vi: 1 – 50 mm\nChỉ ảnh hưởng hiển thị, không thay đổi bản in."
            }
            UM.Label { text: "mm" }
        }

        // ── Divider ───────────────────────────────────────────────────
        Rectangle
        {
            Layout.fillWidth: true
            height: 1
            color: UM.Theme.getColor("lining")
        }

        // ── Trạng thái ────────────────────────────────────────────────
        UM.Label
        {
            id: statusLabel
            Layout.fillWidth: true
            text: manager.statusMessage !== "" ? manager.statusMessage : "Nhấn \"Phát hiện & Hiển thị\" để bắt đầu quét."
            wrapMode: Text.WordWrap
            font.italic: true
            color: UM.Theme.getColor("text_inactive")
        }

        Item { Layout.fillHeight: true }

        // ── Nút thao tác ──────────────────────────────────────────────
        RowLayout
        {
            Layout.fillWidth: true
            spacing: UM.Theme.getSize("default_margin").width

            Cura.PrimaryButton
            {
                text: "Phát hiện & Hiển thị"
                Layout.fillWidth: true
                onClicked: manager.detectAndVisualize()
                ToolTip.visible: hovered
                ToolTip.text: "Quét toàn bộ object sẽ được in,\nphát hiện vùng overhang và\nhiển thị điểm chống đỡ trên 3D."
            }

            Cura.SecondaryButton
            {
                text: "Xoá điểm"
                onClicked: manager.clearSupportPoints()
                ToolTip.visible: hovered
                ToolTip.text: "Xoá toàn bộ điểm chống đỡ\nđang hiển thị trên khung nhìn 3D."
            }
        }
    }
}
