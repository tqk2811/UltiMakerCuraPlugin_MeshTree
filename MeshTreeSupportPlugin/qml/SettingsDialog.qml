// =============================================================================
// Dialog cài đặt và hiển thị tiến độ cho plugin Mesh Tree Support
//
// Cung cấp:
// - Các trường nhập liệu cho 7 tham số thuật toán (nhóm theo chức năng)
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
    width: 530
    height: 780
    minimumWidth: 480
    minimumHeight: 650
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

                // ─── NHÓM 3: TRÁNH VA CHẠM (BVH + SDF) ───
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
                            ToolTip.text: "Khoảng cách tối thiểu giữa nhánh support và bề mặt vật thể.\nNhánh vi phạm sẽ bị đẩy ra xa bằng gradient SDF.\nGiá trị lớn → an toàn hơn nhưng nhánh xa vật thể.\nPhạm vi: 0.5 - 10 mm"
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
                            text: "Độ phân giải SDF:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: sdfResolutionMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Kích thước ô lưới 3D của trường khoảng cách (SDF).\nGiá trị nhỏ → chính xác hơn nhưng tốn RAM và thời gian tính.\nGiá trị lớn → nhanh, ít RAM nhưng kém chính xác.\nPhạm vi: 1 - 10 mm"
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
                            ToolTip.text: "Mở rộng lưới SDF ra ngoài bounding box của vật thể.\nĐảm bảo nhánh đi vòng ngoài vẫn có dữ liệu va chạm.\nGiá trị lớn → phạm vi rộng hơn nhưng tốn thêm RAM.\nPhạm vi: 2 - 30 mm"
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
        fMinClearance.text      = manager.getSetting("min_clearance").toFixed(1)
        fSdfResolution.text     = manager.getSetting("sdf_resolution").toFixed(1)
        fSdfPadding.text        = manager.getSetting("sdf_padding").toFixed(1)
    }
}
