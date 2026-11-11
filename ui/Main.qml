import QtQuick
import QtQuick.Window
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import QtQuick.Effects

ApplicationWindow {
    id: window
    visible: true
    width: 1440
    height: 810
    minimumWidth: 360
    minimumHeight: 260
    title: "Xóa nền ảnh"
    color: "#e4eaff"
    font.family: Qt.platform.os === "osx" ? "Helvetica Neue" : "Segoe UI"
    font.pixelSize: 13
    property color ink: "#25294a"
    property color muted: "#596480"
    property color accent: "#4e57dc"
    property int page: 0
    property int settingsTab: 0
    // Allow room for window borders and the taskbar around a quarter-screen tile.
    readonly property bool quarterScreen: Screen.width > 0 && Screen.height > 0
        && width <= Screen.width * 0.56 && height <= Screen.height * 0.56
    readonly property bool stacked: quarterScreen || width < 900
    readonly property bool compact: width < 760
    readonly property bool compactFooter: width < (quarterScreen ? 560 : 760)
    readonly property bool tiny: width < 520
    readonly property bool shortWindow: height < 620
    readonly property bool collapsedNavigation: quarterScreen || width < 1180
    readonly property int outerMargin: compact || quarterScreen ? 12 : 24

    onQuarterScreenChanged: {
        if (workspaceScroll && workspaceScroll.contentItem)
            workspaceScroll.contentItem.contentY = 0
    }

    onSettingsTabChanged: {
        if (settingsScroll && settingsScroll.contentItem)
            settingsScroll.contentItem.contentY = 0
    }

    onClosing: function(event) {
        if (controller.busy) {
            event.accepted = false
            closeDialog.open()
        }
    }

    component Copy: Text {
        color: window.ink
        font.pixelSize: 13
        renderType: Text.QtRendering
        elide: Text.ElideRight
        verticalAlignment: Text.AlignVCenter
    }

    component Glass: Item {
        id: pane
        property real corner: 26
        property point sampleOrigin: {
            // Resizing and scrolling keep the glass sample aligned with the backdrop.
            let dependency = window.width + window.height + x + y
                + (workspaceScroll.contentItem ? workspaceScroll.contentItem.contentY : 0)
            return mapToItem(backdrop, 0, 0)
        }
        Rectangle {
            x: 0; y: 5; width: parent.width; height: parent.height
            radius: pane.corner
            color: "#0c6264a0"
            antialiasing: true
        }
        ShaderEffectSource {
            id: sample
            visible: false
            sourceItem: backdrop
            sourceRect: Qt.rect(pane.sampleOrigin.x, pane.sampleOrigin.y, pane.width, pane.height)
            textureSize: Qt.size(Math.max(1, Math.ceil(pane.width / 2)), Math.max(1, Math.ceil(pane.height / 2)))
            live: true
        }
        Rectangle {
            id: roundedMask
            anchors.fill: parent
            radius: pane.corner
            color: "white"
            visible: false
            antialiasing: true
            layer.enabled: true
            layer.samples: 4
        }
        MultiEffect {
            anchors.fill: parent
            source: sample
            blurEnabled: true
            blurMax: 16
            blur: 0.65
            autoPaddingEnabled: false
            maskEnabled: true
            maskSource: roundedMask
        }
        Rectangle {
            anchors.fill: parent
            radius: pane.corner
            antialiasing: true
            border.width: 1
            border.color: "#c0ffffff"
            gradient: Gradient {
                GradientStop { position: 0; color: "#70ffffff" }
                GradientStop { position: 1; color: "#34ffffff" }
            }
        }
        Rectangle {
            anchors.fill: parent
            anchors.margins: 2
            radius: Math.max(1, pane.corner - 2)
            color: "transparent"
            border.color: "#48ffffff"
            border.width: 1
            antialiasing: true
        }
    }

    component Pill: Button {
        id: button
        property bool primary: false
        property bool selected: false
        hoverEnabled: true
        implicitHeight: 42
        implicitWidth: 120
        leftPadding: 16
        rightPadding: 16
        opacity: enabled ? 1 : 0.48
        scale: down ? 0.98 : 1
        Behavior on scale { NumberAnimation { duration: 110; easing.type: Easing.OutCubic } }
        Behavior on opacity { NumberAnimation { duration: 140 } }
        contentItem: Copy {
            text: button.text
            horizontalAlignment: Text.AlignHCenter
            font.weight: button.primary || button.selected ? Font.DemiBold : Font.Medium
            color: button.primary ? "white" : (button.selected ? window.accent : window.ink)
        }
        background: Rectangle {
            radius: height / 2
            antialiasing: true
            border.width: button.activeFocus ? 2 : 1
            border.color: button.activeFocus ? "#6c76ed" : "#c4ffffff"
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop {
                    position: 0
                    color: button.primary ? (button.hovered ? "#5175f2" : "#4263e3")
                                          : (button.selected ? "#e6e8ff" : (button.hovered ? "#b8ffffff" : "#62ffffff"))
                    Behavior on color { ColorAnimation { duration: 150 } }
                }
                GradientStop {
                    position: 1
                    color: button.primary ? (button.hovered ? "#9b68e3" : "#8354d7")
                                          : (button.selected ? "#f0eaff" : "#4effffff")
                    Behavior on color { ColorAnimation { duration: 150 } }
                }
            }
        }
    }

    component Field: TextField {
        id: field
        implicitHeight: 40
        color: window.ink
        selectionColor: "#adbafa"
        selectedTextColor: window.ink
        leftPadding: 13
        rightPadding: 13
        readOnly: controller.busy
        opacity: enabled ? 1 : 0.5
        background: Rectangle {
            radius: 13
            antialiasing: true
            color: field.activeFocus ? "#b8ffffff" : "#78ffffff"
            border.width: field.activeFocus ? 2 : 1
            border.color: field.activeFocus ? "#7b87ee" : "#aeffffff"
            Behavior on color { ColorAnimation { duration: 140 } }
        }
    }

    component Toggle: Switch {
        id: control
        implicitWidth: 46
        implicitHeight: 30
        padding: 0
        enabled: !controller.busy
        indicator: Rectangle {
            width: 44; height: 26
            y: (control.height - height) / 2
            radius: 13
            antialiasing: true
            color: control.checked ? "#707ee9" : "#a3b5c7e5"
            border.color: "#b3ffffff"
            Behavior on color { ColorAnimation { duration: 150 } }
            Rectangle {
                x: control.checked ? 21 : 3
                y: 3
                width: 20; height: 20
                radius: 10
                color: "white"
                antialiasing: true
                Behavior on x { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
            }
        }
        contentItem: Item {}
    }

    component Progress: Rectangle {
        radius: height / 2
        antialiasing: true
        color: "#365762a1"
        implicitHeight: 6
        Rectangle {
            width: Math.max(0, parent.width * controller.progress)
            height: parent.height
            radius: height / 2
            antialiasing: true
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0; color: "#637df0" }
                GradientStop { position: 1; color: "#a674e2" }
            }
            Behavior on width { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
        }
    }

    Item {
        id: backdrop
        anchors.fill: parent
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0; color: "#c9defb" }
                GradientStop { position: 0.48; color: "#e5eaff" }
                GradientStop { position: 1; color: "#d7d0f6" }
            }
        }
        Rectangle {
            width: parent.width * 0.68; height: parent.height * 1.5
            x: -width * 0.45; y: -height * 0.2
            radius: width / 2
            rotation: -25
            antialiasing: true
            gradient: Gradient {
                GradientStop { position: 0; color: "#44ffffff" }
                GradientStop { position: 1; color: "#669dc7ff" }
            }
        }
        Rectangle {
            width: parent.width * 0.8; height: parent.height * 0.7
            x: parent.width * 0.32; y: parent.height * 0.65
            radius: height / 2
            rotation: -16
            antialiasing: true
            gradient: Gradient {
                GradientStop { position: 0; color: "#90d7b5f3" }
                GradientStop { position: 1; color: "#12ffffff" }
            }
        }
        Rectangle {
            width: parent.width * 1.2; height: 88
            x: -40; y: parent.height * 0.47
            rotation: -18
            radius: 44
            antialiasing: true
            gradient: Gradient {
                GradientStop { position: 0; color: "#54ffffff" }
                GradientStop { position: 1; color: "#10ffffff" }
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: window.outerMargin
        spacing: window.compact ? 10 : 22
        Glass {
            visible: !window.collapsedNavigation
            Layout.preferredWidth: 64
            Layout.fillHeight: true
            corner: 30
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 8
                spacing: 12
                Pill {
                    text: "✦"; primary: true
                    Layout.fillWidth: true
                    Layout.topMargin: 10
                    implicitHeight: 46
                    onClicked: window.page = 0
                }
                Item { Layout.preferredHeight: 22 }
                Pill {
                    text: "Ảnh"; selected: window.page === 0
                    leftPadding: 6; rightPadding: 6
                    Layout.fillWidth: true
                    implicitHeight: 46
                    ToolTip.visible: hovered
                    ToolTip.text: "Không gian làm việc"
                    onClicked: window.page = 0
                }
                Pill {
                    text: "Log"; selected: window.page === 1
                    leftPadding: 6; rightPadding: 6
                    Layout.fillWidth: true
                    implicitHeight: 46
                    ToolTip.visible: hovered
                    ToolTip.text: "Nhật ký xử lý"
                    onClicked: window.page = 1
                }
                Item { Layout.fillHeight: true }
                Copy { text: "PNG"; color: window.muted; font.pixelSize: 10; Layout.alignment: Qt.AlignHCenter; Layout.bottomMargin: 16 }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumWidth: 0
            spacing: window.compact || window.shortWindow || window.quarterScreen ? 10 : 18
            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: window.quarterScreen ? 34 : (window.shortWindow ? 40 : 84)
                spacing: window.tiny ? 6 : 10
                ColumnLayout {
                    visible: !window.quarterScreen
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    spacing: 5
                    Copy { visible: !window.shortWindow; text: "PHOTO STUDIO"; color: window.accent; font.pixelSize: 10; font.weight: Font.DemiBold; font.letterSpacing: 1.6; Layout.fillWidth: true }
                    Copy { text: window.page === 0 ? "Xóa nền ảnh" : (window.compact ? "Nhật ký" : "Hoạt động xử lý"); font.pixelSize: window.compact || window.shortWindow ? 23 : 32; font.weight: Font.DemiBold; Layout.fillWidth: true }
                    Copy { visible: !window.shortWindow && !window.tiny; text: "Tách nền nhẹ nhàng. Giữ trọn từng chi tiết."; color: window.muted; Layout.fillWidth: true }
                }
                Pill { visible: window.collapsedNavigation; text: "Ảnh"; implicitWidth: 46; implicitHeight: 34; leftPadding: 6; rightPadding: 6; selected: window.page === 0; onClicked: window.page = 0 }
                Pill { visible: window.collapsedNavigation; text: "Log"; implicitWidth: 46; implicitHeight: 34; leftPadding: 6; rightPadding: 6; selected: window.page === 1; onClicked: window.page = 1; ToolTip.visible: hovered; ToolTip.text: "Nhật ký xử lý" }
                Pill {
                    visible: window.quarterScreen
                    text: "Thư mục"
                    implicitWidth: 90; implicitHeight: 34
                    leftPadding: 8; rightPadding: 8
                    enabled: !controller.busy
                    ToolTip.visible: hovered
                    ToolTip.text: controller.count + " ảnh · " + controller.options.input
                    onClicked: folderMenu.open()
                    Menu {
                        id: folderMenu
                        y: parent.height
                        MenuItem {
                            text: "Chọn thư mục ảnh gốc…"
                            onTriggered: { folderDialog.optionKey = "input"; folderDialog.currentFolder = controller.folderUrl("input"); folderDialog.open() }
                        }
                        MenuItem {
                            text: "Chọn nơi lưu kết quả…"
                            onTriggered: { folderDialog.optionKey = "output"; folderDialog.currentFolder = controller.folderUrl("output"); folderDialog.open() }
                        }
                    }
                }
                Item { visible: window.quarterScreen; Layout.fillWidth: true }
                Rectangle {
                    Layout.preferredWidth: window.compact ? 64 : Math.min(280, window.width * 0.24)
                    Layout.preferredHeight: window.shortWindow || window.quarterScreen ? 34 : 42
                    radius: 21; antialiasing: true
                    color: "#70ffffff"; border.color: "#c0ffffff"
                    RowLayout {
                        anchors.fill: parent; anchors.margins: window.compact ? 9 : 13; spacing: 6
                        Rectangle { width: 6; height: 6; radius: 3; antialiasing: true; color: controller.device.indexOf("GPU") >= 0 ? "#298775" : window.accent }
                        Copy { text: window.compact ? (controller.device.indexOf("GPU") >= 0 ? "GPU" : (controller.ready ? "CPU" : "…")) : controller.device; font.pixelSize: 10; Layout.fillWidth: true }
                    }
                    HoverHandler { id: deviceHover }
                    ToolTip.visible: deviceHover.hovered
                    ToolTip.text: controller.device
                }
            }

            ScrollView {
                id: workspaceScroll
                visible: window.page === 0
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 0
                clip: true
                contentWidth: availableWidth
                contentHeight: workspaceGrid.implicitHeight
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                GridLayout {
                    id: workspaceGrid
                    width: workspaceScroll.availableWidth
                    columns: window.stacked ? 1 : 2
                    columnSpacing: 20
                    rowSpacing: window.compact ? 14 : 20
                    ColumnLayout {
                        visible: !window.quarterScreen
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.preferredHeight: window.stacked ? -1 : Math.max(460, workspaceScroll.availableHeight)
                        spacing: 18
                        Glass {
                            Layout.fillWidth: true
                            Layout.fillHeight: !window.stacked
                            Layout.preferredHeight: window.stacked ? Math.max(window.tiny ? 290 : 250, Math.min(380, window.height * 0.45)) : -1
                            Layout.minimumHeight: window.tiny ? 290 : 230
                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: window.compact ? 16 : 20; spacing: 14
                                GridLayout {
                                    Layout.fillWidth: true
                                    columns: window.tiny ? 1 : 2
                                    rowSpacing: 8
                                    Copy { text: "Xem trước"; font.pixelSize: 18; font.weight: Font.DemiBold; Layout.fillWidth: true }
                                    RowLayout {
                                        spacing: 6
                                        Pill { text: "Ảnh gốc"; implicitWidth: 86; implicitHeight: 34; selected: controller.previewKind === "original"; onClicked: controller.selectPreview("original") }
                                        Pill { text: "Kết quả"; implicitWidth: 86; implicitHeight: 34; selected: controller.previewKind === "result"; onClicked: controller.selectPreview("result") }
                                    }
                                }
                                Item {
                                    id: previewArea
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    Rectangle {
                                        anchors.fill: parent; radius: 20; antialiasing: true
                                        color: "#eff1fc"
                                    }
                                    Item {
                                        id: photoContent
                                        anchors.fill: parent
                                        visible: false
                                        Rectangle {
                                            anchors.fill: parent
                                            color: "#f8f9ff"
                                            Grid {
                                                columns: Math.ceil(parent.width / 18)
                                                Repeater {
                                                    model: Math.ceil(photoContent.width / 18) * Math.ceil(photoContent.height / 18)
                                                    Rectangle {
                                                        required property int index
                                                        width: 18; height: 18
                                                        color: (index + Math.floor(index / Math.ceil(photoContent.width / 18))) % 2 ? "#e5e8f4" : "#f8f9ff"
                                                    }
                                                }
                                            }
                                        }
                                        Image {
                                            id: photograph
                                            anchors.fill: parent
                                            anchors.margins: 12
                                            source: controller.previewSource
                                            fillMode: Image.PreserveAspectFit
                                            asynchronous: true
                                            cache: false
                                            smooth: true
                                            mipmap: true
                                        }
                                    }
                                    Rectangle {
                                        id: photoMask
                                        anchors.fill: parent; radius: 20; color: "white"
                                        visible: false; antialiasing: true; layer.enabled: true; layer.samples: 4
                                    }
                                    MultiEffect {
                                        anchors.fill: parent
                                        source: photoContent
                                        visible: photograph.status === Image.Ready
                                        maskEnabled: true; maskSource: photoMask
                                        autoPaddingEnabled: false
                                    }
                                    Column {
                                        anchors.centerIn: parent
                                        width: parent.width - 24
                                        spacing: 13
                                        visible: photograph.status !== Image.Ready
                                        Copy { text: "✧"; font.pixelSize: 40; color: window.accent; anchors.horizontalCenter: parent.horizontalCenter }
                                        Copy { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: controller.previewKind === "result" ? "Chưa có ảnh kết quả" : "Ảnh của bạn, diện mạo mới"; font.pixelSize: window.tiny ? 14 : 17; font.weight: Font.DemiBold }
                                        Copy { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: controller.previewKind === "result" ? "Kết quả sẽ xuất hiện sau khi xóa nền." : "Chọn thư mục ảnh để bắt đầu."; color: window.muted; font.pixelSize: window.tiny ? 11 : 13 }
                                    }
                                }
                                Copy { text: controller.previewName; color: window.muted; font.pixelSize: 11; Layout.fillWidth: true }
                            }
                        }
                        Glass {
                            Layout.fillWidth: true
                            Layout.preferredHeight: folderContent.implicitHeight + (window.compact ? 32 : 40)
                            ColumnLayout {
                                id: folderContent
                                anchors.fill: parent; anchors.margins: window.compact ? 16 : 20; spacing: 7
                                RowLayout {
                                    Layout.fillWidth: true
                                    Copy { text: "Thư mục ảnh"; font.pixelSize: 16; font.weight: Font.DemiBold; Layout.fillWidth: true }
                                    Pill { text: controller.count + " ảnh  ↻"; implicitHeight: 28; implicitWidth: 90; enabled: controller.ready && !controller.busy; onClicked: controller.refresh() }
                                }
                                Copy { text: "Ảnh gốc"; color: window.muted; font.pixelSize: 11 }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Field { Layout.fillWidth: true; Layout.minimumWidth: 0; text: controller.options.input; onTextEdited: controller.setOption("input", text) }
                                    Pill { text: "Chọn…"; implicitWidth: 86; enabled: !controller.busy; onClicked: { folderDialog.optionKey = "input"; folderDialog.currentFolder = controller.folderUrl("input"); folderDialog.open() } }
                                }
                                Copy { text: "Lưu kết quả"; color: window.muted; font.pixelSize: 11 }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Field { Layout.fillWidth: true; Layout.minimumWidth: 0; text: controller.options.output; onTextEdited: controller.setOption("output", text) }
                                    Pill { text: "Chọn…"; implicitWidth: 86; enabled: !controller.busy; onClicked: { folderDialog.optionKey = "output"; folderDialog.currentFolder = controller.folderUrl("output"); folderDialog.open() } }
                                }
                            }
                        }
                    }

                    Glass {
                        Layout.fillWidth: window.stacked
                        Layout.preferredWidth: window.stacked ? -1 : Math.max(352, Math.min(420, window.width * 0.30))
                        Layout.preferredHeight: window.quarterScreen ? workspaceScroll.availableHeight : (window.stacked ? settingsContent.implicitHeight + (window.compact ? 32 : 44) : Math.max(460, workspaceScroll.availableHeight))
                        ColumnLayout {
                            id: settingsContent
                            anchors.fill: parent; anchors.margins: window.quarterScreen ? 12 : (window.compact ? 16 : 22); spacing: window.quarterScreen ? 8 : 14
                            Copy { visible: !window.quarterScreen; text: "Thiết lập của bạn"; font.pixelSize: 18; font.weight: Font.DemiBold }
                            Copy { visible: !window.quarterScreen; text: "Một vài lựa chọn, ảnh đẹp hơn."; color: window.muted; font.pixelSize: 12 }
                            RowLayout {
                                Layout.fillWidth: true
                                Pill { text: "Chế độ xử lý"; Layout.fillWidth: true; implicitHeight: window.quarterScreen ? 32 : 36; selected: window.settingsTab === 0; onClicked: window.settingsTab = 0 }
                                Pill { text: "Tùy chỉnh"; Layout.fillWidth: true; implicitHeight: window.quarterScreen ? 32 : 36; selected: window.settingsTab === 1; onClicked: window.settingsTab = 1 }
                            }
                            ScrollView {
                                id: settingsScroll
                                Layout.fillWidth: true
                                Layout.fillHeight: !window.stacked || window.quarterScreen
                                Layout.preferredHeight: window.stacked && !window.quarterScreen ? settingsOptions.implicitHeight : -1
                                Layout.minimumHeight: 0
                                clip: true
                                contentWidth: availableWidth
                                contentHeight: settingsOptions.implicitHeight
                                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                                ScrollBar.vertical.policy: window.stacked && !window.quarterScreen ? ScrollBar.AlwaysOff : ScrollBar.AsNeeded
                                ColumnLayout {
                                    id: settingsOptions
                                    width: settingsScroll.availableWidth
                                    height: implicitHeight
                                    spacing: window.quarterScreen ? 8 : 18
                                    ColumnLayout {
                                        visible: window.settingsTab === 0
                                        Layout.fillWidth: true
                                        spacing: window.quarterScreen ? 8 : 18
                                        GridLayout {
                                            columns: window.quarterScreen && settingsScroll.availableWidth >= 520 ? 3 : 2
                                            columnSpacing: window.quarterScreen ? 8 : 10
                                            rowSpacing: window.quarterScreen ? 6 : 10
                                            Layout.fillWidth: true
                                            Repeater {
                                                model: controller.modeItems
                                                Button {
                                                    id: modeButton
                                                    required property int index
                                                    required property var modelData
                                                    property bool selected: controller.options.mode === index
                                                    Layout.fillWidth: true
                                                    Layout.minimumWidth: 0
                                                    Layout.preferredHeight: window.quarterScreen ? 36 : 76
                                                    hoverEnabled: true
                                                    enabled: !controller.busy
                                                    ToolTip.visible: hovered
                                                    ToolTip.text: modelData.title + " · " + modelData.detail
                                                    onClicked: controller.setOption("mode", index)
                                                    background: Rectangle {
                                                        radius: window.quarterScreen ? 12 : 18; antialiasing: true
                                                        color: modeButton.selected ? "#b9e5e5ff" : (modeButton.hovered ? "#a0ffffff" : "#60ffffff")
                                                        border.width: modeButton.selected || modeButton.activeFocus ? 2 : 1
                                                        border.color: modeButton.selected || modeButton.activeFocus ? "#9299ee" : "#b3ffffff"
                                                        Behavior on color { ColorAnimation { duration: 140 } }
                                                    }
                                                    contentItem: ColumnLayout {
                                                        spacing: 6
                                                        Copy { text: (modeButton.selected ? "✓  " : "") + modeButton.modelData.title; font.pixelSize: 12; font.weight: Font.DemiBold; color: modeButton.selected ? window.accent : window.ink; Layout.fillWidth: true }
                                                        Copy { visible: !window.quarterScreen; text: modeButton.modelData.detail; color: window.muted; font.pixelSize: 10; wrapMode: Text.WordWrap; elide: Text.ElideNone; Layout.fillWidth: true }
                                                    }
                                                    leftPadding: 12; rightPadding: 12; topPadding: window.quarterScreen ? 6 : 11; bottomPadding: window.quarterScreen ? 6 : 11
                                                }
                                            }
                                        }
                                        GridLayout {
                                            Layout.fillWidth: true
                                            columns: window.quarterScreen ? 2 : 1
                                            columnSpacing: 8; rowSpacing: 8
                                            Copy { text: "MODEL AI"; color: window.muted; font.pixelSize: 10; font.weight: Font.DemiBold; font.letterSpacing: 1 }
                                            ComboBox {
                                                id: modelBox
                                                Layout.fillWidth: true
                                                Layout.minimumWidth: 0
                                                implicitHeight: window.quarterScreen ? 34 : 42
                                                enabled: !controller.busy
                                                model: controller.modelItems
                                                currentIndex: controller.options.model
                                                onActivated: controller.setOption("model", currentIndex)
                                                contentItem: Copy { text: modelBox.displayText; leftPadding: 13; rightPadding: 30 }
                                                background: Rectangle { radius: 13; antialiasing: true; color: "#88ffffff"; border.color: modelBox.activeFocus ? "#7c87ed" : "#aaffffff" }
                                            }
                                        }
                                        Copy { visible: !window.quarterScreen; text: "Chọn chế độ phù hợp với ảnh. Khung hình và nền nằm ở Tùy chỉnh."; color: window.muted; font.pixelSize: 12; wrapMode: Text.WordWrap; elide: Text.ElideNone; Layout.fillWidth: true }
                                    }
                                    ColumnLayout {
                                        visible: window.settingsTab === 1
                                        Layout.fillWidth: true
                                        spacing: window.quarterScreen ? 10 : 22
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Copy { text: "Cắt sát chủ thể"; Layout.fillWidth: true; Layout.minimumWidth: 0 }
                                            Field { text: controller.options.pad; Layout.preferredWidth: 48; enabled: controller.options.crop; onTextEdited: controller.setOption("pad", text) }
                                            Copy { text: "%"; color: window.muted }
                                            Toggle { checked: controller.options.crop; onToggled: controller.setOption("crop", checked) }
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Copy { text: "Khung vuông"; Layout.fillWidth: true }
                                            Toggle { checked: controller.options.square; onToggled: controller.setOption("square", checked) }
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Copy { text: "Kích thước"; Layout.fillWidth: true; Layout.minimumWidth: 0 }
                                            Field { text: controller.options.size; Layout.preferredWidth: 108; enabled: controller.options.size_on; onTextEdited: controller.setOption("size", text) }
                                            Toggle { checked: controller.options.size_on; onToggled: controller.setOption("size_on", checked) }
                                        }
                                        Copy { text: "NỀN KẾT QUẢ"; color: window.muted; font.pixelSize: 10; font.weight: Font.DemiBold; font.letterSpacing: 1 }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Repeater {
                                                model: [{ label: "Trong suốt", value: "trong", swatch: "#cbd0e5" }, { label: "Trắng", value: "trang", swatch: "#ffffff" }, { label: "Màu khác", value: "khac", swatch: "#c3a2ea" }]
                                                Button {
                                                    id: backgroundButton
                                                    required property var modelData
                                                    Layout.fillWidth: true
                                                    implicitHeight: window.quarterScreen ? 60 : 84
                                                    enabled: !controller.busy
                                                    property bool selected: controller.options.bg === modelData.value
                                                    onClicked: controller.setOption("bg", modelData.value)
                                                    background: Rectangle { radius: 18; antialiasing: true; color: backgroundButton.selected ? "#c4e7e3ff" : "#60ffffff"; border.color: backgroundButton.selected ? "#8d97e9" : "#a8ffffff"; border.width: backgroundButton.selected ? 2 : 1 }
                                                    contentItem: ColumnLayout {
                                                        spacing: window.quarterScreen ? 4 : 9
                                                        Rectangle { Layout.alignment: Qt.AlignHCenter; width: 26; height: 26; radius: 13; color: backgroundButton.modelData.swatch; border.color: "white"; border.width: 2; antialiasing: true }
                                                        Copy { text: backgroundButton.modelData.label; font.pixelSize: 10; color: backgroundButton.selected ? window.accent : window.muted; Layout.alignment: Qt.AlignHCenter }
                                                    }
                                                }
                                            }
                                        }
                                        Field { visible: controller.options.bg === "khac"; Layout.fillWidth: true; text: controller.options.color; placeholderText: "RGB · ví dụ 255,255,255"; onTextEdited: controller.setOption("color", text) }
                                        Copy { visible: controller.options.bg !== "khac"; text: controller.options.bg === "trong" ? "Xuất PNG với nền trong suốt." : "Xuất PNG với nền trắng."; color: window.muted; font.pixelSize: 12 }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Copy { text: "Ghi đè ảnh đã xử lý"; Layout.fillWidth: true }
                                            Toggle { checked: controller.options.overwrite; onToggled: controller.setOption("overwrite", checked) }
                                        }
                                    }
                                    Item { visible: !window.quarterScreen; Layout.preferredHeight: 6 }
                                }
                            }
                        }
                    }
                }
            }

            Glass {
                visible: window.page === 1
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 0
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: window.shortWindow ? 10 : 24; spacing: window.shortWindow ? 8 : 16
                    RowLayout {
                        Layout.fillWidth: true
                        Copy { text: "Nhật ký xử lý"; font.pixelSize: window.shortWindow ? 14 : 20; font.weight: Font.DemiBold; Layout.fillWidth: true }
                        Copy { text: Math.round(controller.progress * 100) + "%"; color: window.accent; font.weight: Font.DemiBold }
                    }
                    Copy { visible: !window.shortWindow; text: controller.status; color: window.muted; Layout.fillWidth: true }
                    Progress { visible: !window.shortWindow; Layout.fillWidth: true }
                    ScrollView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.minimumHeight: 0
                        TextArea {
                            id: logArea
                            text: controller.logs || "Nhật ký sẽ xuất hiện khi bạn bắt đầu xóa nền."
                            readOnly: true
                            selectByMouse: true
                            wrapMode: TextArea.Wrap
                            color: window.ink
                            font.family: Qt.platform.os === "osx" ? "Menlo" : "Consolas"
                            font.pixelSize: 12
                            padding: 14
                            background: Rectangle { color: "#65ffffff"; radius: 16; antialiasing: true }
                            onTextChanged: cursorPosition = length
                        }
                    }
                }
            }

            Glass {
                Layout.fillWidth: true
                Layout.preferredHeight: window.compactFooter ? 104 : (window.quarterScreen ? 64 : 80)
                Layout.minimumHeight: window.compactFooter ? 104 : (window.quarterScreen ? 64 : 80)
                GridLayout {
                    anchors.fill: parent; anchors.margins: window.quarterScreen ? 8 : (window.compactFooter ? 12 : 16)
                    columns: window.compactFooter ? 3 : 4
                    columnSpacing: window.compactFooter ? 8 : 12
                    rowSpacing: 8
                    Pill { Layout.row: 0; Layout.column: 0; Layout.fillWidth: window.compactFooter; Layout.minimumWidth: window.compact || window.quarterScreen ? 90 : 196; text: window.compact || window.quarterScreen ? "✦ Xóa nền" : "✦  Bắt đầu xóa nền"; primary: true; implicitWidth: window.compact || window.quarterScreen ? 128 : 196; implicitHeight: window.compact || window.quarterScreen ? 40 : 48; leftPadding: window.compact || window.quarterScreen ? 10 : 16; rightPadding: window.compact || window.quarterScreen ? 10 : 16; enabled: controller.ready && !controller.busy; onClicked: controller.start() }
                    Pill { Layout.row: 0; Layout.column: 1; text: "Dừng"; implicitWidth: window.compact || window.quarterScreen ? 62 : 76; implicitHeight: window.compact || window.quarterScreen ? 40 : 48; leftPadding: 10; rightPadding: 10; enabled: controller.busy && !controller.stopping; onClicked: controller.stop() }
                    ColumnLayout {
                        Layout.row: window.compactFooter ? 1 : 0
                        Layout.column: window.compactFooter ? 0 : 2
                        Layout.columnSpan: window.compactFooter ? 3 : 1
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.leftMargin: window.compactFooter ? 0 : 6; Layout.rightMargin: window.compactFooter ? 0 : 6
                        spacing: window.compactFooter ? 6 : 10
                        Copy { text: controller.status; color: window.muted; font.pixelSize: 11; Layout.fillWidth: true; Layout.minimumWidth: 0; ToolTip.visible: statusHover.hovered; ToolTip.text: controller.status; HoverHandler { id: statusHover } }
                        Progress { Layout.fillWidth: true; implicitHeight: 5 }
                    }
                    Pill { Layout.row: 0; Layout.column: window.compactFooter ? 2 : 3; text: window.compact || window.quarterScreen ? "Kết quả ↗" : "Mở thư mục kết quả  ↗"; implicitWidth: window.compact || window.quarterScreen ? 106 : 180; implicitHeight: window.compact || window.quarterScreen ? 40 : 48; leftPadding: window.compact || window.quarterScreen ? 10 : 16; rightPadding: window.compact || window.quarterScreen ? 10 : 16; ToolTip.visible: hovered; ToolTip.text: "Mở thư mục kết quả"; onClicked: controller.openOutput() }
                }
            }
        }
    }

    FolderDialog {
        id: folderDialog
        property string optionKey: "input"
        title: optionKey === "input" ? "Chọn thư mục ảnh gốc" : "Chọn nơi lưu kết quả"
        onAccepted: controller.setFolder(optionKey, selectedFolder)
    }
    Dialog {
        id: errorDialog
        property string detail: ""
        title: "Không thể thực hiện"
        modal: true
        anchors.centerIn: parent
        width: Math.min(540, window.width - 80)
        standardButtons: Dialog.Ok
        contentItem: Copy { text: errorDialog.detail; wrapMode: Text.WordWrap; elide: Text.ElideNone }
    }
    Dialog {
        id: closeDialog
        title: "Đang xử lý ảnh"
        modal: true
        anchors.centerIn: parent
        standardButtons: Dialog.Yes | Dialog.No
        contentItem: Copy { text: "Đóng ứng dụng và dừng xử lý?" }
        onAccepted: { controller.stop(); Qt.quit() }
    }
    Connections {
        target: controller
        function onErrorOccurred(message) { errorDialog.detail = message; errorDialog.open() }
    }
    Shortcut { sequence: "Ctrl+Return"; enabled: controller.ready && !controller.busy; onActivated: controller.start() }
    Shortcut { sequence: "Ctrl+O"; enabled: !controller.busy; onActivated: { folderDialog.optionKey = "input"; folderDialog.currentFolder = controller.folderUrl("input"); folderDialog.open() } }
}
