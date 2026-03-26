// =============================================================================
// Dialog cài đặt và hiển thị tiến độ cho plugin Mesh Tree Support
//
// Cung cấp:
// - Các trường nhập liệu cho tham số thuật toán (nhóm theo chức năng)
// - Thanh tiến trình (ProgressBar) cập nhật realtime từ Job
// - Nút Bắt đầu / Mặc định / Đóng
// - Tự động lưu/load thông số qua manager (Python backend)
//
// Giao tiếp Python ↔ QML:
// - manager.getSetting(key) → lấy giá trị float
// - manager.updateSetting(key, value) → cập nhật và auto-save
// - manager.resetSettings() → khôi phục mặc định
// - manager.startGeneration() → bắt đầu sinh cây support
// - manager.progressValue / statusText / isRunning → thuộc tính reactive
// =============================================================================

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Window {
    id: root
    title: "Mesh Tree Support - Cài đặt"
    width: 560
    height: 920
    minimumWidth: 500
    minimumHeight: 750
    // Gắn làm cửa sổ con của Cura (luôn nổi trên Cura, đóng khi Cura đóng)
    transientParent: mainWindow
    flags: Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint
    modality: Qt.NonModal
    color: "#f5f5f5"

    // =========================================================================
    // Layout chính: Header → Settings (scrollable) → Progress → Buttons
    // =========================================================================
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 10

        // === Tiêu đề ===
        Label {
            text: "Cây chống đỡ - Cài đặt"
            font.pixelSize: 18
            font.bold: true
            color: "#333333"
        }

        Rectangle { height: 1; Layout.fillWidth: true; color: "#cccccc" }

        // === Vùng settings cuộn được ===
        ScrollView {
            id: scrollView
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

            ColumnLayout {
                width: scrollView.availableWidth
                spacing: 10

                // ─── NHÓM 1: PHÁT HIỆN VÙNG LƠ LỬNG ───
                GroupBox {
                    title: "  Phát hiện vùng lơ lửng (Overhang)  "
                    Layout.fillWidth: true

                    GridLayout {
                        columns: 3
                        columnSpacing: 8
                        rowSpacing: 6
                        anchors.fill: parent

                        Label {
                            text: "Góc overhang:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: overhangAngleMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Góc nghiêng tối thiểu so với phương thẳng đứng để được coi là vùng lơ lửng cần support.\nGiá trị nhỏ → nhiều vùng được phát hiện hơn. Thường dùng 45-60°.\nPhạm vi: 5 - 85°"
                            MouseArea { id: overhangAngleMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fOverhangAngle
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 5; top: 85; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("overhang_angle", v) }
                        }
                        Label { text: "độ" }

                        Label {
                            text: "Chiều cao tối thiểu:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: minHeightMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Bỏ qua các vùng lơ lửng có chiều cao (Z) thấp hơn giá trị này.\nGiúp lọc bỏ các overhang nhỏ sát bàn in không cần support.\nPhạm vi: 0 - 50 mm"
                            MouseArea { id: minHeightMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fMinHeight
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0; top: 50; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("min_overhang_height", v) }
                        }
                        Label { text: "mm" }

                    }
                }

                // ─── NHÓM 2: VỎ OVERHANG ───
                GroupBox {
                    title: "  Vỏ overhang (Shell)  "
                    Layout.fillWidth: true

                    GridLayout {
                        columns: 3
                        columnSpacing: 8
                        rowSpacing: 6
                        anchors.fill: parent

                        Label {
                            text: "Độ dày vỏ overhang:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: shellThicknessMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Độ dày lớp vỏ mỏng ôm sát bề mặt lơ lửng.\nVỏ gồm 2 lớp (trong + ngoài) tạo thành mặt cong hỗ trợ.\nPhạm vi: 0.1 - 5 mm"
                            MouseArea { id: shellThicknessMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fShellThickness
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0.1; top: 5; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("shell_thickness", v) }
                        }
                        Label { text: "mm" }

                        Label {
                            text: "Khoảng cách vỏ:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: shellGapMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Khoảng cách giữa bề mặt vật thể và lớp trong của vỏ overhang.\nGiá trị lớn → dễ tách support, giá trị nhỏ → bám sát hơn.\nPhạm vi: 0 - 3 mm"
                            MouseArea { id: shellGapMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fShellGap
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0; top: 3; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("shell_gap", v) }
                        }
                        Label { text: "mm" }
                    }
                }

                // ─── NHÓM 3: XỬ LÝ ĐA GIÁC ───
                GroupBox {
                    title: "  Xử lý đa giác (Polygon)  "
                    Layout.fillWidth: true

                    GridLayout {
                        columns: 3
                        columnSpacing: 8
                        rowSpacing: 6
                        anchors.fill: parent

                        Label {
                            text: "Diện tích tối thiểu:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: minPolyAreaMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Đa giác nhỏ hơn giá trị này sẽ được gộp với hàng xóm nhỏ nhất.\nGiảm số lượng nhánh ở vùng chi tiết nhỏ.\nPhạm vi: 0.1 - 5 mm²"
                            MouseArea { id: minPolyAreaMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fMinPolyArea
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0.1; top: 5; decimals: 2 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("min_polygon_area", v) }
                        }
                        Label { text: "mm²" }

                        Label {
                            text: "Diện tích tối đa:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: maxPolyAreaMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Đa giác lớn hơn giá trị này sẽ được chia nhỏ.\nĐảm bảo mỗi nhánh hỗ trợ vùng vừa phải.\nPhạm vi: 2 - 50 mm²"
                            MouseArea { id: maxPolyAreaMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fMaxPolyArea
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 2; top: 50; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("max_polygon_area", v) }
                        }
                        Label { text: "mm²" }
                    }
                }

                // ─── NHÓM 4: TIP INTERFACE ───
                GroupBox {
                    title: "  Tip Interface  "
                    Layout.fillWidth: true

                    GridLayout {
                        columns: 3
                        columnSpacing: 8
                        rowSpacing: 6
                        anchors.fill: parent

                        Label {
                            text: "Bán kính tip:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: tipRadiusMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Bán kính octagon tại Point A (đầu nhánh).\nGiá trị nhỏ → nhánh mảnh, giá trị lớn → nhánh dày.\nPhạm vi: 0.1 - 2 mm"
                            MouseArea { id: tipRadiusMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fTipRadius
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0.1; top: 2; decimals: 2 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("tip_radius", v) }
                        }
                        Label { text: "mm" }

                        Label {
                            text: "Hệ số chiều cao:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: tipHeightMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Chiều cao mỗi bước tip tỷ lệ diện tích × hệ số này.\nGiá trị lớn → tip dài hơn, chuyển tiếp mượt hơn.\nPhạm vi: 0.1 - 2"
                            MouseArea { id: tipHeightMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fTipHeightFactor
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0.1; top: 2; decimals: 2 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("tip_height_factor", v) }
                        }
                        Label { text: "" }
                    }
                }

                // ─── NHÓM 5: NHÁNH CÂY ───
                GroupBox {
                    title: "  Nhánh cây (Branch Routing)  "
                    Layout.fillWidth: true

                    GridLayout {
                        columns: 3
                        columnSpacing: 8
                        rowSpacing: 6
                        anchors.fill: parent

                        Label {
                            text: "Bước mô phỏng:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: stepSizeMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Khoảng cách mỗi bước di chuyển nhánh.\nGiá trị nhỏ → mượt hơn nhưng chậm.\nPhạm vi: 0.1 - 2 mm"
                            MouseArea { id: stepSizeMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fStepSize
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0.1; top: 2; decimals: 2 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("branch_step_size", v) }
                        }
                        Label { text: "mm" }

                        Label {
                            text: "Trọng lực:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: gravityMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Trọng số lực kéo nhánh đi thẳng xuống.\nGiá trị lớn → nhánh thẳng hơn.\nPhạm vi: 0.1 - 5"
                            MouseArea { id: gravityMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fGravity
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0.1; top: 5; decimals: 2 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("gravity_weight", v) }
                        }
                        Label { text: "" }

                        Label {
                            text: "Lực gộp nhánh:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: mergeWeightMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Trọng số lực kéo nhánh về phía nhau để gộp.\nGiá trị lớn → gộp nhanh hơn, ít chân hơn.\nPhạm vi: 0 - 2"
                            MouseArea { id: mergeWeightMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fMergeWeight
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0; top: 2; decimals: 2 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("merge_weight", v) }
                        }
                        Label { text: "" }

                        Label {
                            text: "Khoảng gộp tối đa:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: mergeDistMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Giới hạn khoảng cách gộp nhánh tối đa.\nNgăn gộp nhánh quá xa gây mất cân bằng.\nPhạm vi: 5 - 100 mm"
                            MouseArea { id: mergeDistMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fMergeDistMax
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 5; top: 100; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("merge_distance_max", v) }
                        }
                        Label { text: "mm" }

                        Label {
                            text: "Hệ số tăng diện tích:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: areaGrowthMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Diện tích nhánh tăng theo: A = A₀ × (1 + hệ_số × Δz).\nGiá trị lớn → nhánh dày nhanh hơn.\nPhạm vi: 0.01 - 0.5"
                            MouseArea { id: areaGrowthMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fAreaGrowth
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0.01; top: 0.5; decimals: 3 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("area_growth_coeff", v) }
                        }
                        Label { text: "/mm" }

                        Label {
                            text: "Quán tính:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: momentumMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Hệ số quán tính (0 = không quán tính, 1 = quán tính tối đa).\nGiá trị cao → đường mượt hơn, đổi hướng chậm.\nPhạm vi: 0 - 0.9"
                            MouseArea { id: momentumMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fMomentum
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0; top: 0.9; decimals: 2 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("momentum_alpha", v) }
                        }
                        Label { text: "" }
                    }
                }

                // ─── NHÓM 6: TRÁNH VA CHẠM (BVH + SDF) ───
                GroupBox {
                    title: "  Tránh va chạm (BVH + SDF)  "
                    Layout.fillWidth: true

                    GridLayout {
                        columns: 3
                        columnSpacing: 8
                        rowSpacing: 6
                        anchors.fill: parent

                        Label {
                            text: "Khoảng cách an toàn:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: minClearanceMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Khoảng cách tối thiểu giữa nhánh support và bề mặt vật thể.\nNhánh vi phạm sẽ bị đẩy ra xa bằng gradient SDF.\nPhạm vi: 0.5 - 10 mm"
                            MouseArea { id: minClearanceMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fMinClearance
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0.5; top: 10; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("min_clearance", v) }
                        }
                        Label { text: "mm" }

                        Label {
                            text: "Lực chống va chạm:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: collisionWeightMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Trọng số lực đẩy nhánh ra xa vật thể.\nGiá trị lớn → tránh xa hơn nhưng nhánh có thể bị bẻ cong mạnh.\nPhạm vi: 0.1 - 5"
                            MouseArea { id: collisionWeightMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fCollisionWeight
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0.1; top: 5; decimals: 2 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("collision_weight", v) }
                        }
                        Label { text: "" }

                        Label {
                            text: "Độ phân giải SDF:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: sdfResolutionMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Kích thước ô lưới 3D của trường khoảng cách (SDF).\nGiá trị nhỏ → chính xác hơn nhưng tốn RAM.\nPhạm vi: 1 - 10 mm"
                            MouseArea { id: sdfResolutionMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fSdfResolution
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 1; top: 10; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("sdf_resolution", v) }
                        }
                        Label { text: "mm" }

                        Label {
                            text: "Phần mở rộng SDF:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: sdfPaddingMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Mở rộng lưới SDF ra ngoài bounding box.\nĐảm bảo nhánh đi vòng ngoài vẫn có dữ liệu va chạm.\nPhạm vi: 2 - 30 mm"
                            MouseArea { id: sdfPaddingMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fSdfPadding
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 2; top: 30; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("sdf_padding", v) }
                        }
                        Label { text: "mm" }
                    }
                }
            }
        }

        // =====================================================================
        // THANH TIẾN TRÌNH + TRẠNG THÁI
        // =====================================================================
        Rectangle { height: 1; Layout.fillWidth: true; color: "#cccccc" }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 4

            ProgressBar {
                id: progressBar
                Layout.fillWidth: true
                from: 0
                to: 100
                value: manager ? manager.progressValue : 0
            }

            Label {
                text: manager ? manager.statusText : "Sẵn sàng"
                color: "#666666"
                font.pixelSize: 12
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
        }

        // =====================================================================
        // CÁC NÚT ĐIỀU KHIỂN
        // =====================================================================
        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Button {
                text: "Mặc định"
                onClicked: manager.resetSettings()
                enabled: manager ? !manager.isRunning : true
            }

            Item { Layout.fillWidth: true }

            Button {
                text: "Huỷ"
                visible: manager ? manager.isRunning : false
                onClicked: manager.cancelGeneration()
            }

            Button {
                text: "Bắt đầu"
                enabled: manager ? !manager.isRunning : true
                highlighted: true
                onClicked: manager.startGeneration()
            }

            Button {
                text: "Đóng"
                onClicked: root.close()
            }
        }
    }

    // =========================================================================
    // NẠP / TẢI LẠI THÔNG SỐ
    // =========================================================================

    // Nạp giá trị ban đầu từ Python khi dialog mở
    Component.onCompleted: reloadSettings()

    // Khi Python phát signal settingsChanged (VD: sau khi Reset) → reload tất cả
    Connections {
        target: manager
        function onSettingsChanged() { reloadSettings() }
    }

    // Hàm nạp lại tất cả giá trị từ Python backend
    function reloadSettings() {
        if (!manager) return

        fOverhangAngle.text     = manager.getSetting("overhang_angle").toFixed(1)
        fMinHeight.text         = manager.getSetting("min_overhang_height").toFixed(1)
        fShellThickness.text    = manager.getSetting("shell_thickness").toFixed(1)
        fShellGap.text          = manager.getSetting("shell_gap").toFixed(1)
        fMinPolyArea.text       = manager.getSetting("min_polygon_area").toFixed(2)
        fMaxPolyArea.text       = manager.getSetting("max_polygon_area").toFixed(1)
        fTipRadius.text         = manager.getSetting("tip_radius").toFixed(2)
        fTipHeightFactor.text   = manager.getSetting("tip_height_factor").toFixed(2)
        fStepSize.text          = manager.getSetting("branch_step_size").toFixed(2)
        fGravity.text           = manager.getSetting("gravity_weight").toFixed(2)
        fMergeWeight.text       = manager.getSetting("merge_weight").toFixed(2)
        fMergeDistMax.text      = manager.getSetting("merge_distance_max").toFixed(1)
        fAreaGrowth.text        = manager.getSetting("area_growth_coeff").toFixed(3)
        fMomentum.text          = manager.getSetting("momentum_alpha").toFixed(2)
        fMinClearance.text      = manager.getSetting("min_clearance").toFixed(1)
        fCollisionWeight.text   = manager.getSetting("collision_weight").toFixed(2)
        fSdfResolution.text     = manager.getSetting("sdf_resolution").toFixed(1)
        fSdfPadding.text        = manager.getSetting("sdf_padding").toFixed(1)
    }
}
