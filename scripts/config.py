"""Pipeline configuration from pipeline.toml at the repository root."""
import tomllib

from aoi import ROOT

with open(ROOT / "pipeline.toml", "rb") as f:
    CONFIG = tomllib.load(f)

ELEVATION = CONFIG["elevation"]
