# Stable monthly sampling with SHA-256
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
from pathlib import Path

from .data import RenewablesNinjaLoader
from .models import PvTimeSeries


@dataclass(frozen=True)
class Sampling:
    method: str
    seed: str
    days_per_month: int
    terminal_hours: int
    missing_lookback: int
    missing_forward: int


@dataclass(frozen=True)
class Site:
    site_year_id: str
    year: int
    path: Path


@dataclass(frozen=True)
class Declaration:
    sampling: Sampling


@dataclass(frozen=True)
class LoadedSite:
    declaration: Site
    series: PvTimeSeries


@dataclass(frozen=True)
class OnsetSample:
    site_year_id: str
    onset_indices: tuple[int, ...]


def load(
    path: str | Path,
) -> tuple[Declaration, tuple[LoadedSite, ...]]:
    # read all this straight off json data file
    p0 = Path(path).resolve(strict=True); raw = json.loads(p0.read_text(encoding="utf-8"))
    s0 = raw["sampling"]
    miss = s0["source_missing_policy"]
    ss = Sampling(
        s0["method"],
        s0["seed"],
        int(s0["days_per_month"]),
        int(s0["common_terminal_hours"]),
        int(miss["lookback_hours"]),
        int(miss["forward_hours"]),
    )
    things = tuple(
        Site(
            x["site_year_id"],
            int(x["expected_year"]),
            (p0.parent / x["source"]).resolve(strict=True),
        )
        for x in raw["site_years"]
    )
    dec = Declaration(ss)
    ld = RenewablesNinjaLoader()
    out = tuple(
        LoadedSite(x, ld.load(x.path, x.site_year_id))
        for x in things
    )
    return dec, out


def sample_onsets(
    declaration: Declaration, loaded: tuple[LoadedSite, ...]
) -> tuple[OnsetSample, ...]:
    out = []
    for item in loaded: out.append(_sample(item, declaration.sampling))
    return tuple(out)


def _sample(loaded: LoadedSite, sampling: Sampling) -> OnsetSample:
    pp = loaded.series.points
    d0: dict[date, list[int]] = defaultdict(list)
    for ii, p in enumerate(pp):
        d0[p.timestamp_utc.date()].append(ii)
    m0: dict[int, list[date]] = defaultdict(list)
    for dd, ix in sorted(d0.items()):
        if len(ix) != 24 or tuple(
            pp[ii].timestamp_utc.hour for ii in ix
        ) != tuple(range(24)):
            raise ValueError(f"{dd}: incomplete UTC day")
        if ix[-1] + sampling.terminal_hours >= len(pp):
            continue
        a = ix[0] - sampling.missing_lookback
        b = ix[0] + sampling.missing_forward
        if any(
            pp[ii % len(pp)].source_missing
            for ii in range(a, b)
        ):
            continue
        m0[dd.month].append(dd)
    picked = []
    # same dates cdo here
    for mm in range(1, 13):
        rr = sorted(
            (
                sha256(
                    "\x1f".join(
                        (
                            sampling.method,
                            sampling.seed,
                            str(loaded.declaration.year),
                            f"{mm:02d}",
                            dd.isoformat(),
                        )
                    ).encode()
                ).hexdigest(),
                dd,
            )
            for dd in m0[mm]
        )
        if len(rr) < sampling.days_per_month:
            raise ValueError(
                f"month {mm}: insufficient eligible days"
            )
        picked.extend(
            dd for _, dd in rr[: sampling.days_per_month]
        )
    return OnsetSample(
        loaded.declaration.site_year_id,
        tuple(
            ii for dd in sorted(picked) for ii in d0[dd]
        ),
    )
