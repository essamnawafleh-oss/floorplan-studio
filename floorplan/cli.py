"""Command line:  python -m floorplan examples/family.json --seeds 1 2 3 --out out/"""

from __future__ import annotations

import argparse
import json
import os

from . import design
from .export import to_dxf, to_glb, to_obj, to_svg


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="floorplan", description="Rule-based floor plan generator")
    ap.add_argument("config", help="project JSON file")
    ap.add_argument("--seeds", type=int, nargs="+", default=[1], help="one plan per seed")
    ap.add_argument("--out", default="out", help="output folder")
    ap.add_argument("--lang", default=None, choices=["ar", "en", "both"], help="labels on drawings")
    ap.add_argument("--candidates", type=int, default=400, help="layouts tried per seed")
    ap.add_argument("--formats", nargs="+", default=["svg", "dxf", "glb", "json"],
                    choices=["svg", "dxf", "glb", "obj", "json"])
    args = ap.parse_args(argv)

    with open(args.config, encoding="utf-8") as f:
        config = json.load(f)
    lang = args.lang or config.get("lang", "both")
    os.makedirs(args.out, exist_ok=True)
    base = os.path.splitext(os.path.basename(args.config))[0]

    for seed in args.seeds:
        plan = design(config, seed=seed, candidates=args.candidates)
        stem = os.path.join(args.out, f"{base}_seed{seed}")
        if "svg" in args.formats:
            with open(stem + ".svg", "w", encoding="utf-8") as f:
                f.write(to_svg(plan, lang=lang))
        if "dxf" in args.formats:
            to_dxf(plan, stem + ".dxf", lang=config.get("dxf_lang", "en"))
        if "glb" in args.formats:
            to_glb(plan, stem + ".glb")
        if "obj" in args.formats:
            to_obj(plan, stem + ".obj")
        if "json" in args.formats:
            with open(stem + ".json", "w", encoding="utf-8") as f:
                json.dump(plan.to_dict(), f, ensure_ascii=False, indent=2)
        print(f"seed {seed}: {plan.width} x {plan.depth} m, {len(plan.rooms)} rooms, score {plan.score:.1f} -> {stem}.*")
        for w in plan.warnings:
            print("   !", w["en"], "|", w["ar"])


if __name__ == "__main__":
    main()
