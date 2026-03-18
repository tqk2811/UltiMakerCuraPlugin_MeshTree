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
        property alias tooltip:  tipArea.text
        signal valueEdited(real v)

        spacing: 8

        ToolTip.visible: false   // placeholder so child can trigger parent tip

        Label {
            id: lbl
            Layout.preferredWidth: 200
            wrapMode: Text.WordWrap

            MouseArea {
                id: tipArea
                property string text: ""
                anchors.fill: parent
                hoverEnabled: true
                ToolTip.visible: containsMouse && tipArea.text !== ""
                ToolTip.text:    tipArea.text
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

            // ── Overhang ───────────────────────────────────────────── //
            Label { text: "Overhang"; font.bold: true; color: "#555" }

            SettingRow {
                label:   "Support Angle (ngưỡng overhang)"
                value:   Math.round(manager.supportAngle * 10)
                from:    0; to: 890; stepSize: 5
                unit:    "deg"
                tooltip: "Góc tính từ mặt phẳng nằm ngang.\nMặt nào nghiêng hơn góc này sẽ được coi là overhang và cần support.\nVí dụ: 50° → mặt dốc hơn 50° so với nằm ngang cần support."
                onValueEdited: manager.supportAngle = v
                Layout.fillWidth: true
            }

            Rectangle { height: 1; color: "#ddd"; Layout.fillWidth: true; Layout.topMargin: 4; Layout.bottomMargin: 4 }

            // ── Branches ───────────────────────────────────────────── //
            Label { text: "Branches"; font.bold: true; color: "#555" }

            SettingRow {
                label:   "Branch Angle (góc cành tối đa)"
                value:   Math.round(manager.branchAngle * 10)
                from:    0; to: 800; stepSize: 5
                unit:    "deg"
                tooltip: "Góc tối đa của cành so với phương thẳng đứng.\nCành không được nghiêng quá góc này khi vươn từ điểm neo B lên điểm tiếp xúc A.\nGóc càng lớn → cành càng thoải, ít bị đổ hơn."
                onValueEdited: manager.branchAngle = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Tip Diameter (đường kính đầu cành)"
                value:   Math.round(manager.tipDiameter * 10)
                from:    1; to: 100; stepSize: 1
                unit:    "mm"
                tooltip: "Đường kính phần đầu nhọn của cành tại điểm tiếp xúc A trên bề mặt overhang.\nNhỏ hơn → dễ bẻ gãy support sau khi in xong."
                onValueEdited: manager.tipDiameter = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Branch Diameter (đường kính cành)"
                value:   Math.round(manager.branchDiameter * 10)
                from:    1; to: 200; stepSize: 5
                unit:    "mm"
                tooltip: "Đường kính chính của thân cành support.\nLớn hơn → cứng hơn, tốn vật liệu hơn."
                onValueEdited: manager.branchDiameter = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Branch Diameter Angle (độ phình cành)"
                value:   Math.round(manager.branchDiameterAngle * 10)
                from:    0; to: 300; stepSize: 5
                unit:    "deg"
                tooltip: "Tốc độ mở rộng đường kính cành theo chiều cao (mỗi lớp).\nGiá trị lớn hơn → cành phình rộng nhanh hơn từ đỉnh xuống đáy, tạo hình nón."
                onValueEdited: manager.branchDiameterAngle = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Base Plate Diameter (đường kính đế)"
                value:   Math.round(manager.baseDiameter * 10)
                from:    10; to: 500; stepSize: 5
                unit:    "mm"
                tooltip: "Đường kính của đĩa đế tại điểm neo B trên bàn in.\nĐế rộng hơn → bám sàn tốt hơn, ít bị lật hơn."
                onValueEdited: manager.baseDiameter = v
                Layout.fillWidth: true
            }

            Rectangle { height: 1; color: "#ddd"; Layout.fillWidth: true; Layout.topMargin: 4; Layout.bottomMargin: 4 }

            // ── Merging ────────────────────────────────────────────── //
            Label { text: "Merging"; font.bold: true; color: "#555" }

            SettingRow {
                label:   "Merge Threshold (ngưỡng gộp cành)"
                value:   Math.round(manager.mergeThreshold * 10)
                from:    1; to: 200; stepSize: 5
                unit:    "mm"
                tooltip: "Nếu hai điểm overhang cách nhau dưới khoảng cách này, chúng sẽ được gộp thành một điểm tiếp xúc duy nhất.\nGiá trị lớn hơn → ít cành hơn, support thô hơn nhưng nhanh hơn."
                onValueEdited: manager.mergeThreshold = v
                Layout.fillWidth: true
            }

            Rectangle { height: 1; color: "#ddd"; Layout.fillWidth: true; Layout.topMargin: 4; Layout.bottomMargin: 4 }

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
