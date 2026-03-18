import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Window 2.15
import UM 1.5 as UM

Window {
    id: dialog
    title: "MeshTree Support - Settings"

    width: 500
    minimumWidth: 400
    height: 600
    minimumHeight: 500
    modality: Qt.NonModal

    // ------------------------------------------------------------------ //
    //  Helper component: one labeled row with a SpinBox                   //
    // ------------------------------------------------------------------ //
    component SettingRow: RowLayout {
        property alias label:    lbl.text
        property alias value:    spin.value
        property alias from:     spin.from
        property alias to:       spin.to
        property alias stepSize: spin.stepSize
        property alias unit:     unitLbl.text
        property string tooltip: ""
        signal valueEdited(real v)

        // Full tooltip = description + auto range line
        readonly property string _fullTip: tooltip +
            "\n\nGiới hạn: " + (spin.from / 10.0).toFixed(1) +
            " – " + (spin.to / 10.0).toFixed(1) +
            " " + unitLbl.text +
            "  |  Bước: " + (spin.stepSize / 10.0).toFixed(1)

        spacing: 8

        ToolTip.visible: false   // placeholder so child can trigger parent tip

        Label {
            id: lbl
            Layout.preferredWidth: 200
            wrapMode: Text.WordWrap

            MouseArea {
                id: tipArea
                anchors.fill: parent
                hoverEnabled: true
                ToolTip.visible: containsMouse && tooltip !== ""
                ToolTip.text:    _fullTip
                ToolTip.delay:   400
            }
        }
        SpinBox {
            id: spin
            Layout.preferredWidth: 100
            editable: true
            from:     0
            to:       9990
            stepSize: 1
            textFromValue: function(v) { return (v / 10.0).toFixed(1) }
            valueFromText: function(t) { return Math.round(parseFloat(t) * 10) }
            onValueModified: valueEdited(value / 10.0)
        }
        Label { id: unitLbl; color: "#888" }
    }

    // ------------------------------------------------------------------ //
    //  Background                                                          //
    // ------------------------------------------------------------------ //
    Rectangle {
        anchors.fill: parent
        color: UM.Theme.getColor ? UM.Theme.getColor("main_background") : "#ffffff"
    }

    ScrollView {
        anchors.fill: parent
        anchors.margins: 16
        contentWidth: availableWidth
        clip: true

        ColumnLayout {
            width: parent.width
            spacing: 6

            // ── Header ─────────────────────────────────────────────── //
            Label {
                text: "Tree Support Parameters"
                font.bold: true
                font.pixelSize: 15
                Layout.bottomMargin: 4
            }

            // ══ 1. Điểm A – Contact Points ═══════════════════════════ //
            Label {
                text: "① Điểm A  – Contact Points (tiếp xúc overhang)"
                font.bold: true; color: "#c0392b"
                Layout.topMargin: 2
            }
            Label {
                text: "Điểm nằm trên bề mặt overhang của vật thể, nơi support chạm vào model."
                color: "#888"; wrapMode: Text.WordWrap; Layout.fillWidth: true; font.pixelSize: 11
            }

            SettingRow {
                label:   "Support Angle (ngưỡng overhang)"
                value:   Math.round(manager.supportAngle * 10)
                from:    0; to: 890; stepSize: 5
                unit:    "deg"
                tooltip: "Góc ngưỡng để xác định mặt overhang, tính từ mặt phẳng nằm ngang.\n" +
                         "Mặt nào nghiêng HƠN góc này sẽ bị coi là overhang và cần support.\n\n" +
                         "• 45° – mặc định Cura\n• 30° – ít support hơn\n• 60° – nhiều support hơn"
                onValueEdited: manager.supportAngle = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Merge Threshold (ngưỡng gộp điểm A)"
                value:   Math.round(manager.mergeThreshold * 10)
                from:    1; to: 200; stepSize: 5
                unit:    "mm"
                tooltip: "Hai điểm A trong phạm vi này sẽ được gộp thành một điểm duy nhất.\n\n" +
                         "• 1–2 mm → giữ gần như tất cả điểm\n" +
                         "• 5 mm – mặc định\n• 10–20 mm → ít cành hơn"
                onValueEdited: manager.mergeThreshold = v
                Layout.fillWidth: true
            }

            Rectangle { height: 1; color: "#ddd"; Layout.fillWidth: true; Layout.topMargin: 6; Layout.bottomMargin: 6 }

            // ══ 2. Phân nhánh – Branch ════════════════════════════════ //
            Label {
                text: "② Phân nhánh  – Branch (thân cành từ A xuống B)"
                font.bold: true; color: "#27ae60"
                Layout.topMargin: 2
            }
            Label {
                text: "Hình dạng thân cành nối từ điểm A (overhang) xuống trụ B (sàn)."
                color: "#888"; wrapMode: Text.WordWrap; Layout.fillWidth: true; font.pixelSize: 11
            }

            SettingRow {
                label:   "Tip Arm Length (độ dài cánh tay từ A)"
                value:   Math.round(manager.tipArmLength * 10)
                from:    1; to: 200; stepSize: 5
                unit:    "mm"
                tooltip: "Chiều dài đoạn thẳng xuống (-Y) từ điểm A trước khi cành đi về trụ.\n\n" +
                         "• 1–2 mm – mặc định\n• 5+ mm → tách xa mặt model hơn"
                onValueEdited: manager.tipArmLength = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Branch Tip Diameter (đường kính đầu cành – tại A)"
                value:   Math.round(manager.branchTipDiameter * 10)
                from:    1; to: 100; stepSize: 1
                unit:    "mm"
                tooltip: "Đường kính ống cành tại điểm A – đầu mỏng nhất.\n\n" +
                         "• 0.6–0.8 mm – mặc định, mảnh, dễ bẻ sau in\n" +
                         "• 1.5–2.0 mm → cành to hơn, bền hơn"
                onValueEdited: manager.branchTipDiameter = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Branch Base Diameter (đường kính chân cành – tại trụ)"
                value:   Math.round(manager.branchBaseDiameter * 10)
                from:    1; to: 200; stepSize: 1
                unit:    "mm"
                tooltip: "Đường kính ống cành tại điểm nối với trụ B – đầu to nhất.\n" +
                         "Cành to dần từ A xuống đây tạo hình nón cụt (frustum).\n\n" +
                         "• 1.5–2.4 mm – mặc định\n• 4+ mm → chân cành rất to"
                onValueEdited: manager.branchBaseDiameter = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Branch Merge Distance (khoảng gộp cành)"
                value:   Math.round(manager.branchMergeDist * 10)
                from:    5; to: 500; stepSize: 5
                unit:    "mm"
                tooltip: "Hai cành có đầu gần nhau trong khoảng này sẽ được gộp lại.\n\n" +
                         "• 2–3 mm → hiếm khi gộp\n• 5 mm – mặc định\n• 15+ mm → gộp mạnh"
                onValueEdited: manager.branchMergeDist = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Max Segment Length (độ dài đoạn tối đa)"
                value:   Math.round(manager.maxSegmentLength * 10)
                from:    10; to: 5000; stepSize: 50
                unit:    "mm"
                tooltip: "Độ dài tối đa của mỗi đoạn trên đường từ cành xuống trụ.\n" +
                         "Đoạn dài hơn sẽ tự động được chia nhỏ thêm.\n\n" +
                         "• 20–30 mm → nhiều điểm gấp khúc, cành mềm hơn\n" +
                         "• 50 mm – mặc định\n• 100+ mm → ít điểm gấp hơn"
                onValueEdited: manager.maxSegmentLength = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Min Branch Length (độ dài tối thiểu đoạn cành)"
                value:   Math.round(manager.minBranchLength * 10)
                from:    1; to: 100; stepSize: 1
                unit:    "mm"
                tooltip: "Đoạn cành ngắn hơn giá trị này sẽ bị bỏ qua.\n\n" +
                         "• 0.5 mm → giữ hầu hết\n• 1.0 mm – mặc định\n• 3+ mm → chỉ giữ đoạn dài"
                onValueEdited: manager.minBranchLength = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Min Branch Angle (góc tối thiểu cành so với ngang)"
                value:   Math.round(manager.minBranchAngleDeg * 10)
                from:    0; to: 800; stepSize: 5
                unit:    "deg"
                tooltip: "Góc tối thiểu của đoạn cành so với mặt phẳng nằm ngang.\n" +
                         "Đoạn quá nằm ngang sẽ bị điều chỉnh hoặc bỏ qua.\n\n" +
                         "• 0° → không giới hạn\n• 20° – mặc định\n• 45° → chỉ giữ đoạn dốc"
                onValueEdited: manager.minBranchAngleDeg = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Min Junction Angle (góc mở tối thiểu tại điểm gộp)"
                value:   Math.round(manager.minJunctionAngleDeg * 10)
                from:    0; to: 1800; stepSize: 5
                unit:    "deg"
                tooltip: "Góc tối thiểu giữa hai cành tại điểm gộp (chữ Y).\n" +
                         "Nếu góc quá nhỏ (hai cành gần song song), bỏ qua lần gộp đó.\n\n" +
                         "• 0° → không giới hạn, gộp mọi cặp\n" +
                         "• 20° – mặc định\n• 45° → chỉ gộp khi hai cành tạo góc đủ rộng"
                onValueEdited: manager.minJunctionAngleDeg = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Min Branch Levels (số đoạn tối thiểu xuống trụ)"
                value:   Math.round(manager.minLevels * 10)
                from:    10; to: 200; stepSize: 10
                unit:    "đoạn"
                tooltip: "Số đoạn tối thiểu chia đường từ arm_end xuống đỉnh trụ.\n\n" +
                         "• 1 → thẳng một đoạn\n• 4 – mặc định\n• 8+ → nhiều khớp hơn"
                onValueEdited: manager.minLevels = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Max Merge Levels (số lần gộp tối đa)"
                value:   Math.round(manager.maxLevels * 10)
                from:    10; to: 500; stepSize: 10
                unit:    "lần"
                tooltip: "Số lần gộp cành tối đa trong greedy merge tree.\n\n" +
                         "• 3–5 → ít gộp\n• 10 – mặc định\n• 20+ → gộp nhiều hơn"
                onValueEdited: manager.maxLevels = v
                Layout.fillWidth: true
            }

            Rectangle { height: 1; color: "#ddd"; Layout.fillWidth: true; Layout.topMargin: 4; Layout.bottomMargin: 4 }

            // ══ 3. Trụ – Cylinder ═════════════════════════════════════ //
            Label {
                text: "③ Trụ  – Hollow Cylinder (object in được)"
                font.bold: true; color: "#8e44ad"
                Layout.topMargin: 2
            }
            Label {
                text: "Hình trụ rỗng in được, bao quanh các điểm B, vươn từ sàn lên gần điểm A."
                color: "#888"; wrapMode: Text.WordWrap; Layout.fillWidth: true; font.pixelSize: 11
            }

            SettingRow {
                label:   "B Cluster Distance (bán kính gộp cụm B)"
                value:   Math.round(manager.bClusterDist * 10)
                from:    5; to: 500; stepSize: 5
                unit:    "mm"
                tooltip: "Các điểm B trong phạm vi này sẽ được gộp thành một trụ rỗng chung.\n\n" +
                         "• 2–3 mm → gộp rất ít\n• 5 mm – mặc định\n• 15+ mm → gộp mạnh"
                onValueEdited: manager.bClusterDist = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "B Gap to A (khoảng cách đỉnh trụ đến điểm A)"
                value:   Math.round(manager.bGapToA * 10)
                from:    0; to: 5000; stepSize: 50
                unit:    "mm"
                tooltip: "Chiều cao trụ = A.y(gần nhất) − giá trị này.\n\n" +
                         "• 0 mm → trụ cao tới tận A\n• 20 mm – mặc định\n• 50 mm → cành dài hơn"
                onValueEdited: manager.bGapToA = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Max Base Area (diện tích đáy tối đa)"
                value:   Math.round(manager.maxBaseArea * 10)
                from:    100; to: 5000; stepSize: 50
                unit:    "mm²"
                tooltip: "Giới hạn diện tích đáy (π × r²) của trụ rỗng B.\n\n" +
                         "• 50 mm² → r_max ≈ 4 mm\n• 150 mm² – mặc định\n• 300 mm² → r_max ≈ 10 mm"
                onValueEdited: manager.maxBaseArea = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Wall Thickness (độ dày thành trụ rỗng)"
                value:   Math.round(manager.wallMm * 10)
                from:    1; to: 50; stepSize: 1
                unit:    "mm"
                tooltip: "Độ dày thành của trụ rỗng B (outer_r − inner_r).\n\n" +
                         "• 0.5–0.8 mm → thành mỏng\n• 1.2 mm – mặc định\n• 2–3 mm → thành dày"
                onValueEdited: manager.wallMm = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Min Outer Radius (bán kính ngoài tối thiểu)"
                value:   Math.round(manager.minOuterR * 10)
                from:    5; to: 100; stepSize: 5
                unit:    "mm"
                tooltip: "Bán kính ngoài tối thiểu của trụ rỗng B.\n\n" +
                         "• 0.8–1.0 mm → trụ rất nhỏ\n• 1.5 mm – mặc định\n• 3–5 mm → trụ to"
                onValueEdited: manager.minOuterR = v
                Layout.fillWidth: true
            }

            Rectangle { height: 1; color: "#ddd"; Layout.fillWidth: true; Layout.topMargin: 6; Layout.bottomMargin: 6 }

            // ── Module status ──────────────────────────────────────── //
            Label { text: "Module Status"; font.bold: true; color: "#555" }

            TextArea {
                id: statusArea
                Layout.fillWidth: true
                readOnly: true
                text: "Click 'Check Modules' to test imports."
                color: "#333"
                background: Rectangle { color: "#f5f5f5"; border.color: "#ccc"; radius: 4 }
                font.family: "Courier New"
                font.pixelSize: 12
                wrapMode: Text.WrapAnywhere
                implicitHeight: 130
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Button {
                    text: "Check Modules"
                    onClicked: statusArea.text = manager.getModuleStatus()
                }
                Button {
                    text: "Sync from Cura"
                    onClicked: {
                        manager.syncFromCura()
                        statusArea.text = "Settings synced from active Cura profile."
                    }
                }
                Item { Layout.fillWidth: true }
                Button {
                    text: "Save"
                    onClicked: statusArea.text = manager.saveSettings()
                }
                Button {
                    text: "Load"
                    onClicked: statusArea.text = manager.loadSettings()
                }
            }

            Rectangle { height: 1; color: "#ddd"; Layout.fillWidth: true; Layout.topMargin: 4; Layout.bottomMargin: 4 }

            // ── Mark A/B points ────────────────────────────────────── //
            Label { text: "Overhang Visualisation"; font.bold: true; color: "#555" }

            Label {
                text: "Select an object (or leave nothing selected for all objects), then click Mark."
                color: "#888"; wrapMode: Text.WordWrap; Layout.fillWidth: true; font.pixelSize: 11
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Button {
                    text: "Mark A/B Points"
                    highlighted: true
                    onClicked: {
                        statusArea.text = "Detecting overhangs..."
                        var result = manager.markOverhangs()
                        statusArea.text = result
                    }
                }
                Button {
                    text: "Clear Markers"
                    onClicked: {
                        manager.clearMarkers()
                        statusArea.text = "Markers cleared."
                    }
                }
            }

            Rectangle { height: 1; color: "#ddd"; Layout.fillWidth: true; Layout.topMargin: 4; Layout.bottomMargin: 4 }

            // ── Action buttons ─────────────────────────────────────── //
            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Button {
                    text: "Generate Tree Support"
                    onClicked: {
                        manager.generate()
                        statusArea.text = "Generate called - pipeline not yet implemented."
                    }
                }
                Item { Layout.fillWidth: true }
                Button {
                    text: "Close"
                    onClicked: dialog.close()
                }
            }

            Item { height: 8 }
        }
    }
}
