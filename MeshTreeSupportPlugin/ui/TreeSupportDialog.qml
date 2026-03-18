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

            // ══ 1. Điểm A – Contact Points (overhang, trên cao) ══════ //
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
                         "• 45° – mặc định Cura, cân bằng giữa chất lượng và vật liệu\n" +
                         "• 30° – chỉ support những chỗ dốc đứng nhất, ít support hơn\n" +
                         "• 60° – support nhiều hơn, an toàn hơn cho model phức tạp\n\n" +
                         "Lưu ý: giá trị nhỏ → ít điểm A, giá trị lớn → nhiều điểm A hơn."
                onValueEdited: manager.supportAngle = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Tip Diameter (đường kính đầu tiếp xúc)"
                value:   Math.round(manager.tipDiameter * 10)
                from:    1; to: 100; stepSize: 1
                unit:    "mm"
                tooltip: "Đường kính phần đầu nhọn của cành support tại điểm A (nơi chạm vào model).\n\n" +
                         "• Nhỏ (0.5–1 mm) → dễ bẻ gãy support sau in, vết để lại ít\n" +
                         "• Lớn (2–3 mm) → support bền hơn nhưng khó tách và để lại vết\n\n" +
                         "Khuyến nghị: 0.8–1.2 mm cho PLA/PETG, 0.5–0.8 mm cho resin."
                onValueEdited: manager.tipDiameter = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Merge Threshold (ngưỡng gộp điểm A)"
                value:   Math.round(manager.mergeThreshold * 10)
                from:    1; to: 200; stepSize: 5
                unit:    "mm"
                tooltip: "Hai điểm A trong phạm vi này sẽ được gộp thành một điểm duy nhất.\n" +
                         "Giúp giảm số lượng cành support trên cùng một vùng overhang.\n\n" +
                         "• 1–2 mm → giữ gần như tất cả điểm, support dày đặc, chính xác\n" +
                         "• 5 mm – bình thường, cân bằng số lượng và chất lượng\n" +
                         "• 10–20 mm → ít cành hơn, in nhanh hơn nhưng có thể thiếu support\n\n" +
                         "Lưu ý: giá trị này cũng là kích thước ô lưới để phân vùng điểm A."
                onValueEdited: manager.mergeThreshold = v
                Layout.fillWidth: true
            }

            Rectangle { height: 1; color: "#ddd"; Layout.fillWidth: true; Layout.topMargin: 6; Layout.bottomMargin: 6 }

            // ══ 2. Phân nhánh – Branch (từ A xuống) ══════════════════ //
            Label {
                text: "② Phân nhánh  – Branch (thân cành từ A xuống B)"
                font.bold: true; color: "#27ae60"
                Layout.topMargin: 2
            }
            Label {
                text: "Hình dạng thân cành nối từ điểm A (overhang) xuống điểm B (sàn)."
                color: "#888"; wrapMode: Text.WordWrap; Layout.fillWidth: true; font.pixelSize: 11
            }

            SettingRow {
                label:   "Branch Angle (góc cành tối đa)"
                value:   Math.round(manager.branchAngle * 10)
                from:    0; to: 800; stepSize: 5
                unit:    "deg"
                tooltip: "Góc tối đa mà cành support được phép nghiêng so với phương thẳng đứng.\n" +
                         "Cành vươn từ điểm B (sàn) lên điểm A (overhang) không được vượt góc này.\n\n" +
                         "• 0° → cành hoàn toàn thẳng đứng, B nằm ngay dưới A\n" +
                         "• 40° – mặc định Cura, cành có thể nghiêng vừa phải để tránh model\n" +
                         "• 60–70° → cành rất thoải, B có thể lệch xa để tìm vị trí tốt hơn\n\n" +
                         "Góc lớn hơn giúp B tránh xa footprint model, nhưng cành dài và yếu hơn."
                onValueEdited: manager.branchAngle = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Branch Diameter (đường kính thân)"
                value:   Math.round(manager.branchDiameter * 10)
                from:    1; to: 200; stepSize: 5
                unit:    "mm"
                tooltip: "Đường kính danh nghĩa của thân cành support (tại điểm A trên overhang).\n" +
                         "Giá trị này là đường kính trước khi áp dụng Branch Diameter Angle.\n\n" +
                         "• 1–2 mm → cành mảnh, dễ bẻ, tiết kiệm vật liệu\n" +
                         "• 3 mm – mặc định Cura, phù hợp hầu hết trường hợp\n" +
                         "• 5+ mm → cành dày, cứng, dùng cho model nặng hoặc overhang rộng\n\n" +
                         "Kết hợp với Branch Diameter Angle để tạo hình nón từ đỉnh xuống đáy."
                onValueEdited: manager.branchDiameter = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Branch Diameter Angle (độ phình thân)"
                value:   Math.round(manager.branchDiameterAngle * 10)
                from:    0; to: 300; stepSize: 5
                unit:    "deg"
                tooltip: "Tốc độ tăng đường kính thân theo chiều cao, tạo hình nón từ đỉnh xuống đáy.\n" +
                         "Công thức: diameter_tại_lớp = branch_diameter + 2 × tan(angle) × chiều_cao\n\n" +
                         "• 0° → thân hình trụ, đường kính không đổi từ A xuống B\n" +
                         "• 5° – mặc định Cura, thân phình nhẹ, ổn định tốt\n" +
                         "• 10–15° → thân phình mạnh, rất ổn định nhưng tốn vật liệu\n\n" +
                         "Giá trị lớn kết hợp cành cao sẽ tạo đế rất rộng tại điểm B."
                onValueEdited: manager.branchDiameterAngle = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Tip Arm Length (độ dài cánh tay từ A)"
                value:   Math.round(manager.tipArmLength * 10)
                from:    1; to: 200; stepSize: 5
                unit:    "mm"
                tooltip: "Chiều dài đoạn thẳng vuông góc với bề mặt overhang tại điểm A.\n" +
                         "Cành bắt đầu bằng đoạn này theo hướng pháp tuyến mặt trước khi đi xuống trụ.\n\n" +
                         "• 1–2 mm → cánh tay ngắn, cành bắt đầu đi xuống gần như ngay từ A\n" +
                         "• 5 mm – vừa, cành tách xa bề mặt model một chút trước khi đi xuống\n" +
                         "• 10+ mm → cánh tay dài, hữu ích khi model có vành nhô ra"
                onValueEdited: manager.tipArmLength = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Branch Merge Distance (khoảng gộp cành)"
                value:   Math.round(manager.branchMergeDist * 10)
                from:    5; to: 500; stepSize: 5
                unit:    "mm"
                tooltip: "Hai cành có điểm đầu (sau cánh tay) gần nhau trong khoảng này sẽ gộp lại.\n" +
                         "Điểm gộp nằm ở giữa, thấp hơn trong hai đầu cành, từ đó đi chung xuống trụ.\n\n" +
                         "• 2–3 mm → hiếm khi gộp, mỗi điểm A gần như có cành riêng\n" +
                         "• 5 mm – mặc định, gộp các cành từ các điểm A gần nhau\n" +
                         "• 15+ mm → gộp mạnh, ít cành hơn nhưng thân trở nên dày hơn"
                onValueEdited: manager.branchMergeDist = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Branch Radius Tip (bán kính đầu cành – tại A)"
                value:   Math.round(manager.branchRadiusTip * 10)
                from:    1; to: 50; stepSize: 1
                unit:    "mm"
                tooltip: "Bán kính ống cành tại điểm A – đầu mỏng nhất.\n" +
                         "Cành nhỏ dần từ đây lên điểm tiếp xúc model.\n\n" +
                         "• 0.3–0.4 mm – mặc định, mảnh, dễ bẻ sau in\n" +
                         "• 0.8–1.0 mm → cành to hơn, bền hơn nhưng khó tách"
                onValueEdited: manager.branchRadiusTip = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Branch Radius Base (bán kính chân cành – tại trụ)"
                value:   Math.round(manager.branchRadiusBase * 10)
                from:    1; to: 100; stepSize: 1
                unit:    "mm"
                tooltip: "Bán kính ống cành tại điểm nối với trụ B – đầu to nhất.\n" +
                         "Cành to dần từ A xuống đây, tạo hình nón cụt (frustum).\n\n" +
                         "• 0.8–1.2 mm – mặc định, phình vừa phải\n" +
                         "• 2+ mm → chân cành rất to, cứng nhưng tốn vật liệu"
                onValueEdited: manager.branchRadiusBase = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Min Branch Length (độ dài tối thiểu cành phụ)"
                value:   Math.round(manager.minBranchLength * 10)
                from:    1; to: 100; stepSize: 1
                unit:    "mm"
                tooltip: "Cành phụ ngắn hơn giá trị này sẽ bị bỏ qua, không vẽ.\n" +
                         "Giúp tránh sinh ra các đoạn quá ngắn không có ý nghĩa.\n\n" +
                         "• 0.5 mm → giữ hầu hết cành, kể cả rất ngắn\n" +
                         "• 1.0 mm – mặc định, loại bỏ các đoạn dưới 1 mm\n" +
                         "• 3+ mm → chỉ giữ cành dài, cây support trông gọn hơn"
                onValueEdited: manager.minBranchLength = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Min Branch Angle (góc tối thiểu cành phụ)"
                value:   Math.round(manager.minBranchAngleDeg * 10)
                from:    0; to: 800; stepSize: 5
                unit:    "deg"
                tooltip: "Góc tối thiểu của cành so với mặt phẳng nằm ngang.\n" +
                         "Cành quá nằm ngang (< góc này) sẽ bị điều chỉnh xuống thấp hơn,\n" +
                         "hoặc bỏ qua nếu không thể đạt góc yêu cầu.\n\n" +
                         "• 0° → không giới hạn, cành có thể nằm ngang hoàn toàn\n" +
                         "• 20° – mặc định, đủ dốc để tự in không cần support thêm\n" +
                         "• 45° → chỉ giữ cành khá dốc, cây support chắc hơn"
                onValueEdited: manager.minBranchAngleDeg = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Min Branch Levels (số đoạn tối thiểu xuống trụ)"
                value:   Math.round(manager.minLevels * 10)
                from:    10; to: 200; stepSize: 10
                unit:    "đoạn"
                tooltip: "Số đoạn tối thiểu chia đường từ arm_end xuống đỉnh trụ.\n" +
                         "Mỗi đoạn tạo một khớp nối, giúp cành trông có nhiều tầng hơn.\n\n" +
                         "• 1 → cành xuống thẳng một đoạn từ arm_end đến trụ\n" +
                         "• 4 – mặc định, cành có 4 khớp dọc đường xuống\n" +
                         "• 8+ → cành mềm mại, nhiều khớp hơn"
                onValueEdited: manager.minLevels = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Max Merge Levels (số lần gộp tối đa)"
                value:   Math.round(manager.maxLevels * 10)
                from:    10; to: 500; stepSize: 10
                unit:    "lần"
                tooltip: "Số lần gộp cành tối đa trong greedy merge tree.\n" +
                         "Chỉ gộp khi hai đầu cành trong Branch Merge Distance.\n\n" +
                         "• 3–5 → ít lần gộp, cành ít hội tụ\n" +
                         "• 10 – mặc định\n" +
                         "• 20+ → cho phép nhiều lần gộp khi có nhiều điểm A gần nhau"
                onValueEdited: manager.maxLevels = v
                Layout.fillWidth: true
            }

            Rectangle { height: 1; color: "#ddd"; Layout.fillWidth: true; Layout.topMargin: 4; Layout.bottomMargin: 4 }

            // ══ 3. Trụ – Cylinder (object in được) ═══════════════════ //
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
                tooltip: "Các điểm B trong phạm vi này sẽ được gộp thành một hình trụ rỗng chung.\n" +
                         "Giúp tránh vẽ quá nhiều hình trụ chồng chéo lên nhau.\n\n" +
                         "• 2–3 mm → gộp rất ít, mỗi điểm B hầu như có trụ riêng\n" +
                         "• 5 mm – mặc định, gộp các điểm gần nhau thành nhóm hợp lý\n" +
                         "• 15+ mm → gộp mạnh, ít trụ hơn nhưng kích thước trụ lớn hơn"
                onValueEdited: manager.bClusterDist = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "B Gap to A (khoảng cách đỉnh trụ đến điểm A)"
                value:   Math.round(manager.bGapToA * 10)
                from:    0; to: 5000; stepSize: 50
                unit:    "mm"
                tooltip: "Khoảng trống giữa đỉnh trụ và điểm A gần nhất theo chiều ngang.\n" +
                         "Chiều cao trụ = A.y(gần nhất) − giá trị này.\n\n" +
                         "• 0 mm → trụ cao tới tận điểm A\n" +
                         "• 20 mm – mặc định: A ở 80 mm → trụ cao 60 mm\n" +
                         "• 50 mm → A ở 80 mm → trụ cao 30 mm (cành dài hơn)"
                onValueEdited: manager.bGapToA = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Max Base Area (diện tích đáy tối đa)"
                value:   Math.round(manager.maxBaseArea * 10)
                from:    100; to: 5000; stepSize: 50
                unit:    "mm²"
                tooltip: "Giới hạn diện tích đáy (π × r²) của hình trụ rỗng B.\n" +
                         "Khi cụm B rất rộng, bán kính ngoài bị cắt để không vượt giới hạn này.\n\n" +
                         "• 50 mm² → r_max ≈ 4.0 mm, trụ nhỏ gọn\n" +
                         "• 150 mm² – mặc định, r_max ≈ 6.9 mm\n" +
                         "• 300 mm² → r_max ≈ 9.8 mm, cho phép trụ rất rộng"
                onValueEdited: manager.maxBaseArea = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Wall Thickness (độ dày thành trụ rỗng)"
                value:   Math.round(manager.wallMm * 10)
                from:    1; to: 50; stepSize: 1
                unit:    "mm"
                tooltip: "Độ dày thành của hình trụ rỗng B (outer_r − inner_r).\n" +
                         "Giá trị thực tế = max(setting, line_width của Cura profile).\n\n" +
                         "• 0.5–0.8 mm → thành mỏng, tiết kiệm, nhưng khó thấy màu\n" +
                         "• 1.2 mm – mặc định, đủ dày để nhìn rõ trong viewport\n" +
                         "• 2–3 mm → thành dày, trụ trông rắn chắc hơn"
                onValueEdited: manager.wallMm = v
                Layout.fillWidth: true
            }
            SettingRow {
                label:   "Min Outer Radius (bán kính ngoài tối thiểu)"
                value:   Math.round(manager.minOuterR * 10)
                from:    5; to: 100; stepSize: 5
                unit:    "mm"
                tooltip: "Bán kính ngoài tối thiểu của hình trụ rỗng B, kể cả khi chỉ có một điểm.\n\n" +
                         "• 0.8–1.0 mm → trụ rất nhỏ, khó thấy\n" +
                         "• 1.5 mm – mặc định, vừa đủ nhìn thấy ở zoom bình thường\n" +
                         "• 3–5 mm → trụ to, dễ thấy nhưng có thể chồng lên model nhỏ"
                onValueEdited: manager.minOuterR = v
                Layout.fillWidth: true
            }

            Rectangle { height: 1; color: "#ddd"; Layout.fillWidth: true; Layout.topMargin: 6; Layout.bottomMargin: 6 }

            // ══ 4. Điểm B – Anchor Points (bàn in, dưới cùng) ═══════ //
            Label {
                text: "④ Điểm B  – Anchor Points (neo trên bàn in)"
                font.bold: true; color: "#2980b9"
                Layout.topMargin: 2
            }
            Label {
                text: "Điểm gốc của support trên bàn in (Y=0), nơi cành cây mọc lên từ trụ."
                color: "#888"; wrapMode: Text.WordWrap; Layout.fillWidth: true; font.pixelSize: 11
            }

            SettingRow {
                label:   "Base Plate Diameter (đường kính đế neo)"
                value:   Math.round(manager.baseDiameter * 10)
                from:    10; to: 500; stepSize: 5
                unit:    "mm"
                tooltip: "Đường kính đĩa đế (base plate) tại điểm B trên bàn in.\n" +
                         "Đế rộng giúp support bám sàn tốt hơn, ít bị lật khi in.\n\n" +
                         "• 5–8 mm → đế nhỏ, tiết kiệm vật liệu, phù hợp support đơn lẻ\n" +
                         "• 10–15 mm – cân bằng độ bám và vật liệu, dùng cho hầu hết model\n" +
                         "• 20+ mm → đế lớn, bám rất chắc, phù hợp model cao hoặc nặng\n\n" +
                         "Lưu ý: giá trị này chỉ dùng khi tạo mesh support thực tế (generate)."
                onValueEdited: manager.baseDiameter = v
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
