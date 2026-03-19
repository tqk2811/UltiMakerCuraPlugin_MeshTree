from . import OverhangSupportPlugin


def getMetaData():
    return {}


def register(app):
    return {"extension": OverhangSupportPlugin.OverhangSupportPlugin()}
