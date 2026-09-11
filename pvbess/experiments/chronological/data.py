# Renewables.ninja PV data, Pfenninger and Staffell (2016)
from __future__ import annotations
import csv; from datetime import datetime
import json
from pathlib import Path
from .models import PvTimeSeries, PvTimeSeriesPoint


class RenewablesNinjaLoader:
    def load(self, path: str | Path, site_id: str) -> PvTimeSeries:
        p0 = Path(path)
        raw = p0.read_text(encoding='utf-8-sig').splitlines()
        # capacity blob is in the comment bit
        h = next(x for x in raw if x.startswith('# {'))
        cap = float(
            json.loads(h[1:].strip())["params"]["capacity"]
        )
        rows0 = tuple(
            x for x in raw if not x.startswith("#")
        )
        rr = csv.DictReader(rows0)
        has_missing = "missing" in (rr.fieldnames or ())
        out = tuple(
            PvTimeSeriesPoint(
                timestamp_utc=datetime.strptime(
                    x["time"], "%Y-%m-%d %H:%M"
                ),
                capacity_factor=float(x["electricity"]) / cap,
                source_missing=has_missing and x["missing"] == "1",
            )
            for x in rr
        )
        return PvTimeSeries(site_id, out)
