import importlib

__all__ = ["listener"]


def __getattr__(name):
    if name == "listener":
        mod = importlib.import_module(f"{__name__}.listener")
        globals()[name] = mod
        return mod
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
