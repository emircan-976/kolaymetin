"""kolaymetin — Türkçe Kolay Dil / Sade Dil denetim aracı."""

__version__ = "1.0.0"

from kolaymetin.api import analyze
from kolaymetin.models import Finding, Report

__all__ = ["Finding", "Report", "__version__", "analyze"]
