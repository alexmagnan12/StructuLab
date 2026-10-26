"""StructLab : identification, décomposition et pricing de produits structurés."""
from .analytics import analyze
from .report import build_termsheet
from .spec import load_spec

__all__ = ["load_spec", "analyze", "build_termsheet"]
__version__ = "1.0"
