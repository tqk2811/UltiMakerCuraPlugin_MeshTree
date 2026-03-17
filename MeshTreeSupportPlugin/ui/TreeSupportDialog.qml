import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import UM 1.5 as UM

UM.Dialog {
    id: dialog
    title: "MeshTree Support – Settings"

    width: 480
    minimumWidth: 400
    height: 580
    minimumHeight: 500

    // ------------------------------------------------------------------ //
    //  Helper component: one labeled row with a SpinBox                   //
    // ------------------------------------------------------------------ //
    component SettingRow: RowLayout {
        property alias label:   lbl.text
        property alias value:   spin.value
        property alias from:    spin.from
        property alias to:      spin.to
        property alias stepSize: spin.stepSize
        property alias unit:    unitLbl.text
        signal valueEdited(real v)

        spacing: 8
        Label {
            id: lbl
            Layout.preferredWidth: 190
            wrapMode: Text.WordWrap
        }
        SpinBox {
            id: spin
            Layout.preferredWidth: 100
            editable: true
            // Use integer steps × 0.1 internally for 1-decimal precision
            property real realValue: value / 10.0
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
    //  Main content                                                        //
    // ------------------------------------------------------------------ //
    ScrollView {
        anchors.fill: parent
        anchors.margins: 12
        contentWidth: availableWidth
        clip: true

        ColumnLayout {
            width: parent.width
            spacing: 4

            // ── Header ─────────────────────────────────────────────── //
            Label {
                text: "Tree Support Parameters"
                font.bold: true
                font.pixelSize: 14
                Layout.bottomMargin: 6
            }

            // ── Overhang ───────────────────────────────────────────── //
            Label { text: "Overhang"; font.bold: true; color: "#555" }

            SettingRow {
                label:    "Support Angle  (overhang threshold)"
                value:    Math.round(manager.supportAngle * 10)
                from:     0; to: 890; stepSize: 5
                unit:     "°"
                onValueEdited: manager.supportAngle = v
                Layout.fillWidth: true
            }

            UM.TooltipArea {
                Layout.fillWidth: true; height: helpAngle.height
                text: "Faces whose angle from horizontal exceeds this value will receive support."
                Label {
                    id: helpAngle
                    text: "Faces tilted more than this angle from horizontal are considered overhanging."
                    color: "#888"; wrapMode: Text.WordWrap; width: parent.width
                    font.pixelSize: 11
                }
            }

            Rectangle { height: 1; color: "#ddd"; Layout.fillWidth: true; Layout.topMargin: 4; Layout.bottomMargin: 4 }

            // ── Branches ───────────────────────────────────────────── //
            Label { text: "Branches"; font.bold: true; color: "#555" }

            SettingRow {
                label:    "Branch Angle  (max from vertical)"
                value:    Math.round(manager.branchAngle * 10)
                from:     0; to: 800; stepSize: 5
                unit:     "°"
                onValueEdited: manager.branchAngle = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:    "Tip Diameter"
                value:    Math.round(manager.tipDiameter * 10)
                from:     1; to: 100; stepSize: 1
                unit:     "mm"
                onValueEdited: manager.tipDiameter = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:    "Branch Diameter"
                value:    Math.round(manager.branchDiameter * 10)
                from:     1; to: 200; stepSize: 5
                unit:     "mm"
                onValueEdited: manager.branchDiameter = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:    "Branch Diameter Angle  (widens per layer)"
                value:    Math.round(manager.branchDiameterAngle * 10)
                from:     0; to: 300; stepSize: 5
                unit:     "°"
                onValueEdited: manager.branchDiameterAngle = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:    "Base Plate Diameter"
                value:    Math.round(manager.baseDiameter * 10)
                from:     10; to: 500; stepSize: 5
                unit:     "mm"
                onValueEdited: manager.baseDiameter = v
                Layout.fillWidth: true
            }

            Rectangle { height: 1; color: "#ddd"; Layout.fillWidth: true; Layout.topMargin: 4; Layout.bottomMargin: 4 }

            // ── Merging ────────────────────────────────────────────── //
            Label { text: "Merging"; font.bold: true; color: "#555" }

            SettingRow {
                label:    "Merge Threshold  (branches closer than this are merged)"
                value:    Math.round(manager.mergeThreshold * 10)
                from:     1; to: 200; stepSize: 5
                unit:     "mm"
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
            }

            Rectangle { height: 1; color: "#ddd"; Layout.fillWidth: true; Layout.topMargin: 4; Layout.bottomMargin: 4 }

            // ── Action buttons ─────────────────────────────────────── //
            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Button {
                    text: "Generate Tree Support"
                    highlighted: true
                    onClicked: {
                        manager.generate()
                        statusArea.text = "Generate called – check Cura log for output.\n(Pipeline not yet implemented.)"
                    }
                }
                Item { Layout.fillWidth: true }
                Button {
                    text: "Close"
                    onClicked: dialog.close()
                }
            }
        }
    }
}
