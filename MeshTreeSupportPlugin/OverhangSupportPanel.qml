import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.3
import UM 1.5 as UM
import Cura 1.0 as Cura

Window
{
    id: panel
    title: "Overhang Support Visualizer – Phát hiện vùng Overhang"

    width: 500
    height: 760
    minimumWidth: 420
    minimumHeight: 660

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

    ScrollView
    {
        anchors.fill: parent
        contentWidth: availableWidth
        clip: true

        ColumnLayout
        {
            width: parent.width
            anchors.margins: UM.Theme.getSize("default_margin").width
            spacing: UM.Theme.getSize("default_margin").height

            // padding top
            Item { height: UM.Theme.getSize("default_margin").height }

            // ══ Phần 1: Xác định Contact Points ══════════════════════════════
            UM.Label { text: "⚙  Xác định Contact Points"; font.bold: true
                       leftPadding: UM.Theme.getSize("default_margin").width }

            GridLayout
            {
                columns: 3
                Layout.fillWidth: true
                Layout.leftMargin:  UM.Theme.getSize("default_margin").width
                Layout.rightMargin: UM.Theme.getSize("default_margin").width
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
                    stepSize: 1
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
                    stepSize: 1
                    editable: true
                    value: Math.round(manager.pointDiameter * 100)
                    onValueModified: manager.pointDiameter = value / 100.0
                    textFromValue: function(v) { return (v / 100.0).toFixed(2) }
                    valueFromText: function(t) { return Math.round(parseFloat(t) * 100) }
                }
                UM.Label { text: "mm" }

                // Khoảng cách tới object
                LabelWithTip
                {
                    text: "Khoảng cách tới object"
                    tip: "Điểm sẽ bị dịch xuống dưới theo trục Z một khoảng bằng giá trị này.\n0 mm = điểm nằm sát mặt overhang.\nPhạm vi: 0.00 – 100.00 mm"
                }
                SpinBox
                {
                    id: offsetSpinBox
                    Layout.fillWidth: true
                    from: 0; to: 10000
                    stepSize: 1
                    editable: true
                    value: Math.round(manager.pointOffset * 100)
                    onValueModified: manager.pointOffset = value / 100.0
                    textFromValue: function(v) { return (v / 100.0).toFixed(2) }
                    valueFromText: function(t) { return Math.round(parseFloat(t) * 100) }
                }
                UM.Label { text: "mm" }
            }

            // Hiển thị vùng overhang
            CheckBox
            {
                id: overlayCheckBox
                text: "Hiển thị vùng overhang"
                checked: manager.showOverlay
                onCheckedChanged: manager.showOverlay = checked
                Layout.leftMargin: UM.Theme.getSize("default_margin").width
                ToolTip.visible: hovered
                ToolTip.delay: 400
                ToolTip.text: "Tô màu riêng các mặt tam giác được xác định là vùng overhang\ntrên khung nhìn 3D. Không ảnh hưởng đến bản in."
            }

            // Nút detect
            RowLayout
            {
                Layout.fillWidth: true
                Layout.leftMargin:  UM.Theme.getSize("default_margin").width
                Layout.rightMargin: UM.Theme.getSize("default_margin").width
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

            // ── Divider ────────────────────────────────────────────────────────
            Rectangle
            {
                Layout.fillWidth: true
                Layout.leftMargin:  UM.Theme.getSize("default_margin").width
                Layout.rightMargin: UM.Theme.getSize("default_margin").width
                height: 1
                color: UM.Theme.getColor("lining")
            }

            // ══ Phần 2: Cây chống đỡ ══════════════════════════════════════════
            UM.Label { text: "🌲  Cây chống đỡ"; font.bold: true
                       leftPadding: UM.Theme.getSize("default_margin").width }

            GridLayout
            {
                columns: 3
                Layout.fillWidth: true
                Layout.leftMargin:  UM.Theme.getSize("default_margin").width
                Layout.rightMargin: UM.Theme.getSize("default_margin").width
                columnSpacing: UM.Theme.getSize("default_margin").width
                rowSpacing: UM.Theme.getSize("default_margin").height

                // Góc nhánh
                LabelWithTip
                {
                    text: "Góc nhánh"
                    tip: "Góc nghiêng từ trục đứng khi hai nhánh hội tụ về nhau.\nNhỏ hơn = nhánh gần thẳng đứng, hội tụ chậm.\nLớn hơn = nhánh nghiêng nhiều, hội tụ nhanh.\nPhạm vi: 1° – 89° | Khuyến nghị: 20° – 45°"
                }
                SpinBox
                {
                    id: treeAngleSpinBox
                    Layout.fillWidth: true
                    from: 1; to: 89
                    editable: true
                    value: manager.treeBranchAngle
                    onValueModified: manager.treeBranchAngle = value
                }
                UM.Label { text: "°" }

                // Khoảng cách ghép cặp cơ bản
                LabelWithTip
                {
                    text: "K.cách ghép cặp cơ bản"
                    tip: "Khoảng cách XZ tối đa giữa hai nhánh cấp 0 để được ghép cặp.\nKhoảng cách thực tế = giá trị này + Thêm/cấp × cấp lớn nhất.\nPhạm vi: 0.01 – 500.00 mm | Khuyến nghị: 15 – 30 mm"
                }
                SpinBox
                {
                    id: treeBaseDistSpinBox
                    Layout.fillWidth: true
                    from: 1; to: 50000
                    stepSize: 1
                    editable: true
                    value: Math.round(manager.treeBaseDist * 100)
                    onValueModified: manager.treeBaseDist = value / 100.0
                    textFromValue: function(v) { return (v / 100.0).toFixed(2) }
                    valueFromText: function(t) { return Math.round(parseFloat(t) * 100) }
                }
                UM.Label { text: "mm" }

                // Khoảng cách thêm mỗi cấp
                LabelWithTip
                {
                    text: "Thêm/cấp"
                    tip: "Khoảng cách ghép cặp tăng thêm cho mỗi cấp (dùng cấp lớn hơn khi ghép cặp khác cấp).\nVí dụ: cấp 0+0=20mm, cấp 1=25mm, cấp 2=30mm.\nPhạm vi: 0.00 – 100.00 mm | Khuyến nghị: 3 – 10 mm"
                }
                SpinBox
                {
                    id: treeDistPerLvlSpinBox
                    Layout.fillWidth: true
                    from: 0; to: 10000
                    stepSize: 1
                    editable: true
                    value: Math.round(manager.treeDistPerLevel * 100)
                    onValueModified: manager.treeDistPerLevel = value / 100.0
                    textFromValue: function(v) { return (v / 100.0).toFixed(2) }
                    valueFromText: function(t) { return Math.round(parseFloat(t) * 100) }
                }
                UM.Label { text: "mm" }

                // Khoảng cách tối thiểu tới vật thể
                LabelWithTip
                {
                    text: "K.cách tối thiểu tới vật"
                    tip: "Đường đi chéo của nhánh phải cách bề mặt vật thể ít nhất giá trị này.\nNếu không đủ khoảng cách, cặp bị từ chối và nhánh đi thẳng xuống.\nĐặt 0 để tắt kiểm tra.\nPhạm vi: 0.00 – 50.00 mm | Mặc định: 2 mm"
                }
                SpinBox
                {
                    id: treeClearanceSpinBox
                    Layout.fillWidth: true
                    from: 0; to: 5000
                    stepSize: 1
                    editable: true
                    value: Math.round(manager.treeClearance * 100)
                    onValueModified: manager.treeClearance = value / 100.0
                    textFromValue: function(v) { return (v / 100.0).toFixed(2) }
                    valueFromText: function(t) { return Math.round(parseFloat(t) * 100) }
                }
                UM.Label { text: "mm" }

                // Hệ số tăng kích thước
                LabelWithTip
                {
                    text: "Hệ số tăng kích thước"
                    tip: "Đường kính nhánh tăng dần khi xuống thấp hơn contact point.\nCông thức: Ø_điểm + (Y_contact_cao_nhất − Y_hiện_tại) × Ø_điểm × hệ_số\nVí dụ 1%: mỗi 10 mm xuống thêm, đường kính tăng thêm 10% × Ø_điểm.\nPhạm vi: 0.00 – 100.00% | Khuyến nghị: 0.5 – 3%"
                }
                SpinBox
                {
                    id: treeGrowthSpinBox
                    Layout.fillWidth: true
                    from: 0; to: 10000
                    stepSize: 1
                    editable: true
                    value: Math.round(manager.treeGrowthPct * 100)
                    onValueModified: manager.treeGrowthPct = value / 100.0
                    textFromValue: function(v) { return (v / 100.0).toFixed(2) }
                    valueFromText: function(t) { return Math.round(parseFloat(t) * 100) }
                }
                UM.Label { text: "%" }

                // Bước mô phỏng
                LabelWithTip
                {
                    text: "Bước mô phỏng"
                    tip: "Độ phân giải của vòng lặp mô phỏng (mm/bước).\nNhỏ hơn = chính xác hơn nhưng chậm hơn.\nPhạm vi: 0.10 – 10.00 mm | Khuyến nghị: 0.5 – 2 mm"
                }
                SpinBox
                {
                    id: treeStepSpinBox
                    Layout.fillWidth: true
                    from: 10; to: 1000
                    stepSize: 1
                    editable: true
                    value: Math.round(manager.treeStepSize * 100)
                    onValueModified: manager.treeStepSize = value / 100.0
                    textFromValue: function(v) { return (v / 100.0).toFixed(2) }
                    valueFromText: function(t) { return Math.round(parseFloat(t) * 100) }
                }
                UM.Label { text: "mm" }

                // Đoạn thẳng sau gộp
                LabelWithTip
                {
                    text: "Thẳng sau gộp"
                    tip: "Sau khi hai nhánh hội tụ, nhánh gộp đi thẳng xuống bao nhiêu mm trước khi được phép bẻ góc tiếp.\nPhạm vi: 0 – 100 mm | Mặc định: 10 mm"
                }
                SpinBox
                {
                    id: treeMergeDropSpinBox
                    Layout.fillWidth: true
                    from: 0; to: 10000
                    stepSize: 1
                    editable: true
                    value: Math.round(manager.treeMergeDrop * 100)
                    onValueModified: manager.treeMergeDrop = value / 100.0
                    textFromValue: function(v) { return (v / 100.0).toFixed(2) }
                    valueFromText: function(t) { return Math.round(parseFloat(t) * 100) }
                }
                UM.Label { text: "mm" }

                // Số luồng
                LabelWithTip
                {
                    text: "Số luồng"
                    tip: "Số luồng CPU dùng để tính toán cây chống đỡ.\n0 = tự động (dùng toàn bộ CPU).\nPhạm vi: 0 – 64 | Mặc định: 0 (tự động)"
                }
                SpinBox
                {
                    id: treeThreadsSpinBox
                    Layout.fillWidth: true
                    from: 0; to: 64
                    stepSize: 1
                    editable: true
                    value: manager.treeThreadCount
                    onValueModified: manager.treeThreadCount = value
                    textFromValue: function(v) { return v === 0 ? "auto" : v.toString() }
                    valueFromText: function(t) { return t === "auto" ? 0 : parseInt(t) || 0 }
                }
                UM.Label { text: "luồng" }
            }

            // Nút tree
            RowLayout
            {
                Layout.fillWidth: true
                Layout.leftMargin:  UM.Theme.getSize("default_margin").width
                Layout.rightMargin: UM.Theme.getSize("default_margin").width
                spacing: UM.Theme.getSize("default_margin").width

                Cura.PrimaryButton
                {
                    text: manager.isGenerating ? "Đang tính toán…" : "Tạo cây chống đỡ"
                    Layout.fillWidth: true
                    enabled: !manager.isGenerating
                    onClicked: manager.generateTreeSupport()
                    ToolTip.visible: hovered
                    ToolTip.delay: 400
                    ToolTip.text: "Tạo cấu trúc cây chống đỡ từ các contact points đã phát hiện.\nHãy chạy 'Phát hiện & Hiển thị' trước."
                }

                Cura.SecondaryButton
                {
                    text: "Xoá cây"
                    enabled: !manager.isGenerating
                    onClicked: manager.clearTreeSupport()
                    ToolTip.visible: hovered
                    ToolTip.delay: 400
                    ToolTip.text: "Xoá toàn bộ cây chống đỡ đang hiển thị."
                }
            }

            // ── Divider ────────────────────────────────────────────────────────
            Rectangle
            {
                Layout.fillWidth: true
                Layout.leftMargin:  UM.Theme.getSize("default_margin").width
                Layout.rightMargin: UM.Theme.getSize("default_margin").width
                height: 1
                color: UM.Theme.getColor("lining")
            }

            // ── Trạng thái ─────────────────────────────────────────────────────
            Item
            {
                Layout.fillWidth: true
                Layout.leftMargin:  UM.Theme.getSize("default_margin").width
                Layout.rightMargin: UM.Theme.getSize("default_margin").width
                implicitHeight: statusLabel.implicitHeight

                property int dotPhase: 0
                property var dotTexts: ["   ", ".  ", ".. ", "..."]

                Timer
                {
                    id: dotTimer
                    interval: 400
                    repeat: true
                    running: manager.isGenerating
                    onTriggered: parent.dotPhase = (parent.dotPhase + 1) % 4
                    onRunningChanged: if (!running) parent.dotPhase = 0
                }

                UM.Label
                {
                    id: statusLabel
                    anchors { left: parent.left; right: parent.right }
                    text: {
                        var base = manager.statusMessage !== "" ? manager.statusMessage
                                                                : "Nhấn \"Phát hiện & Hiển thị\" để bắt đầu quét."
                        return manager.isGenerating ? base + parent.dotTexts[parent.dotPhase] : base
                    }
                    wrapMode: Text.WordWrap
                    font.italic: true
                    color: manager.isGenerating ? UM.Theme.getColor("text")
                                                : UM.Theme.getColor("text_inactive")
                }
            }

            // padding bottom
            Item { height: UM.Theme.getSize("default_margin").height }
        }
    }
}
