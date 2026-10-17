"""Quick numbers: wall lengths, openings, glazing ratio per room."""

ADDON = {"name": "Wall & glazing summary", "description": "Wall lengths and window-to-floor ratio", "version": "1.0"}


def register(api):
    api.add_action("Wall & glazing summary", lambda: show(api))


def show(api):
    plan = api.plan
    if plan is None:
        return
    q = api.quantities()
    b = q["blocks"]
    lines = [f"Exterior walls: {b['ext_length']:.2f} m", f"Interior walls: {b['int_length']:.2f} m", ""]
    for r in plan.rooms:
        glass = sum(o.width * (o.head - o.sill) for o in plan.openings if o.kind == "window" and r.id in o.rooms)
        if r.net.area > 0 and r.spec.type != "corridor":
            lines.append(f"{r.spec.name_en}: windows {glass:.2f} m2 = {100 * glass / r.net.area:.0f}% of floor")
    api.message("\n".join(lines))
