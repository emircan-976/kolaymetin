"""Vercel giriş noktası: Vercel kök dizindeki index.py içinde `app` adlı FastAPI nesnesini arar.

Paket src/ düzeninde olduğundan, kurulu olmasa da içe aktarılabilsin diye src/ yola eklenir.
Yerelde bu dosya gerekmez; `kolaymetin sunucu` yeterlidir.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from kolaymetin.web.app import app

__all__ = ["app"]
