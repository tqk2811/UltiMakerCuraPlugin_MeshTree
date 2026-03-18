import os

from UM.Extension import Extension
from UM.Logger import Logger
from UM.i18n import i18nCatalog
from UM.Scene.Selection import Selection

from cura.CuraApplication import CuraApplication

try:
    from PyQt6.QtCore import QObject, pyqtSlot, pyqtProperty, pyqtSignal
except ImportError:
    from PyQt5.QtCore import QObject, pyqtSlot, pyqtProperty, pyqtSignal

i18n_catalog = i18nCatalog("cura")


class MeshTreeSupportPlugin(Extension, QObject):

    settingsChanged = pyqtSignal()

    def __init__(self, parent=None):
        Extension.__init__(self)
        QObject.__init__(self, parent)

        self._app    = CuraApplication.getInstance()
        self._dialog = None

        self._settings = {
            "support_angle":         50.0,
            "branch_angle":          40.0,
            "tip_diameter":           1.0,
            "branch_diameter":        3.0,
            "branch_diameter_angle":  5.0,
            "base_diameter":          7.0,
            "layer_height":           0.2,
            "merge_threshold":        2.0,
            # Marker visualisation
            "b_cluster_dist":         5.0,
            "b_gap_to_a":           200.0,   # mm – cylinder top stops this far below A
            "max_base_area":        150.0,
            "wall_mm":                1.2,
            "min_outer_r":            1.5,
        }

        self.setMenuName(i18n_catalog.i18nc("@item:inmenu", "MeshTree Support"))
        self.addMenuItem(i18n_catalog.i18nc("@item:inmenu", "Settings and Generate"), self._showDialog)

        self._autoLoad()
        Logger.log("d", "[MeshTreeSupportPlugin] Plugin loaded.")

    # ------------------------------------------------------------------ #
    #  QML properties                                                      #
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

    @pyqtProperty(float, notify=settingsChanged)
    def bClusterDist(self):
        return self._settings["b_cluster_dist"]

    @bClusterDist.setter
    def bClusterDist(self, value):
        if self._settings["b_cluster_dist"] != value:
            self._settings["b_cluster_dist"] = value
            self.settingsChanged.emit()

    @pyqtProperty(float, notify=settingsChanged)
    def bGapToA(self):
        return self._settings["b_gap_to_a"]

    @bGapToA.setter
    def bGapToA(self, value):
        if self._settings["b_gap_to_a"] != value:
            self._settings["b_gap_to_a"] = value
            self.settingsChanged.emit()

    @pyqtProperty(float, notify=settingsChanged)
    def maxBaseArea(self):
        return self._settings["max_base_area"]

    @maxBaseArea.setter
    def maxBaseArea(self, value):
        if self._settings["max_base_area"] != value:
            self._settings["max_base_area"] = value
            self.settingsChanged.emit()

    @pyqtProperty(float, notify=settingsChanged)
    def wallMm(self):
        return self._settings["wall_mm"]

    @wallMm.setter
    def wallMm(self, value):
        if self._settings["wall_mm"] != value:
            self._settings["wall_mm"] = value
            self.settingsChanged.emit()

    @pyqtProperty(float, notify=settingsChanged)
    def minOuterR(self):
        return self._settings["min_outer_r"]

    @minOuterR.setter
    def minOuterR(self, value):
        if self._settings["min_outer_r"] != value:
            self._settings["min_outer_r"] = value
            self.settingsChanged.emit()

    # ------------------------------------------------------------------ #
    #  QML slots                                                           #
    # ------------------------------------------------------------------ #

    @pyqtSlot(result=str)
    def markOverhangs(self) -> str:
        """
        Detect overhang faces on selected (or all) mesh nodes,
        compute A/B contact pairs, inject cylinder markers into the scene.
        Returns a status message for the UI.
        """
        from .core.OverhangDetector   import OverhangDetector
        from .core.ContactPointFinder import ContactPointFinder
        from .scene.MarkerInjector    import MarkerInjector

        # ── Get target nodes ─────────────────────────────────────── #
        nodes = [n for n in Selection.getAllSelectedObjects() if n.getMeshData()]
        if not nodes:
            scene = self._app.getController().getScene()
            nodes = [
                n for n in scene.getRoot().getChildren()
                if n.getMeshData() is not None
                and n.getName() not in ("MeshTree_MarkerA", "MeshTree_MarkerB")
            ]
        if not nodes:
            return "No mesh objects found in scene."

        detector = OverhangDetector(
            support_angle_deg=self._settings["support_angle"]
        )
        finder = ContactPointFinder(
            branch_angle_deg=self._settings["branch_angle"],
            merge_threshold =self._settings["merge_threshold"],
        )
        # Read minimum printable wall from Cura (line_width), fallback 0.4 mm
        min_wall = 0.4
        stack = self._app.getGlobalContainerStack()
        if stack:
            try:
                min_wall = float(stack.getProperty("line_width", "value") or 0.4)
            except Exception:
                pass

        injector = MarkerInjector(
            layer_height   = self._settings["layer_height"],
            b_cluster_dist = self._settings["b_cluster_dist"],
            b_gap_to_a     = self._settings["b_gap_to_a"],
            max_base_area  = self._settings["max_base_area"],
            wall_mm        = self._settings["wall_mm"],
            min_wall_mm    = min_wall,
            min_outer_r    = self._settings["min_outer_r"],
        )

        all_faces = []
        for node in nodes:
            faces = detector.detect(node)
            Logger.log("d", "[MeshTreeSupportPlugin] Node '%s': %d overhang faces", node.getName(), len(faces))
            all_faces.extend(faces)

        if not all_faces:
            return f"No overhang faces found (angle > {self._settings['support_angle']}°).\nTry lowering the support angle."

        pairs = finder.find(all_faces)
        pairs = ContactPointFinder.exclude_near_footprint(pairs, nodes, exclusion_radius=10.0)
        injector.inject(pairs)

        return (
            f"Found {len(all_faces)} overhang faces → "
            f"{len(pairs)} contact pairs (after 10 mm footprint exclusion).\n"
            f"A markers (contact, on overhang): {len(pairs)}\n"
            f"B markers (anchor, build plate):  {len(pairs)}"
        )

    @pyqtSlot(result=str)
    def saveSettings(self) -> str:
        from .core.SettingsStore import SettingsStore
        return SettingsStore.save(self._settings)

    @pyqtSlot(result=str)
    def loadSettings(self) -> str:
        from .core.SettingsStore import SettingsStore
        data = SettingsStore.load()
        if data is None:
            return "No saved settings found."
        for k, v in data.items():
            if k in self._settings:
                self._settings[k] = float(v)
        self.settingsChanged.emit()
        return "Settings loaded."

    @pyqtSlot()
    def clearMarkers(self) -> None:
        from .scene.MarkerInjector import MarkerInjector
        MarkerInjector().clear()

    @pyqtSlot()
    def syncFromCura(self):
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
        for local_key, cura_key in mapping.items():
            try:
                val = stack.getProperty(cura_key, "value")
                if val is not None:
                    self._settings[local_key] = float(val)
            except Exception as e:
                Logger.log("w", "[MeshTreeSupportPlugin] Could not read %s: %s", cura_key, e)
        self.settingsChanged.emit()

    @pyqtSlot()
    def generate(self):
        Logger.log("i", "[MeshTreeSupportPlugin] Generate called – pipeline not yet implemented.")

    @pyqtSlot(result=str)
    def getModuleStatus(self):
        lines = []
        modules = [
            ("core.SupportSettings",    "SupportSettings"),
            ("core.OverhangDetector",   "OverhangDetector"),
            ("core.ContactPointFinder", "ContactPointFinder"),
            ("core.BranchBuilder",      "BranchBuilder"),
            ("core.TreeMeshGenerator",  "TreeMeshGenerator"),
            ("scene.SceneNodeInjector", "SceneNodeInjector"),
            ("scene.MarkerInjector",    "MarkerInjector"),
        ]
        for mod_path, label in modules:
            try:
                __import__("MeshTreeSupportPlugin." + mod_path)
                lines.append("OK  " + label)
            except ImportError as e:
                lines.append("ERR " + label + "  (" + str(e) + ")")
            except Exception as e:
                lines.append("?   " + label + "  (" + str(e) + ")")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    #  Dialog                                                              #
    # ------------------------------------------------------------------ #

    def _autoLoad(self):
        from .core.SettingsStore import SettingsStore
        data = SettingsStore.load()
        if data:
            for k, v in data.items():
                if k in self._settings:
                    self._settings[k] = float(v)

    def _showDialog(self):
        if self._dialog is None:
            self._dialog = self._createDialog()
        if self._dialog:
            self._dialog.show()

    def _createDialog(self):
        qml_path = os.path.join(os.path.dirname(__file__), "ui", "TreeSupportDialog.qml")
        dialog   = self._app.createQmlComponent(qml_path, {"manager": self})
        if dialog is None:
            Logger.log("e", "[MeshTreeSupportPlugin] Failed to create dialog from %s", qml_path)
            return None
        main_window = self._app.getMainWindow()
        if main_window:
            dialog.setProperty("transientParent", main_window)
        return dialog
