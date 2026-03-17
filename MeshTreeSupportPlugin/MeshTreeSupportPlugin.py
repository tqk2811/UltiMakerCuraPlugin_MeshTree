import os

from UM.Extension import Extension
from UM.Logger import Logger
from UM.i18n import i18nCatalog

from cura.CuraApplication import CuraApplication

try:
    from PyQt6.QtCore import QObject, pyqtSlot, pyqtProperty, pyqtSignal, QUrl
    from PyQt6.QtQml import QQmlComponent, QQmlContext
except ImportError:
    from PyQt5.QtCore import QObject, pyqtSlot, pyqtProperty, pyqtSignal, QUrl
    from PyQt5.QtQml import QQmlComponent, QQmlContext

i18n_catalog = i18nCatalog("cura")


class MeshTreeSupportPlugin(Extension, QObject):
    """
    Main plugin entry point. Registers a menu under Extensions > MeshTree Support.
    """

    settingsChanged = pyqtSignal()

    def __init__(self, parent=None):
        Extension.__init__(self)
        QObject.__init__(self, parent)

        self._app = CuraApplication.getInstance()
        self._dialog = None

        # Default settings
        self._settings = {
            "support_angle":         50.0,   # overhang angle threshold (degrees)
            "branch_angle":          40.0,   # max branch angle from vertical (degrees)
            "tip_diameter":           1.0,   # mm
            "branch_diameter":        3.0,   # mm
            "branch_diameter_angle":  5.0,   # degrees, how fast branch widens
            "base_diameter":          7.0,   # mm, base plate diameter
            "layer_height":           0.2,   # mm (read from Cura stack)
            "merge_threshold":        2.0,   # mm, distance to merge branches
        }

        self.setMenuName(i18n_catalog.i18nc("@item:inmenu", "MeshTree Support"))
        self.addMenuItem(i18n_catalog.i18nc("@item:inmenu", "Settings && Generate"), self._showDialog)

        Logger.log("d", "[MeshTreeSupportPlugin] Plugin loaded.")

    # ------------------------------------------------------------------ #
    #  QML-exposed properties                                              #
    # ------------------------------------------------------------------ #

    @pyqtProperty(float, notify=settingsChanged)
    def supportAngle(self):
        return self._settings["support_angle"]

    @supportAngle.setter
    def supportAngle(self, value):
        if self._settings["support_angle"] != value:
            self._settings["support_angle"] = value
            self.settingsChanged.emit()

    @pyqtProperty(float, notify=settingsChanged)
    def branchAngle(self):
        return self._settings["branch_angle"]

    @branchAngle.setter
    def branchAngle(self, value):
        if self._settings["branch_angle"] != value:
            self._settings["branch_angle"] = value
            self.settingsChanged.emit()

    @pyqtProperty(float, notify=settingsChanged)
    def tipDiameter(self):
        return self._settings["tip_diameter"]

    @tipDiameter.setter
    def tipDiameter(self, value):
        if self._settings["tip_diameter"] != value:
            self._settings["tip_diameter"] = value
            self.settingsChanged.emit()

    @pyqtProperty(float, notify=settingsChanged)
    def branchDiameter(self):
        return self._settings["branch_diameter"]

    @branchDiameter.setter
    def branchDiameter(self, value):
        if self._settings["branch_diameter"] != value:
            self._settings["branch_diameter"] = value
            self.settingsChanged.emit()

    @pyqtProperty(float, notify=settingsChanged)
    def branchDiameterAngle(self):
        return self._settings["branch_diameter_angle"]

    @branchDiameterAngle.setter
    def branchDiameterAngle(self, value):
        if self._settings["branch_diameter_angle"] != value:
            self._settings["branch_diameter_angle"] = value
            self.settingsChanged.emit()

    @pyqtProperty(float, notify=settingsChanged)
    def baseDiameter(self):
        return self._settings["base_diameter"]

    @baseDiameter.setter
    def baseDiameter(self, value):
        if self._settings["base_diameter"] != value:
            self._settings["base_diameter"] = value
            self.settingsChanged.emit()

    @pyqtProperty(float, notify=settingsChanged)
    def mergeThreshold(self):
        return self._settings["merge_threshold"]

    @mergeThreshold.setter
    def mergeThreshold(self, value):
        if self._settings["merge_threshold"] != value:
            self._settings["merge_threshold"] = value
            self.settingsChanged.emit()

    # ------------------------------------------------------------------ #
    #  Slots called from QML                                               #
    # ------------------------------------------------------------------ #

    @pyqtSlot()
    def syncFromCura(self):
        """Read matching settings from the active Cura print profile."""
        stack = self._app.getGlobalContainerStack()
        if stack is None:
            Logger.log("w", "[MeshTreeSupportPlugin] No active container stack.")
            return

        mapping = {
            "support_angle":         "support_angle",
            "branch_angle":          "support_tree_angle",
            "tip_diameter":          "support_tree_tip_diameter",
            "branch_diameter":       "support_tree_branch_diameter",
            "branch_diameter_angle": "support_tree_branch_diameter_angle",
            "base_diameter":         "support_tree_bp_diameter",
            "layer_height":          "layer_height",
        }
        changed = False
        for local_key, cura_key in mapping.items():
            try:
                val = stack.getProperty(cura_key, "value")
                if val is not None:
                    self._settings[local_key] = float(val)
                    changed = True
            except Exception as e:
                Logger.log("w", "[MeshTreeSupportPlugin] Could not read %s: %s", cura_key, e)

        if changed:
            self.settingsChanged.emit()
        Logger.log("d", "[MeshTreeSupportPlugin] Synced settings from Cura: %s", self._settings)

    @pyqtSlot()
    def generate(self):
        """Placeholder – will call the pipeline in later phases."""
        Logger.log("i", "[MeshTreeSupportPlugin] Generate called with settings: %s", self._settings)
        # TODO: wire up OverhangDetector → ContactPointFinder → BranchBuilder → TreeMeshGenerator

    @pyqtSlot(result=str)
    def getModuleStatus(self):
        """Return a status string showing which core modules are importable."""
        lines = []
        modules = [
            ("core.SupportSettings",    "SupportSettings"),
            ("core.OverhangDetector",   "OverhangDetector"),
            ("core.ContactPointFinder", "ContactPointFinder"),
            ("core.BranchBuilder",      "BranchBuilder"),
            ("core.TreeMeshGenerator",  "TreeMeshGenerator"),
            ("scene.SceneNodeInjector", "SceneNodeInjector"),
        ]
        for mod_path, label in modules:
            try:
                full = "MeshTreeSupportPlugin." + mod_path
                __import__(full)
                lines.append("✓  " + label)
            except ImportError as e:
                lines.append("✗  " + label + "  (" + str(e) + ")")
            except Exception as e:
                lines.append("?  " + label + "  (" + str(e) + ")")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    #  Dialog                                                              #
    # ------------------------------------------------------------------ #

    def _showDialog(self):
        if self._dialog is None:
            self._dialog = self._createDialog()
        if self._dialog:
            self._dialog.show()

    def _createDialog(self):
        qml_path = os.path.join(os.path.dirname(__file__), "ui", "TreeSupportDialog.qml")
        dialog = self._app.createQmlComponent(qml_path, {"manager": self})
        if dialog is None:
            Logger.log("e", "[MeshTreeSupportPlugin] Failed to create dialog from %s", qml_path)
        return dialog
