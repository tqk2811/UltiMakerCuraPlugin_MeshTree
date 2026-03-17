from .MeshTreeSupportExtension import MeshTreeSupportExtension


def getMetaData() -> dict:
    return {}


def register(app) -> dict:
    return {"extension": MeshTreeSupportExtension()}
