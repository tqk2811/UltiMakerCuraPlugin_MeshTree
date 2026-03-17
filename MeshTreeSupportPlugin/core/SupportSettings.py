"""
SupportSettings – reads tree-support related settings from the active Cura container stack.
Stub: ready for implementation.
"""
from UM.Logger import Logger


class SupportSettings:
    """
    Wraps the Cura global container stack and exposes tree-support parameters
    as typed Python attributes.
    """

    CURA_KEYS = {
        "support_angle":              ("support_angle",                    50.0),
        "branch_angle":               ("support_tree_angle",               40.0),
        "tip_diameter":               ("support_tree_tip_diameter",         1.0),
        "branch_diameter":            ("support_tree_branch_diameter",      3.0),
        "branch_diameter_angle":      ("support_tree_branch_diameter_angle",5.0),
        "base_diameter":              ("support_tree_bp_diameter",          7.0),
        "layer_height":               ("layer_height",                      0.2),
    }

    def __init__(self, override: dict = None):
        self._values = {k: default for k, (_, default) in self.CURA_KEYS.items()}
        if override:
            self._values.update(override)

    @classmethod
    def from_cura_stack(cls, stack) -> "SupportSettings":
        instance = cls()
        for local_key, (cura_key, default) in cls.CURA_KEYS.items():
            try:
                val = stack.getProperty(cura_key, "value")
                if val is not None:
                    instance._values[local_key] = float(val)
            except Exception as e:
                Logger.log("w", "[SupportSettings] Could not read %s: %s", cura_key, e)
        return instance

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(f"SupportSettings has no attribute '{name}'")

    def __repr__(self):
        return f"SupportSettings({self._values})"
