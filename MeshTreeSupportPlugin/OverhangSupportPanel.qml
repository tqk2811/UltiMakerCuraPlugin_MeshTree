// ============================================================
// OverhangSupportPanel.qml
// Giao diện người dùng của plugin Overhang Support Visualizer
// ============================================================
// File này định nghĩa cửa sổ panel điều khiển plugin.
// Được tạo bởi Python thông qua app.createQmlComponent(),
// nhận object `manager` (OverhangSupportPlugin Python) qua context property.
//
// Cấu trúc giao diện (từ trên xuống dưới):
//   Phần 1 – Xác định Contact Points:
//     • Góc overhang, khoảng cách điểm, đường kính điểm, offset
//     • Checkbox hiển thị overlay
//     • Nút "Phát hiện & Hiển thị" và "Xoá điểm"
//   ─── Divider ───
//   Phần 2 – Cây chống đỡ:
//     • Góc nhánh, k.cách ghép cặp, thêm/cấp, clearance, tăng kích thước
//     • Bước mô phỏng, thẳng sau gộp, số luồng
//     • Nút "Tạo cây chống đỡ" và "Xoá cây"
//   ─── Divider ───
//   Khu vực trạng thái: hiển thị statusMessage + animated dots khi đang tính
// ============================================================

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.3
import UM 1.5 as UM           // Ultimaker UI framework (Label, Theme, etc.)
import Cura 1.0 as Cura       // Cura-specific UI components (PrimaryButton, SecondaryButton)

Window
{
    id: panel
    title: "Overhang Support Visualizer – Phát hiện vùng Overhang"

    // Kích thước cửa sổ: 500×760, tối thiểu 420×660 để vừa với mọi màn hình
    width: 500
    height: 760
    minimumWidth: 420
    minimumHeight: 660

    // NonModal: cửa sổ không chặn thao tác với Cura khi đang mở
    modality: Qt.NonModal
    // WindowStaysOnTopHint: panel luôn hiển thị phía trên cửa sổ chính
    flags: Qt.Window | Qt.WindowSystemMenuHint | Qt.WindowTitleHint | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint

    color: UM.Theme.getColor("main_background")

    // ============================================================
    // Component LabelWithTip – Label tùy chỉnh có ToolTip
    // ============================================================
    // UM.Label không hỗ trợ ToolTip attached property (Qt limitation),
    // nên phải bọc trong Item + MouseArea để bắt sự kiện hover.
    // Sử dụng: LabelWithTip { text: "Label"; tip: "Tooltip content" }
    component LabelWithTip: Item
    {
        property alias text: lbl.text   // Chuyển tiếp text xuống UM.Label bên trong
        property string tip: ""         // Nội dung tooltip (rỗng = không hiện tooltip)
        implicitWidth: lbl.implicitWidth
        implicitHeight: lbl.implicitHeight

        UM.Label { id: lbl; anchors.fill: parent }
        MouseArea
        {
            anchors.fill: parent
            hoverEnabled: true
            // Chỉ hiện tooltip khi hover VÀ có nội dung tip
            ToolTip.visible: containsMouse && parent.tip !== ""
            ToolTip.delay: 400    // Chờ 400ms trước khi hiện tooltip
            ToolTip.text: parent.tip
        }
    }

    // ── ScrollView bao toàn bộ nội dung ──────────────────────────────────────
    // Cho phép cuộn khi cửa sổ nhỏ hơn nội dung
    ScrollView
    {
        anchors.fill: parent
        contentWidth: availableWidth   // Không scroll ngang, chỉ scroll dọc
        clip: true

        ColumnLayout
        {
            width: parent.width
            anchors.margins: UM.Theme.getSize("default_margin").width
            spacing: UM.Theme.getSize("default_margin").height

            // Padding trên cùng để nội dung không dính sát mép
            Item { height: UM.Theme.getSize("default_margin").height }

            // ══════════════════════════════════════════════════════════════════
            // PHẦN 1: XÁC ĐỊNH CONTACT POINTS
            // Các tham số cho bước phát hiện vùng overhang và đặt điểm chống đỡ
            // ══════════════════════════════════════════════════════════════════
            UM.Label { text: "⚙  Xác định Contact Points"; font.bold: true
                       leftPadding: UM.Theme.getSize("default_margin").width }

            // GridLayout 3 cột: [Label] [SpinBox] [Đơn vị]
            // Mỗi hàng = một tham số cấu hình
            GridLayout
            {
                columns: 3
                Layout.fillWidth: true
                Layout.leftMargin:  UM.Theme.getSize("default_margin").width
                Layout.rightMargin: UM.Theme.getSize("default_margin").width
                columnSpacing: UM.Theme.getSize("default_margin").width
                rowSpacing: UM.Theme.getSize("default_margin").height

                // ── Góc Overhang ──────────────────────────────────────────────
                // Ngưỡng góc để xác định mặt nào cần chống đỡ.
                // Binding hai chiều: QML → manager.overhangAngle → preferences
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
                    value: manager.overhangAngle              // Đọc từ Python property
                    onValueModified: manager.overhangAngle = value  // Ghi vào Python property
                }
                UM.Label { text: "°" }

                // ── Khoảng cách điểm ─────────────────────────────────────────
                // Khoảng cách Poisson-disk tối thiểu giữa hai contact point.
                // SpinBox lưu giá trị × 100 (integer) để tránh float rounding trong QML.
                // textFromValue và valueFromText chuyển đổi hiển thị sang mm.
                LabelWithTip
                {
                    text: "Khoảng cách điểm"
                    tip: "Khoảng cách tối thiểu giữa hai điểm chống đỡ liền kề.\nGiá trị nhỏ → nhiều điểm hơn.\nPhạm vi: 0.01 – 200.00 mm | Khuyến nghị: 5 – 15 mm"
                }
                SpinBox
                {
                    id: spacingSpinBox
                    Layout.fillWidth: true
                    from: 1; to: 20000            // Nội bộ: 0.01 – 200.00 mm × 100
                    stepSize: 1
                    editable: true
                    value: Math.round(manager.pointSpacing * 100)
                    onValueModified: manager.pointSpacing = value / 100.0
                    textFromValue: function(v) { return (v / 100.0).toFixed(2) }
                    valueFromText: function(t) { return Math.round(parseFloat(t) * 100) }
                }
                UM.Label { text: "mm" }

                // ── Đường kính điểm ──────────────────────────────────────────
                // Kích thước hình cầu hiển thị contact point TRONG VIEWPORT.
                // Không ảnh hưởng kết quả in – chỉ để người dùng nhìn rõ vị trí điểm.
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

                // ── Khoảng cách tới object ───────────────────────────────────
                // Contact point được dịch xuống dưới theo Z (Y trong Cura) bằng giá trị này.
                // 0mm = điểm nằm sát mặt overhang, lớn hơn = điểm thấp hơn mặt.
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

            // ── Checkbox: Hiển thị vùng overhang ─────────────────────────────
            // Bật/tắt overlay màu trên vùng overhang trong viewport.
            // Thay đổi ngay lập tức khi check/uncheck (không cần chạy lại detect).
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

            // ── Nút hành động Phần 1 ─────────────────────────────────────────
            RowLayout
            {
                Layout.fillWidth: true
                Layout.leftMargin:  UM.Theme.getSize("default_margin").width
                Layout.rightMargin: UM.Theme.getSize("default_margin").width
                spacing: UM.Theme.getSize("default_margin").width

                // Nút chính: chạy detectAndVisualize() – quét tất cả object trong scene
                Cura.PrimaryButton
                {
                    text: "Phát hiện & Hiển thị"
                    Layout.fillWidth: true
                    onClicked: manager.detectAndVisualize()
                    ToolTip.visible: hovered
                    ToolTip.delay: 400
                    ToolTip.text: "Quét toàn bộ object sẽ được in, phát hiện vùng overhang\nvà hiển thị điểm chống đỡ trên khung nhìn 3D."
                }

                // Nút phụ: xoá tất cả contact point markers và overlay khỏi scene
                Cura.SecondaryButton
                {
                    text: "Xoá điểm"
                    onClicked: manager.clearSupportPoints()
                    ToolTip.visible: hovered
                    ToolTip.delay: 400
                    ToolTip.text: "Xoá toàn bộ điểm chống đỡ đang hiển thị."
                }
            }

            // ── Divider ngang ─────────────────────────────────────────────────
            Rectangle
            {
                Layout.fillWidth: true
                Layout.leftMargin:  UM.Theme.getSize("default_margin").width
                Layout.rightMargin: UM.Theme.getSize("default_margin").width
                height: 1
                color: UM.Theme.getColor("lining")
            }

            // ══════════════════════════════════════════════════════════════════
            // PHẦN 2: CÂY CHỐNG ĐỠ
            // Các tham số điều khiển thuật toán mô phỏng cây từ contact points
            // ══════════════════════════════════════════════════════════════════
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

                // ── Góc nhánh ────────────────────────────────────────────────
                // Góc nghiêng từ trục đứng khi hai nhánh hội tụ.
                // Nhỏ hơn = nhánh gần thẳng đứng, hội tụ chậm hơn (điểm hội tụ thấp hơn).
                // Lớn hơn = nhánh nghiêng nhiều, hội tụ nhanh hơn.
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

                // ── Khoảng cách ghép cặp cơ bản ─────────────────────────────
                // Ngưỡng dxz tối đa (trong mặt phẳng XZ) để hai nhánh cấp 0 ghép cặp.
                // Ngưỡng thực = base_dist + max(level_a, level_b) × dist_per_level
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

                // ── Khoảng cách thêm mỗi cấp ─────────────────────────────────
                // Cho phép nhánh cấp cao ghép với nhánh xa hơn.
                // Ví dụ: base=20mm, per_level=5mm → cấp 2 có ngưỡng 30mm.
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

                // ── Khoảng cách tối thiểu tới vật thể ───────────────────────
                // Clearance kiểm tra khi tính đường đi chéo của nhánh.
                // Nếu đường chéo đi quá gần vật thể (< clearance mm), cặp bị từ chối.
                // 0 = tắt kiểm tra (nhánh có thể xuyên qua vật thể).
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

                // ── Hệ số tăng kích thước ─────────────────────────────────────
                // Nhánh càng xuống thấp càng dày hơn (như thân cây thật).
                // Công thức: r(y) = (Ø + (origin_y - y) × Ø × hệ_số/100) / 2
                // Ví dụ 20%: mỗi 10mm xuống thêm, bán kính tăng 2mm (nếu Ø=1mm).
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

                // ── Bước mô phỏng ─────────────────────────────────────────────
                // Độ phân giải sweep Y: mỗi vòng lặp di chuyển bao nhiêu mm.
                // Nhỏ hơn = chính xác hơn (phát hiện va chạm tốt hơn) nhưng chậm hơn.
                LabelWithTip
                {
                    text: "Bước mô phỏng"
                    tip: "Độ phân giải của vòng lặp mô phỏng (mm/bước).\nNhỏ hơn = chính xác hơn nhưng chậm hơn.\nPhạm vi: 0.10 – 10.00 mm | Khuyến nghị: 0.5 – 2 mm"
                }
                SpinBox
                {
                    id: treeStepSpinBox
                    Layout.fillWidth: true
                    from: 10; to: 1000   // Nội bộ: 0.10 – 10.00 mm × 100
                    stepSize: 1
                    editable: true
                    value: Math.round(manager.treeStepSize * 100)
                    onValueModified: manager.treeStepSize = value / 100.0
                    textFromValue: function(v) { return (v / 100.0).toFixed(2) }
                    valueFromText: function(t) { return Math.round(parseFloat(t) * 100) }
                }
                UM.Label { text: "mm" }

                // ── Đoạn thẳng sau gộp ───────────────────────────────────────
                // Sau khi hai nhánh gộp, nhánh mới BUỘC đi thẳng xuống N mm
                // trước khi được phép ghép cặp tiếp. Tránh cây bị gộp liên tục
                // ngay tại điểm hội tụ (oscillation).
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

                // ── Số luồng ─────────────────────────────────────────────────
                // Số luồng CPU dùng cho kiểm tra clearance song song.
                // 0 = tự động = os.cpu_count() (toàn bộ CPU logic).
                // textFromValue: hiển thị 0 thành "auto" thay vì "0".
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

            // ── Nút hành động Phần 2 ─────────────────────────────────────────
            RowLayout
            {
                Layout.fillWidth: true
                Layout.leftMargin:  UM.Theme.getSize("default_margin").width
                Layout.rightMargin: UM.Theme.getSize("default_margin").width
                spacing: UM.Theme.getSize("default_margin").width

                // Nút chính: generateTreeSupport() chạy trên luồng nền.
                // Disabled khi isGenerating=true (đang tính) để tránh chạy đè.
                // Text thay đổi khi đang tính: "Tạo cây chống đỡ" → "Đang tính toán…"
                Cura.PrimaryButton
                {
                    text: manager.isGenerating ? "Đang tính toán…" : "Tạo cây chống đỡ"
                    Layout.fillWidth: true
                    enabled: !manager.isGenerating   // Disable khi đang chạy background task
                    onClicked: manager.generateTreeSupport()
                    ToolTip.visible: hovered
                    ToolTip.delay: 400
                    ToolTip.text: "Tạo cấu trúc cây chống đỡ từ các contact points đã phát hiện.\nHãy chạy 'Phát hiện & Hiển thị' trước."
                }

                // Nút phụ: xoá toàn bộ mesh cây chống đỡ khỏi scene
                Cura.SecondaryButton
                {
                    text: "Xoá cây"
                    enabled: !manager.isGenerating   // Disable khi đang tính (tránh xoá nửa chừng)
                    onClicked: manager.clearTreeSupport()
                    ToolTip.visible: hovered
                    ToolTip.delay: 400
                    ToolTip.text: "Xoá toàn bộ cây chống đỡ đang hiển thị."
                }
            }

            // ── Divider ngang ─────────────────────────────────────────────────
            Rectangle
            {
                Layout.fillWidth: true
                Layout.leftMargin:  UM.Theme.getSize("default_margin").width
                Layout.rightMargin: UM.Theme.getSize("default_margin").width
                height: 1
                color: UM.Theme.getColor("lining")
            }

            // ── Khu vực Trạng thái ────────────────────────────────────────────
            // Hiển thị statusMessage từ Python + animated dots "..." khi đang tính.
            // Khi isGenerating=True: text + dots animation (Timer cứ 400ms đổi phase)
            // Khi isGenerating=False: text tĩnh, màu inactive (xám)
            Item
            {
                Layout.fillWidth: true
                Layout.leftMargin:  UM.Theme.getSize("default_margin").width
                Layout.rightMargin: UM.Theme.getSize("default_margin").width
                implicitHeight: statusLabel.implicitHeight

                property int dotPhase: 0                              // Phase hiện tại (0–3)
                property var dotTexts: ["   ", ".  ", ".. ", "..."]  // 4 trạng thái dots

                // Timer điều khiển animation dots khi đang tính toán
                Timer
                {
                    id: dotTimer
                    interval: 400    // Đổi phase mỗi 400ms
                    repeat: true
                    running: manager.isGenerating   // Chỉ chạy khi đang tính toán
                    onTriggered: parent.dotPhase = (parent.dotPhase + 1) % 4
                    onRunningChanged: if (!running) parent.dotPhase = 0  // Reset khi dừng
                }

                UM.Label
                {
                    id: statusLabel
                    anchors { left: parent.left; right: parent.right }
                    // Binding phức tạp: chọn text nguồn và thêm dots nếu đang tính
                    text: {
                        var base = manager.statusMessage !== "" ? manager.statusMessage
                                                                : "Nhấn \"Phát hiện & Hiển thị\" để bắt đầu quét."
                        return manager.isGenerating ? base + parent.dotTexts[parent.dotPhase] : base
                    }
                    wrapMode: Text.WordWrap
                    font.italic: true
                    // Màu chữ: đang tính = màu chữ thường, không tính = màu inactive (xám nhạt)
                    color: manager.isGenerating ? UM.Theme.getColor("text")
                                                : UM.Theme.getColor("text_inactive")
                }
            }

            // Padding dưới cùng
            Item { height: UM.Theme.getSize("default_margin").height }
        }
    }
}
