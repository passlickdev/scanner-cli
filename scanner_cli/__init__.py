from importlib.metadata import version as _pkg_version, PackageNotFoundError as _PkgNotFound

try:
    __version__ = _pkg_version("scanner-cli")
except _PkgNotFound:
    __version__ = "dev"

__all__ = ["__version__"]
