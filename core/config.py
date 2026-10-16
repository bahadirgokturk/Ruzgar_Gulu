"""config/defaults.yaml dosyasını okuyan yardımcı."""
from pathlib import Path
from typing import Any

import yaml

DEFAULTS_PATH = Path(__file__).resolve().parent.parent / "config" / "defaults.yaml"


def load_defaults(path: Path = DEFAULTS_PATH) -> dict[str, Any]:
    """Varsayılan değerleri sözlük olarak döndürür."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
