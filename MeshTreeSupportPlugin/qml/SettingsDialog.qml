// =============================================================================
// Dialog cài đặt và hiển thị tiến độ cho plugin Mesh Tree Support
//
// Cung cấp:
// - Các trường nhập liệu cho 16 tham số thuật toán (nhóm theo chức năng)
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
            text: "Cây chống đỡ hữu cơ - Cài đặt"
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

                        Label {
                            text: "Độ dày vỏ overhang:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: shellThicknessMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Độ dày lớp vỏ mỏng ôm sát bề mặt lơ lửng.\nVỏ gồm 2 lớp (trong + ngoài) tạo thành mặt cong hỗ trợ.\nCác ngọn cây support nối vào lớp ngoài của vỏ.\nPhạm vi: 0.1 - 5 mm"
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
                            ToolTip.text: "Khoảng cách giữa bề mặt vật thể và lớp trong của vỏ overhang.\nGiá trị lớn → dễ tách support, giá trị nhỏ → bám sát hơn.\nTổng khoảng cách tip đến vật thể = độ dày vỏ + khoảng cách vỏ.\nPhạm vi: 0 - 3 mm"
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

                // ─── NHÓM 2: GOM CỤM ĐIỂM ───
                GroupBox {
                    title: "  Gom cụm điểm (KD-Tree Clustering)  "
                    Layout.fillWidth: true

                    GridLayout {
                        columns: 3
                        columnSpacing: 8
                        rowSpacing: 6
                        anchors.fill: parent

                        Label {
                            text: "Bán kính gom cụm:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: clusterRadiusMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Các điểm overhang trong bán kính này được gộp thành 1 nhánh support.\nGiá trị nhỏ → nhiều nhánh hơn (dày đặc), giá trị lớn → ít nhánh (thưa).\nPhạm vi: 1 - 50 mm"
                            MouseArea { id: clusterRadiusMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fClusterRadius
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 1; top: 50; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("cluster_radius", v) }
                        }
                        Label { text: "mm" }
                    }
                }

                // ─── NHÓM 3: NHÁNH CÂY (Space Colonization) ───
                GroupBox {
                    title: "  Nhánh cây (Space Colonization)  "
                    Layout.fillWidth: true

                    GridLayout {
                        columns: 3
                        columnSpacing: 8
                        rowSpacing: 6
                        anchors.fill: parent

                        Label {
                            text: "Bán kính ngọn:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: tipRadiusMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Bán kính nhánh tại điểm tiếp xúc với vật thể (ngọn cây).\nGiá trị nhỏ → dễ bẻ support, giá trị lớn → bám chắc hơn.\nNên >= 1.5x đường kính đầu phun để in được.\nPhạm vi: 0.1 - 5 mm"
                            MouseArea { id: tipRadiusMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fTipRadius
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0.1; top: 5; decimals: 2 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("branch_tip_radius", v) }
                        }
                        Label { text: "mm" }

                        Label {
                            text: "Bước di chuyển:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: stepSizeMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Khoảng cách mỗi bước khi thuật toán mọc nhánh từ trên xuống.\nGiá trị nhỏ → nhánh mượt hơn nhưng tính toán lâu hơn.\nGiá trị lớn → nhanh hơn nhưng nhánh thô, góc cạnh.\nPhạm vi: 0.2 - 5 mm"
                            MouseArea { id: stepSizeMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fStepSize
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0.2; top: 5; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("step_size", v) }
                        }
                        Label { text: "mm" }

                        Label {
                            text: "Khoảng cách gộp nhánh:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: mergeDistanceMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Hai nhánh cách nhau dưới khoảng cách này sẽ hợp nhất thành một.\nGiá trị lớn → nhiều nhánh merge sớm, tạo thân chính to.\nGiá trị nhỏ → ít merge, nhiều nhánh riêng lẻ.\nPhạm vi: 1 - 30 mm"
                            MouseArea { id: mergeDistanceMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fMergeDistance
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 1; top: 30; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("merge_distance", v) }
                        }
                        Label { text: "mm" }

                        Label {
                            text: "Chiều cao gộp tối thiểu:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: minMergeHeightMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Nhánh chỉ được phép merge khi ở trên chiều cao này.\nDưới mức này, nhánh rơi thẳng xuống bàn in, không gộp nữa.\nTránh merge quá gần đế gây mất ổn định.\nPhạm vi: 0 - 100 mm"
                            MouseArea { id: minMergeHeightMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fMinMergeHeight
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0; top: 100; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("min_merge_height", v) }
                        }
                        Label { text: "mm" }

                        Label {
                            text: "Lực hội tụ:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: convergenceMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Cường độ kéo các nhánh về phía trọng tâm chung (trên mặt phẳng XY).\n0 = không kéo (nhánh rơi thẳng), 1 = kéo mạnh nhất.\nGiá trị lớn → cây gọn hơn, nhánh tập trung. Giá trị nhỏ → cây toả rộng.\nPhạm vi: 0 - 1"
                            MouseArea { id: convergenceMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fConvergence
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0; top: 1; decimals: 2 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("convergence_strength", v) }
                        }
                        Label { text: "" }

                        Label {
                            text: "Góc nhánh tối đa:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: maxBranchAngleMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Góc lệch tối đa của nhánh so với phương thẳng đứng (trục Z).\nNhánh không được nghiêng quá góc này → tránh đi ngang/ngược lên.\nGóc nhỏ → nhánh thẳng đứng hơn, góc lớn → cho phép nghiêng nhiều.\nPhạm vi: 5 - 85°"
                            MouseArea { id: maxBranchAngleMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fMaxBranchAngle
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 5; top: 85; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("max_branch_angle", v) }
                        }
                        Label { text: "độ" }

                        Label {
                            text: "Bước xuất phát:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: departureStepsMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Số bước đi vuông góc bề mặt tại ngọn nhánh (đoạn xuất phát).\nĐoạn này đi theo hướng pháp tuyến ra xa bề mặt vật thể trước khi bắt đầu routing.\nĐộ dài thực tế = số bước × bước di chuyển (mm).\nVD: 3 bước × 1mm = 3mm đoạn xuất phát vuông góc.\nGiúp tạo chân vuông góc dễ bẻ support sau khi in.\nPhạm vi: 1 - 10 bước"
                            MouseArea { id: departureStepsMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fDepartureSteps
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: IntValidator { bottom: 1; top: 10 }
                            onEditingFinished: { var v = parseInt(text); if (!isNaN(v)) manager.updateSetting("departure_steps", v) }
                        }
                        Label { text: "bước" }

                        Label {
                            text: "Chiều cao rơi thẳng:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: straightDropMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Khi nhánh xuống dưới chiều cao này, nó rơi thẳng đứng xuống bàn in.\nTạo chân đế ổn định, không bẻ ngang ở phần thấp.\nGiá trị lớn → chân thẳng dài hơn. 0 = không rơi thẳng.\nPhạm vi: 0 - 50 mm"
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
                            text: "Hệ số mập dần:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: radiusGrowthMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Mỗi bước routing, bán kính nhánh tăng thêm tỷ lệ này.\nBổ sung cho định luật Murray (chỉ tăng khi merge).\n0 = chỉ dùng Murray. 0.02 = +2%/bước (nhánh 50 bước mập ~2.7x).\n0.05 = +5%/bước (nhánh 50 bước mập ~11x).\nPhạm vi: 0 - 0.1"
                            MouseArea { id: radiusGrowthMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fRadiusGrowth
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0; top: 0.1; decimals: 3 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("radius_growth_rate", v) }
                        }
                        Label { text: "" }
                    }
                }

                // ─── NHÓM 4: TRÁNH VA CHẠM (BVH + SDF) ───
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

                // ─── NHÓM 5: MESH ỐNG TRỤ ───
                GroupBox {
                    title: "  Lưới ống trụ  "
                    Layout.fillWidth: true

                    GridLayout {
                        columns: 3
                        columnSpacing: 8
                        rowSpacing: 6
                        anchors.fill: parent

                        Label {
                            text: "Số mặt ống trụ:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: cylinderSegmentsMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Số cạnh đa giác tạo thành tiết diện ống trụ.\nGiá trị nhỏ (4-6) → ống vuông/lục giác, ít tam giác, nhẹ file.\nGiá trị lớn (12-24) → ống tròn mượt, nhiều tam giác hơn.\nPhạm vi: 4 - 24"
                            MouseArea { id: cylinderSegmentsMA; anchors.fill: parent; hoverEnabled: true }
                        }
                        TextField {
                            id: fCylinderSegments
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: IntValidator { bottom: 4; top: 24 }
                            onEditingFinished: { var v = parseInt(text); if (!isNaN(v)) manager.updateSetting("cylinder_segments", v) }
                        }
                        Label { text: "" }

                        Label {
                            text: "Hệ số rộng đế:"
                            Layout.preferredWidth: 180
                            ToolTip.visible: brimMultiplierMA.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: "Bán kính đế (brim) = bán kính nhánh × hệ số này.\nTạo phần loe ra ở chân cây để chống đổ khi in.\n1 = không loe (bằng nhánh). 3 = đế rộng gấp 3x nhánh.\nPhạm vi: 1 - 10×"
                            MouseArea { id: brimMultiplierMA; anchors.fill: parent; hoverEnabled: true }
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
                            ToolTip.text: "Chiều cao phần loe đế (brim) từ bàn in lên.\nGiá trị nhỏ → đế phẳng, loe nhanh. Giá trị lớn → loe dài, thoai thoải.\nThường 0.3 - 1 mm là đủ ổn định.\nPhạm vi: 0.1 - 5 mm"
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
        fClusterRadius.text     = manager.getSetting("cluster_radius").toFixed(1)
        fTipRadius.text         = manager.getSetting("branch_tip_radius").toFixed(2)
        fStepSize.text          = manager.getSetting("step_size").toFixed(1)
        fMergeDistance.text      = manager.getSetting("merge_distance").toFixed(1)
        fMinMergeHeight.text    = manager.getSetting("min_merge_height").toFixed(1)
        fConvergence.text       = manager.getSetting("convergence_strength").toFixed(2)
        fMaxBranchAngle.text    = manager.getSetting("max_branch_angle").toFixed(1)
        fDepartureSteps.text    = Math.round(manager.getSetting("departure_steps")).toString()
        fStraightDrop.text      = manager.getSetting("straight_drop_height").toFixed(1)
        fRadiusGrowth.text      = manager.getSetting("radius_growth_rate").toFixed(3)
        fShellThickness.text    = manager.getSetting("shell_thickness").toFixed(1)
        fShellGap.text          = manager.getSetting("shell_gap").toFixed(1)
        fMinClearance.text      = manager.getSetting("min_clearance").toFixed(1)
        fSdfResolution.text     = manager.getSetting("sdf_resolution").toFixed(1)
        fSdfPadding.text        = manager.getSetting("sdf_padding").toFixed(1)
        fBrimMultiplier.text    = manager.getSetting("base_brim_multiplier").toFixed(1)
        fBrimHeight.text        = manager.getSetting("base_brim_height").toFixed(1)
        fCylinderSegments.text  = Math.round(manager.getSetting("cylinder_segments")).toString()
    }
}
