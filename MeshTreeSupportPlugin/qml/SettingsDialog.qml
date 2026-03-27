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
    height: 960
    minimumWidth: 500
    minimumHeight: 750
    transientParent: mainWindow
    flags: Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint
    modality: Qt.NonModal
    color: "#f5f5f5"

    // Ghi nhớ vị trí cửa sổ
    onXChanged: Qt.callLater(function() { manager.updateSetting("_win_x", x) })
    onYChanged: Qt.callLater(function() { manager.updateSetting("_win_y", y) })

    Component.onCompleted: {
        var wx = manager.getSetting("_win_x")
        var wy = manager.getSetting("_win_y")
        if (wx !== 0 || wy !== 0) {
            x = wx
            y = wy
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 10

        Label {
            text: "Cây chống đỡ - Cài đặt"
            font.pixelSize: 18
            font.bold: true
            color: "#333333"
        }

        Rectangle { height: 1; Layout.fillWidth: true; color: "#cccccc" }

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
                            ToolTip.text: "Bỏ qua các vùng lơ lửng có chiều cao (Z) thấp hơn giá trị này.\nPhạm vi: 0 - 50 mm"
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
                            ToolTip.text: "Độ dày lớp vỏ mỏng ôm sát bề mặt lơ lửng.\nPhạm vi: 0.1 - 5 mm"
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
                            ToolTip.text: "Khoảng cách giữa bề mặt vật thể và lớp trong của vỏ overhang.\nPhạm vi: 0 - 3 mm"
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
                            ToolTip.text: "Đa giác nhỏ hơn giá trị này sẽ được gộp với hàng xóm.\nPhạm vi: 0.1 - 5 mm²"
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
                            ToolTip.text: "Đa giác lớn hơn giá trị này sẽ được chia nhỏ.\nPhạm vi: 2 - 50 mm²"
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
                            ToolTip.text: "Bán kính octagon tại Point A (đầu nhánh).\nPhạm vi: 0.1 - 2 mm"
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
                            ToolTip.text: "Chiều cao tip tỷ lệ với diện tích đa giác × hệ số.\nPhạm vi: 0.1 - 2"
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

                // ─── NHÓM 5: NHÁNH CÂY (Space Colonization) ───
                GroupBox {
                    title: "  Nhánh cây (Space Colonization)  "
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
                            ToolTip.text: "Khoảng cách mỗi bước di chuyển nhánh.\nGiá trị nhỏ → mượt hơn nhưng chậm hơn.\nPhạm vi: 0.5 - 5 mm"
                            MouseArea { id: stepSizeMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fStepSize
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0.5; top: 5; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("step_size", v) }
                        }
                        Label { text: "mm" }

                        Label {
                            text: "Khoảng cách gộp:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: mergeDistMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Khoảng cách tối đa để 2 nhánh gộp vào nhau.\nGiá trị lớn → nhánh gộp nhiều hơn, ít chân hơn.\nPhạm vi: 5 - 50 mm"
                            MouseArea { id: mergeDistMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fMergeDist
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 5; top: 50; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("merge_distance", v) }
                        }
                        Label { text: "mm" }

                        Label {
                            text: "Số nhánh gộp tối đa:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: maxMergeMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Số nhánh tối đa được gộp cùng lúc tại 1 điểm.\nPhạm vi: 2 - 10"
                            MouseArea { id: maxMergeMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fMaxMergeCount
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: IntValidator { bottom: 2; top: 10 }
                            onEditingFinished: { var v = parseInt(text); if (!isNaN(v)) manager.updateSetting("max_merge_count", v) }
                        }
                        Label { text: "nhánh" }

                        Label {
                            text: "Góc nhánh tối đa:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: maxAngleMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Góc lệch tối đa của nhánh so với phương thẳng đứng.\nGiá trị nhỏ → nhánh thẳng hơn.\nPhạm vi: 10 - 70°"
                            MouseArea { id: maxAngleMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fMaxBranchAngle
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 10; top: 70; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("max_branch_angle", v) }
                        }
                        Label { text: "độ" }

                        Label {
                            text: "Chiều cao rơi thẳng:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: straightDropMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Dưới chiều cao này, nhánh rơi thẳng đứng xuống bàn in.\nTạo chân đế ổn định.\nPhạm vi: 0 - 50 mm"
                            MouseArea { id: straightDropMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fStraightDrop
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0; top: 50; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("straight_drop_height", v) }
                        }
                        Label { text: "mm" }

                        Label {
                            text: "Tốc độ tăng bán kính:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: radiusGrowthMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Hệ số tăng bán kính mỗi bước: r *= (1 + hệ_số).\n0 = chỉ tăng khi gộp nhánh (Murray).\nPhạm vi: 0 - 0.1"
                            MouseArea { id: radiusGrowthMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fRadiusGrowth
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0; top: 0.1; decimals: 3 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("radius_growth_rate", v) }
                        }
                        Label { text: "/bước" }

                        Label {
                            text: "Departure thẳng xuống:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: depStraightMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Bật: đoạn departure đi thẳng xuống (-Z).\nTắt: đi theo hướng vuông góc bề mặt overhang."
                            MouseArea { id: depStraightMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        CheckBox {
                            id: fDepartureStraight
                            Layout.preferredWidth: 80
                            onCheckedChanged: manager.updateSetting("departure_straight_down", checked ? 1.0 : 0.0)
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
                            ToolTip.text: "Khoảng cách tối thiểu giữa nhánh support và bề mặt vật thể.\nPhạm vi: 0.5 - 10 mm"
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
                            ToolTip.text: "Mở rộng lưới SDF ra ngoài bounding box.\nPhạm vi: 2 - 30 mm"
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

                // ─── NHÓM 7: MESH NHÁNH CÂY ───
                GroupBox {
                    title: "  Mesh nhánh cây  "
                    Layout.fillWidth: true

                    GridLayout {
                        columns: 3
                        columnSpacing: 8
                        rowSpacing: 6
                        anchors.fill: parent

                        Label {
                            text: "Số cạnh mặt cắt:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: segmentsMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Số cạnh của đa giác mặt cắt ngang ống nhánh.\n8 = bát giác (mặc định), nhiều hơn → tròn hơn nhưng nhiều tam giác hơn.\nPhạm vi: 4 - 16"
                            MouseArea { id: segmentsMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fCylSegments
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: IntValidator { bottom: 4; top: 16 }
                            onEditingFinished: { var v = parseInt(text); if (!isNaN(v)) manager.updateSetting("cylinder_segments", v) }
                        }
                        Label { text: "cạnh" }

                        Label {
                            text: "Hệ số mở rộng đế:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: brimMultMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Bán kính đế = bán kính nhánh × hệ số này.\nGiá trị lớn → đế rộng hơn, bám bàn in tốt hơn.\nPhạm vi: 1 - 10"
                            MouseArea { id: brimMultMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fBrimMultiplier
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 1; top: 10; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("base_brim_multiplier", v) }
                        }
                        Label { text: "×" }

                        Label {
                            text: "Chiều cao đế:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: brimHeightMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Chiều cao của phần đế hình nón mở rộng tại chân cây.\nPhạm vi: 0.1 - 5 mm"
                            MouseArea { id: brimHeightMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fBrimHeight
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0.1; top: 5; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("base_brim_height", v) }
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
    Component.onCompleted: reloadSettings()

    Connections {
        target: manager
        function onSettingsChanged() { reloadSettings() }
    }

    function reloadSettings() {
        if (!manager) return

        fOverhangAngle.text      = manager.getSetting("overhang_angle").toFixed(1)
        fMinHeight.text          = manager.getSetting("min_overhang_height").toFixed(1)
        fShellThickness.text     = manager.getSetting("shell_thickness").toFixed(1)
        fShellGap.text           = manager.getSetting("shell_gap").toFixed(1)
        fMinPolyArea.text        = manager.getSetting("min_polygon_area").toFixed(2)
        fMaxPolyArea.text        = manager.getSetting("max_polygon_area").toFixed(1)
        fTipRadius.text          = manager.getSetting("tip_radius").toFixed(2)
        fTipHeightFactor.text    = manager.getSetting("tip_height_factor").toFixed(2)
        fStepSize.text           = manager.getSetting("step_size").toFixed(1)
        fMergeDist.text          = manager.getSetting("merge_distance").toFixed(1)
        fMaxMergeCount.text      = manager.getSetting("max_merge_count").toFixed(0)
        fMaxBranchAngle.text     = manager.getSetting("max_branch_angle").toFixed(1)
        fStraightDrop.text       = manager.getSetting("straight_drop_height").toFixed(1)
        fRadiusGrowth.text       = manager.getSetting("radius_growth_rate").toFixed(3)
        fDepartureStraight.checked = manager.getSetting("departure_straight_down") > 0.5
        fMinClearance.text       = manager.getSetting("min_clearance").toFixed(1)
        fSdfResolution.text      = manager.getSetting("sdf_resolution").toFixed(1)
        fSdfPadding.text         = manager.getSetting("sdf_padding").toFixed(1)
        fCylSegments.text        = manager.getSetting("cylinder_segments").toFixed(0)
        fBrimMultiplier.text     = manager.getSetting("base_brim_multiplier").toFixed(1)
        fBrimHeight.text         = manager.getSetting("base_brim_height").toFixed(1)
    }
}
