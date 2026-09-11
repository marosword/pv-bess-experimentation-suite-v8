# result blocks, tmp first se mos prishet good file
from __future__ import annotations

import gzip
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

from .class_model import (
    CLASS_MEMBERS,
    CLASS_MODEL_DIGEST,
    REPRESENTATIVES,
    expanded_count,
)


SCHEMA_VERSION=1; # compact output version


def canonical_sha256(value)->str:
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),
           allow_nan=False).encode("utf-8");
    return (sha256(raw).hexdigest())


def catalogue(experiment)->dict[str,object]:
    en=experiment.enumeration;
    if (not en.complete or en.invalid_selections) :
        raise ValueError("compact records need complete class enumeration")
    pats0=[]
    for x in en.critical_sets:
        pats0.append(tuple(x.candidate_ids))
    pats=tuple(pats0)
    n = expanded_count(pats)
    dig = canonical_sha256( #class map include
        {
            "certificate": CLASS_MODEL_DIGEST,
            "classes": tuple(zip(REPRESENTATIVES, CLASS_MEMBERS)),
            "patterns": pats,
        }
    )
    out={"digest": dig, 'patterns': pats,
         "expanded_candidate_sets":n}
    return out


def temporal_record(run,baseline,experiment,checkpoint_id:str)->tuple[dict,dict|None]:
    cat = (
        catalogue(experiment) if experiment is not None else None
    )
    return (
        {
            'checkpoint_id': checkpoint_id, "onset_index": run.onset_index,
            "onset_timestamp_utc": run.onset_timestamp_utc.isoformat(),
            'baseline_status': baseline.status.value,
            "baseline_reason": baseline.reason,
            "enumeration_state": "complete"
            if experiment is not None
            else "not_enumerated",
            "catalogue_digest": cat['digest']
            if cat
            else None,
            'healthy_mode': run.healthy_mode.value,
            "healthy_branch_soc":run.healthy_branch_soc,
        },
        cat,
    )


def direction_fields(run, direction: str) -> dict[str, object]:
    sc=run.scenario; p0=sc.points[0]
    return {
        "initial_profile_power": sc.initial_profile_power,
        "held_pv": p0.availability.capability.pv_availability,
        "discharge_efficiency": p0.availability.feasibility.discharge_efficiency,
        "target_power": sc.points[-1].target_power,
        "rate": getattr(
            sc.rates, f"run_{direction}"
        ).rates_per_minute[0],
    }


def block_path(root:Path,group:dict[str,str])->Path:
    return root.joinpath("records",group["family"], group["site_id"],
       group["variant_id"],f'{group["mission_case"]}.json.gz')


def write_block(
    root: Path,
    group: dict[str, str],
    records: list[dict],
    catalogues: dict[str, dict],
) -> Path:
    p=block_path(root,group); p.parent.mkdir(parents=True,exist_ok=True) 
    blob = { 
        'schema_version': SCHEMA_VERSION,
        "class_model_digest": CLASS_MODEL_DIGEST,
        'group': group, "record_count": len(records),
        "records": records,
        'catalogues': [catalogues[key] for key in sorted(catalogues)],
    }
    blob["content_sha256"]=canonical_sha256(blob); #hash payload
    # partial writes never replace good output
    tmp=p.with_name(f".{p.name}.{uuid4().hex}.tmp")
    with gzip.open(tmp,"wt",encoding="utf-8") as f: json.dump(blob,f,sort_keys=True,allow_nan=False)
    tmp.replace(p); return p


def load_block(path:Path)->dict:
    with gzip.open(path,"rt",encoding="utf-8") as f: data=json.load(f)
    # reject incomplete or mismatched blocks
    dig=data.pop("content_sha256",None);
    if data.get("schema_version") != SCHEMA_VERSION: raise ValueError(f"{path}: unsupported compact schema")
    if (data.get("class_model_digest") != CLASS_MODEL_DIGEST):
        raise ValueError(f"{path}: class model mismatch")
    if dig != canonical_sha256(data):
        raise ValueError(f"{path}: content digest mismatch")
    data["content_sha256"] = dig
    if data.get("record_count") != len(data.get("records", ())): raise ValueError(f"{path}: record count mismatch")
    return data


def load_blocks(root:Path)->list[dict]:
    ps=sorted((root/"records").rglob("*.json.gz"));
    if not ps: raise ValueError(f"no compact records below {root}")
    return ([load_block(p) for p in ps])
