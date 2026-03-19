import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.3
import UM 1.5 as UM
import Cura 1.0 as Cura

UM.Dialog
{
    id: dialog
    title: "Overhang Support Visualizer"

    width: 400
    minimumWidth: 320
    minimumHeight: 340

    // Keep the dialog alive between open/close cycles
    onClosing: { visible = false; close.accepted = false }

    ColumnLayout
    {
        anchors.fill: parent
        anchors.margins: UM.Theme.getSize("default_margin").width
        spacing: UM.Theme.getSize("default_margin").height

        // ── Settings grid ─────────────────────────────────────────────
        GridLayout
        {
            columns: 3
            Layout.fillWidth: true
            columnSpacing: UM.Theme.getSize("default_margin").width
            rowSpacing: UM.Theme.getSize("default_margin").height

            // Row 1 – Overhang angle
            UM.Label { text: "Overhang angle:" }
            SpinBox
            {
                id: angleSpinBox
                Layout.fillWidth: true
                from: 0; to: 90
                value: manager.overhangAngle
                onValueModified: manager.overhangAngle = value
            }
            UM.Label { text: "°" }

            // Row 2 – Point spacing
            UM.Label { text: "Point spacing:" }
            SpinBox
            {
                id: spacingSpinBox
                Layout.fillWidth: true
                from: 1; to: 200
                value: manager.pointSpacing
                onValueModified: manager.pointSpacing = value
            }
            UM.Label { text: "mm" }

            // Row 3 – Point diameter
            UM.Label { text: "Point diameter:" }
            SpinBox
            {
                id: diameterSpinBox
                Layout.fillWidth: true
                from: 1; to: 50
                value: manager.pointDiameter
                onValueModified: manager.pointDiameter = value
            }
            UM.Label { text: "mm" }
        }

        // ── Divider ───────────────────────────────────────────────────
        Rectangle
        {
            Layout.fillWidth: true
            height: 1
            color: UM.Theme.getColor("lining")
        }

        // ── Status message ────────────────────────────────────────────
        UM.Label
        {
            id: statusLabel
            Layout.fillWidth: true
            text: manager.statusMessage
            wrapMode: Text.WordWrap
            font.italic: true
        }

        Item { Layout.fillHeight: true }

        // ── Action buttons ────────────────────────────────────────────
        RowLayout
        {
            Layout.fillWidth: true
            spacing: UM.Theme.getSize("default_margin").width

            Cura.PrimaryButton
            {
                text: "Detect & Visualize"
                Layout.fillWidth: true
                onClicked: manager.detectAndVisualize()
            }

            Cura.SecondaryButton
            {
                text: "Clear"
                onClicked: manager.clearSupportPoints()
            }
        }
    }
}
