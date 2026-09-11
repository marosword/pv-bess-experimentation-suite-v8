# Split runs into stable shards
from __future__ import annotations

import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

from pvbess.experiments.harness import ExperimentDefinition
from pvbess.experiments.chronological.baseline import (
    FAILURE_DURATION_SWEEP_HOURS,
)
from pvbess.experiments.chronological.controller import (
    ChronologicalSmoothingController,
)
from pvbess.experiments.chronological.failures import (
    HourlyFailureInsertionRunner,
)
from pvbess.experiments.chronological.inputs import load, sample_onsets
from pvbess.experiments.chronological.mission_runner import (
    ChronologicalMissionFailureRunner,
)
from pvbess.experiments.chronological.study import (
    _declared_reactive_envelope_builders,
    _onset_plan,
    _temporal_builders_for_variant,
    _temporal_mission_builders,
)
from pvbess.experiments.chronological.sweeps import (
    SweepFamily,
    build_controlled_sweep,
)
from pvbess.graph import MODEL_ID

from .class_model import (
    CLASS_MEMBERS,
    CLASS_MODEL_DIGEST,
    ClassCriticalSetHarness,
)
from .records import (
    block_path,
    catalogue,
    direction_fields,
    load_block,
    temporal_record,
    write_block,
)


def group_key(family: SweepFamily, site: str,
    variant, mission: str) -> dict[str, str]:
    # one block, dont move the keys
    return {
        'family': family.value, "universe_id": "combined",
        "site_id": site,
        'variant_id': variant.variant_id, "mission_case": mission,
    }


def selected_group(
    group:dict[str,str], shard_count: int,
                   shard_index:int
) -> bool:
    # enable reruns qe mund te perseriten njesoj
    txt='/'.join(group[key] for key in
            ("family",'site_id', "variant_id",'mission_case'))
    n = int.from_bytes(sha256(txt.encode("utf-8")).digest()[:8],
                                          "big");
    return (n % shard_count == shard_index)


def existing_block(
    output:Path,group:dict[str,str],expected_records:int
)->bool:
    p=block_path(output, group);
    # dont rerun a finished block
    if not(p.exists()): return False
    old = load_block(p)
    if (old["group"] != group):
        raise ValueError(f"{p}: group identity mismatch")
    got=old["record_count"]
    if got != expected_records:
        raise ValueError(
            f"{p}: has {got} records, expected {expected_records}; "
            "smoke and full outputs cannot be mixed"
        )
    print(f"SKIP {p.relative_to(output)}", flush=True)
    return True


def run_temporal_group(
    output: Path,
    group: dict[str, str],
    variant,
    onsets: tuple[int, ...],
    chronology,
    active_runner,
    mission_runner,
    builders,
) -> None:
    if existing_block(output, group, len(onsets)):
        return
    cats = {}; rows=[]; m=group['mission_case']
    # M1 ka own runner se window vazhdon
    if (m == "mission_1_active_power") :
        runs = active_runner.run(
            chronology,
            variant.failure_duration_hours,
            variant.variant_id,
            "combined",
            onsets,
        )
        basefn=lambda run:(run.experiment.enumeration.baseline)
    else:
        runs = mission_runner.run(
            chronology,
            builders[m],
            variant.variant_id,
            "combined",
            onsets,
        )
        basefn = lambda run:run.baseline_assessment
    # pull direction from the reference ramp cases
    way={"mission_2_ramp_down_rate_0p05":"down",
     "mission_2_ramp_up_rate_0p05": "up",}.get(m)
    # reuse repeated catalogues by digest
    for r in runs:
        row, cat = temporal_record(
            r,
            basefn(r),
            r.experiment,
            f"{r.onset_timestamp_utc:%Y%m%dT%H%M}Z",
        )
        if way: row["direction"] = direction_fields(r, way)
        row0=row
        rows.append(row0)
        if cat: cats[cat['digest']] = cat
    write_block(output, group, rows, cats)
    print(
        "DONE "
        + "/".join(
            group[key]
            for key in (
                "family",
                "site_id",
                "variant_id",
                "mission_case",
            )
        )
        + f" records={len(rows)}",
        flush=True,
    )


def run_static_groups(
    output: Path,
    family: SweepFamily,
    variants,
    harness,
    shard_count: int,
    shard_index: int,
) -> None:
    # only once here
    picked = next(
        (
            x
            for x in variants
            if x.runs_declared_reactive_envelope
        ),
        None,
    )
    if picked is None:
        return
    #keep each envelope case separate
    for (
        m,
        mk,
    ) in _declared_reactive_envelope_builders().items():
        g = group_key(
            family, "declared_reference", picked, m
        )
        if not selected_group(g, shard_count, shard_index):
            continue
        if existing_block(output, g, 1):
            continue
        sc = mk.build_declared(
            picked.baseline_configuration()
        )
        #avoid scenario ids colliding across sweeps
        sc = replace(
            sc,
            scenario_id=f"{sc.scenario_id}_{picked.variant_id}_combined",
        )
        out = harness.run(
            ExperimentDefinition(scenario=sc)
        )
        cat = catalogue(out)
        row = {
            'checkpoint_id': "declared_state", "onset_index": None,
            "onset_timestamp_utc":None,
            "baseline_status": out.enumeration.baseline.status.value,
            'baseline_reason': out.enumeration.baseline.reason,
            "enumeration_state":'complete',
            "catalogue_digest": cat["digest"],
            'healthy_mode': None, "healthy_branch_soc": None,
        }
        write_block(
            output, g, [row], {cat["digest"]: cat}
        )
        print(
            f"DONE {family.value}/declared_reference/{m}",
            flush=True,
        )


def run_study(
    input_path: Path,
    output: Path,
    families: tuple[SweepFamily, ...],
    smoke: bool,
    shard_count: int,
    shard_index: int,
) -> None:
    decl,sites=load(input_path); h=ClassCriticalSetHarness()
    ar=HourlyFailureInsertionRunner(h); mr=ChronologicalMissionFailureRunner(h)
    ctrl = ChronologicalSmoothingController()
    build=_temporal_mission_builders();
    # all families use the declared sample
    picks = sample_onsets(decl, sites)
    bysite = {x.site_year_id: x for x in picks}
    cache = {}
    for fam in families:
        vv = build_controlled_sweep(fam)
        # smoke mode keeps the check small
        for sy in (sites[:1] if smoke else sites) :
            sid = sy.declaration.site_year_id
            for v in vv:
                cfg = v.baseline_configuration()
                key=(sid,v.bess_duration_hours,
                                    v.smoothing_window_hours)
                # chronology varet vetem nga duration dhe window, mos e bo solve prap kot
                if key not in cache:
                    cache[key] = ctrl.simulate(
                        sy.series, cfg
                    )
                ch = replace(
                    cache[key],
                    configuration=cfg,
                )
                # mission list osht ndryshe per sweep, mos i fut krejt kot
                mb = _temporal_builders_for_variant(
                    v, build
                )
                # drop onsets without enough future data
                plan = _onset_plan(
                    ch,
                    v.failure_duration_hours,
                    mb,
                    smoke,
                    active_comparison_terminal_hours=max(
                        FAILURE_DURATION_SWEEP_HOURS
                    )
                    if fam is SweepFamily.FAILURE_DURATION
                    else None,
                    selected_onset_indices=None
                    if smoke
                    else bysite[sid].onset_indices,
                )
                for m,onset in plan.items() :
                    g = group_key(
                        fam, sid, v, m
                    )
                    if not selected_group( #avoid worker override
                        g, shard_count, shard_index
                    ):
                        continue
                    run_temporal_group(
                        output,
                        g,
                        v,
                        onset,
                        ch,
                        ar,
                        mr,
                        build,
                    )
        run_static_groups(
            output,
            fam,
            vv,
            h,
            shard_count,
            shard_index,
        )
    # ruaj setup with each shard
    fam0=[]
    for x in families: fam0.append(x.value) #name conciliation 
    meta = {
        'schema_version': 1,
        "input_declaration_sha256": sha256(
            input_path.read_bytes()
        ).hexdigest(),
        "graph_model_id": MODEL_ID, 'failure_universe': "combined",
        "class_model_digest": CLASS_MODEL_DIGEST,
        'class_members': CLASS_MEMBERS,
        "families": fam0, 'smoke': smoke,
        "shard_count": shard_count,
        'shard_index': shard_index,
    }
    (output / "shards").mkdir(parents=True, exist_ok=True)
    (output / "shards" / f"shard_{shard_index:03d}.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

# cli inputs -> check shard -> choose sweeps -> run exp
def main()->None:
    ap=argparse.ArgumentParser();
    ap.add_argument("--input-declaration",type=Path,required=True); ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--smoke",action="store_true")
    ap.add_argument("--shard-count", type=int, default=1); ap.add_argument("--shard-index",type=int,default=0)
    ap.add_argument(
        "--families",
        nargs="+",
        choices=("all", *(family.value for family in SweepFamily)),
        default=("all",),
    )
    a = ap.parse_args()
    if ((a.shard_count < 1)
            or not (0 <= a.shard_index < a.shard_count)) :
        ap.error("shard index must be in [0, shard count)")
    ff = (
        tuple(SweepFamily)
        if "all" in a.families
        else tuple(SweepFamily(x) for x in a.families)
    )
    run_study(
        a.input_declaration.resolve(),
        a.output.resolve(),
        ff,
        a.smoke,
        a.shard_count,
        a.shard_index,
    )


if (__name__ == "__main__") : main()