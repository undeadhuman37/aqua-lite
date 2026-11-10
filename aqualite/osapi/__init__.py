"""Everything that talks to the operating system, behind one small interface.

    from . import osapi
    osapi.paste(text, cfg)        # Windows: winapi.py; macOS: mac.py (PyObjC); elsewhere: other.py (does nothing)

The module for this system is imported the first time a name is used, so importing osapi is free and Windows
never imports PyObjC (nor macOS comtypes). other.py lists the whole interface.
"""
import importlib
import sys

if sys.platform == "win32":
    NAME = "win"
elif sys.platform == "darwin":
    NAME = "mac"
else:
    NAME = "other"

IS_WIN, IS_MAC = NAME == "win", NAME == "mac"
SUPPORTED = NAME != "other"   # can type into other apps, read their text boxes, listen for global shortcuts

_impl = None


def impl():
    """The module for this system (win, mac or other)."""
    global _impl
    if _impl is None:
        _impl = importlib.import_module("." + NAME, __name__)
    return _impl


def __getattr__(name):
    if name.startswith("__"):
        raise AttributeError(name)
    return getattr(impl(), name)
