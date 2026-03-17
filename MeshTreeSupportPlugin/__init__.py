from .MeshTreeSupportPlugin import MeshTreeSupportPlugin


def getMetaData():
    return {}


def register(app):
    return {"extension": MeshTreeSupportPlugin()}
