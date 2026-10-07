"""kolaymetin — Türkçe Kolay Dil / Sade Dil denetim aracı."""

__version__ = "1.0.0"

from kolaymetin.api import analyze
from kolaymetin.models import Finding, Fix, Report, apply_fixes

__all__ = ["Finding", "Fix", "Report", "__version__", "analyze", "apply_fixes"]
