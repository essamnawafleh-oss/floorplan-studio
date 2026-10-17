"""Room schedule as a CSV file (opens in Excel)."""

ADDON = {"name": "Room schedule (CSV)", "description": "Exports every room with its size and area", "version": "1.0"}


def register(api):
    api.add_action("Room schedule → CSV", lambda: export(api))


def export(api):
    plan = api.plan
    if plan is None:
        return
    path = api.save_file("Room schedule", "CSV (*.csv)")
    if not path:
        return
    rows = ["Room,Name (AR),Width m,Length m,Area m2"]
    for r in plan.rooms:
        rows.append(f"{r.spec.name_en},{r.spec.name_ar},{r.net.w:.2f},{r.net.h:.2f},{r.net.area:.2f}")
    rows.append(f"Total,,,,{plan.net_area:.2f}")
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(rows))
    api.status(f"Saved {path}")
