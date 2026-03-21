// =============================================================================
// Dialog cài đặt và hiển thị tiến độ cho plugin Mesh Tree Support
//
// Cung cấp:
// - Các trường nhập liệu cho 13 tham số thuật toán (nhóm theo chức năng)
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
    title: "Mesh Tree Support"
    width: 530
    height: 780
    minimumWidth: 480
    minimumHeight: 650
    flags: Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint
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
            text: "Tree Support - Cai dat"
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
                    title: "  Phat hien vung lo lung (Overhang)  "
                    Layout.fillWidth: true

                    GridLayout {
                        columns: 3
                        columnSpacing: 8
                        rowSpacing: 6
                        anchors.fill: parent

                        Label { text: "Goc overhang:"; Layout.preferredWidth: 180 }
                        TextField {
                            id: fOverhangAngle
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 5; top: 85; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("overhang_angle", v) }
                        }
                        Label { text: "do" }

                        Label { text: "Chieu cao toi thieu:"; Layout.preferredWidth: 180 }
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

                // ─── NHÓM 2: GOM CỤM ĐIỂM ───
                GroupBox {
                    title: "  Gom cum diem (KD-Tree Clustering)  "
                    Layout.fillWidth: true

                    GridLayout {
                        columns: 3
                        columnSpacing: 8
                        rowSpacing: 6
                        anchors.fill: parent

                        Label { text: "Ban kinh gom cum:"; Layout.preferredWidth: 180 }
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
                    title: "  Nhanh cay (Space Colonization)  "
                    Layout.fillWidth: true

                    GridLayout {
                        columns: 3
                        columnSpacing: 8
                        rowSpacing: 6
                        anchors.fill: parent

                        Label { text: "Ban kinh ngon:"; Layout.preferredWidth: 180 }
                        TextField {
                            id: fTipRadius
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0.1; top: 5; decimals: 2 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("branch_tip_radius", v) }
                        }
                        Label { text: "mm" }

                        Label { text: "Buoc di chuyen:"; Layout.preferredWidth: 180 }
                        TextField {
                            id: fStepSize
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0.2; top: 5; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("step_size", v) }
                        }
                        Label { text: "mm" }

                        Label { text: "K/c merge nhanh:"; Layout.preferredWidth: 180 }
                        TextField {
                            id: fMergeDistance
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 1; top: 30; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("merge_distance", v) }
                        }
                        Label { text: "mm" }

                        Label { text: "Chieu cao merge min:"; Layout.preferredWidth: 180 }
                        TextField {
                            id: fMinMergeHeight
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0; top: 100; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("min_merge_height", v) }
                        }
                        Label { text: "mm" }

                        Label { text: "Luc hoi tu:"; Layout.preferredWidth: 180 }
                        TextField {
                            id: fConvergence
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0; top: 1; decimals: 2 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("convergence_strength", v) }
                        }
                        Label { text: "" }

                        Label { text: "Chieu cao roi thang:"; Layout.preferredWidth: 180 }
                        TextField {
                            id: fStraightDrop
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0; top: 50; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("straight_drop_height", v) }
                        }
                        Label { text: "mm" }
                    }
                }

                // ─── NHÓM 4: TRÁNH VA CHẠM (BVH + SDF) ───
                GroupBox {
                    title: "  Tranh va cham (BVH + SDF)  "
                    Layout.fillWidth: true

                    GridLayout {
                        columns: 3
                        columnSpacing: 8
                        rowSpacing: 6
                        anchors.fill: parent

                        Label { text: "K/c an toan:"; Layout.preferredWidth: 180 }
                        TextField {
                            id: fMinClearance
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 0.5; top: 10; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("min_clearance", v) }
                        }
                        Label { text: "mm" }

                        Label { text: "Do phan giai SDF:"; Layout.preferredWidth: 180 }
                        TextField {
                            id: fSdfResolution
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: DoubleValidator { bottom: 1; top: 10; decimals: 1 }
                            onEditingFinished: { var v = parseFloat(text); if (!isNaN(v)) manager.updateSetting("sdf_resolution", v) }
                        }
                        Label { text: "mm" }

                        Label { text: "Padding SDF:"; Layout.preferredWidth: 180 }
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

                // ─── NHÓM 5: MESH ───
                GroupBox {
                    title: "  Mesh ong tru  "
                    Layout.fillWidth: true

                    GridLayout {
                        columns: 3
                        columnSpacing: 8
                        rowSpacing: 6
                        anchors.fill: parent

                        Label { text: "So mat ong tru:"; Layout.preferredWidth: 180 }
                        TextField {
                            id: fCylinderSegments
                            Layout.preferredWidth: 80
                            horizontalAlignment: TextInput.AlignHCenter
                            validator: IntValidator { bottom: 4; top: 24 }
                            onEditingFinished: { var v = parseInt(text); if (!isNaN(v)) manager.updateSetting("cylinder_segments", v) }
                        }
                        Label { text: "" }
                    }
                }
            }
        }

        // =====================================================================
        // PROGRESS BAR + STATUS
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
                text: manager ? manager.statusText : "San sang"
                color: "#666666"
                font.pixelSize: 12
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
        }

        // =====================================================================
        // BUTTONS
        // =====================================================================
        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Button {
                text: "Mac dinh"
                onClicked: manager.resetSettings()
                enabled: manager ? !manager.isRunning : true
            }

            Item { Layout.fillWidth: true }

            Button {
                text: (manager && manager.isRunning) ? "Dang chay..." : "Bat dau"
                enabled: manager ? !manager.isRunning : true
                highlighted: true
                onClicked: manager.startGeneration()
            }

            Button {
                text: "Dong"
                onClicked: root.close()
            }
        }
    }

    // =========================================================================
    // LOAD / RELOAD SETTINGS
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
        fStraightDrop.text      = manager.getSetting("straight_drop_height").toFixed(1)
        fMinClearance.text      = manager.getSetting("min_clearance").toFixed(1)
        fSdfResolution.text     = manager.getSetting("sdf_resolution").toFixed(1)
        fSdfPadding.text        = manager.getSetting("sdf_padding").toFixed(1)
        fCylinderSegments.text  = Math.round(manager.getSetting("cylinder_segments")).toString()
    }
}
