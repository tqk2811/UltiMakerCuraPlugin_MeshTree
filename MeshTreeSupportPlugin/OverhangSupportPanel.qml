import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.3
import UM 1.5 as UM
import Cura 1.0 as Cura

Window
{
    id: panel
    title: "Overhang Support Visualizer – Phát hiện vùng Overhang"

    width: 380
    height: 280
    minimumWidth: 320
    minimumHeight: 240

    modality: Qt.NonModal
    flags: Qt.Window | Qt.WindowSystemMenuHint | Qt.WindowTitleHint | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint

    color: UM.Theme.getColor("main_background")

    // Label có tooltip dùng MouseArea (UM.Label không forward ToolTip attached)
    component LabelWithTip: Item
    {
        property alias text: lbl.text
        property string tip: ""
        implicitWidth: lbl.implicitWidth
        implicitHeight: lbl.implicitHeight

        UM.Label { id: lbl; anchors.fill: parent }
        MouseArea
        {
            anchors.fill: parent
            hoverEnabled: true
            ToolTip.visible: containsMouse && parent.tip !== ""
            ToolTip.delay: 400
            ToolTip.text: parent.tip
        }
    }

    ColumnLayout
    {
        anchors.fill: parent
        anchors.margins: UM.Theme.getSize("default_margin").width
        spacing: UM.Theme.getSize("default_margin").height

        // ── Tiêu đề ───────────────────────────────────────────────────
        UM.Label { text: "⚙  Cài đặt phát hiện"; font.bold: true }

        // ── Lưới cài đặt ──────────────────────────────────────────────
        GridLayout
        {
            columns: 3
            Layout.fillWidth: true
            columnSpacing: UM.Theme.getSize("default_margin").width
            rowSpacing: UM.Theme.getSize("default_margin").height

            // Góc Overhang
            LabelWithTip
            {
                text: "Góc Overhang"
                tip: "Mặt có góc nghiêng lớn hơn giá trị này sẽ bị coi là overhang (cần điểm chống đỡ).\nPhạm vi: 0° – 90° | Khuyến nghị: 45°"
            }
            SpinBox
            {
                id: angleSpinBox
                Layout.fillWidth: true
                from: 0; to: 90
                editable: true
                value: manager.overhangAngle
                onValueModified: manager.overhangAngle = value
            }
            UM.Label { text: "°" }

            // Khoảng cách điểm
            LabelWithTip
            {
                text: "Khoảng cách điểm"
                tip: "Khoảng cách tối thiểu giữa hai điểm chống đỡ liền kề.\nGiá trị nhỏ → nhiều điểm hơn.\nPhạm vi: 0.01 – 200.00 mm | Khuyến nghị: 5 – 15 mm"
            }
            SpinBox
            {
                id: spacingSpinBox
                Layout.fillWidth: true
                from: 1; to: 20000
                stepSize: 10        // bước 0.10 mm
                editable: true
                value: Math.round(manager.pointSpacing * 100)
                onValueModified: manager.pointSpacing = value / 100.0
                textFromValue: function(v) { return (v / 100.0).toFixed(2) }
                valueFromText: function(t) { return Math.round(parseFloat(t) * 100) }
            }
            UM.Label { text: "mm" }

            // Đường kính điểm
            LabelWithTip
            {
                text: "Đường kính điểm"
                tip: "Kích thước hình cầu hiển thị cho mỗi điểm chống đỡ trên khung nhìn 3D.\nChỉ ảnh hưởng hiển thị, không thay đổi bản in.\nPhạm vi: 0.01 – 50.00 mm"
            }
            SpinBox
            {
                id: diameterSpinBox
                Layout.fillWidth: true
                from: 1; to: 5000
                stepSize: 10        // bước 0.10 mm
                editable: true
                value: Math.round(manager.pointDiameter * 100)
                onValueModified: manager.pointDiameter = value / 100.0
                textFromValue: function(v) { return (v / 100.0).toFixed(2) }
                valueFromText: function(t) { return Math.round(parseFloat(t) * 100) }
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
            Layout.fillWidth: true
            text: manager.statusMessage !== "" ? manager.statusMessage
                                               : "Nhấn \"Phát hiện & Hiển thị\" để bắt đầu quét."
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
                ToolTip.delay: 400
                ToolTip.text: "Quét toàn bộ object sẽ được in, phát hiện vùng overhang\nvà hiển thị điểm chống đỡ trên khung nhìn 3D."
            }

            Cura.SecondaryButton
            {
                text: "Xoá điểm"
                onClicked: manager.clearSupportPoints()
                ToolTip.visible: hovered
                ToolTip.delay: 400
                ToolTip.text: "Xoá toàn bộ điểm chống đỡ đang hiển thị."
            }
        }
    }
}
