"""Image / PDF -> plan: a plan drawn as an image must come back as the same plan."""
import json
import os

import pytest

cv2 = pytest.importorskip("cv2")

from floorplan import design
from floorplan.trace import Options, analyse, auto_scale, from_array, from_door, from_line, read, synth, to_plan
from floorplan.trace.labels import parse, room_type_from_text
from floorplan.trace.source import TextToken

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PPM = 60


@pytest.fixture(scope="module")
def plan():
    with open(os.path.join(ROOT, "examples", "family.json"), encoding="utf-8") as f:
        return design(json.load(f), seed=1, candidates=80)


def _match(orig, traced, tol):
    for r in orig.rooms:
        cx, cy = r.net.center
        hit = [q for q in traced.rooms if q.net.x0 <= cx <= q.net.x1 and q.net.y0 <= cy <= q.net.y1]
        assert len(hit) == 1, r.id
        assert abs(hit[0].net.area - r.net.area) <= tol * r.net.area + 0.2, (r.id, r.net.area, hit[0].net.area)


def test_parse_numbers_and_names():
    assert parse("4.20").values == (4.2,)
    assert parse("420").values == (4.2,)
    assert parse("4200").values == (4.2,)
    assert parse("3.60x4.00").kind == "pair"
    assert parse("12.5 m2").kind == "area"
    assert parse("SCALE 1:100").values == (100,)
    assert parse("2") is None                       # a room number, not a length
    assert room_type_from_text("BEDR00M 2") == "bedroom"
    assert room_type_from_text("MASTER BATH") == "ensuite"
    assert room_type_from_text("مطبخ") == "kitchen"


def test_filled_walls_round_trip(plan):
    img = synth.render(plan, PPM, labels=False, dims=False)
    a = analyse(from_array(img))
    assert len(a.regions) == len(plan.rooms)
    out = to_plan(a, 1 / PPM)
    assert abs(out.width - plan.width) < 0.1 and abs(out.depth - plan.depth) < 0.1
    assert out.settings["exterior_wall"] == pytest.approx(plan.settings["exterior_wall"])
    assert out.settings["interior_wall"] == pytest.approx(plan.settings["interior_wall"])
    _match(plan, out, 0.04)
    kinds = [o.kind for o in out.openings]
    assert kinds.count("door") == sum(o.kind == "door" for o in plan.openings)
    assert kinds.count("main_door") == 1
    assert kinds.count("window") == sum(o.kind == "window" for o in plan.openings)
    assert out.edited and any(e["layer"] == "A-FURN" for e in out.drawing)
    assert not any("unreached" in str(w) for w in out.warnings)


def test_outline_walls(plan):
    img = synth.render(plan, PPM, labels=False, dims=False, outline=True)
    a = analyse(from_array(img))
    assert a.style == "outline"
    assert len(a.regions) >= len(plan.rooms) - 1


def test_scale_from_door_line_and_dimension(plan):
    img = synth.render(plan, PPM, labels=False, dims=False)
    a = analyse(from_array(img))
    door = from_door(a, 0.9)
    assert door.scale == pytest.approx(1 / PPM, rel=0.04)
    assert from_line(120, 2.0) == pytest.approx(1 / PPM)
    # an overall dimension written under the building
    x0, y0, x1, y1 = a.bbox
    src = from_array(img)
    src.texts = [TextToken(f"{plan.width:.2f}", ((x0 + x1) / 2 - 30, y1 + 25, (x0 + x1) / 2 + 30, y1 + 45), "pdf")]
    a2 = analyse(src)
    mode, res = auto_scale(a2)
    assert mode == "dims" and res.scale == pytest.approx(1 / PPM, rel=0.01)


def test_tilted_scan_is_straightened(plan):
    img = synth.render(plan, PPM, labels=False, dims=False)
    h, w = img.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), 2.0, 1.0)
    tilted = cv2.warpAffine(img, M, (w, h), borderValue=255)
    a = analyse(from_array(tilted))
    assert abs(abs(a.angle) - 2.0) < 0.3
    assert len(a.regions) == len(plan.rooms)


def test_auto_openings_and_types(plan):
    img = synth.render(plan, PPM, labels=False, dims=False)
    a = analyse(from_array(img))
    types = {r.label: "bedroom" for r in a.regions}
    out = to_plan(a, 1 / PPM, types, options=Options(openings="auto", furniture=False))
    assert out.drawing == []
    assert any(o.kind == "main_door" for o in out.openings)
    assert {r.spec.type for r in out.rooms} == {"bedroom"}


def test_ocr_reads_labels(plan):
    from floorplan.trace import ocr
    if "rapidocr" not in ocr.engines():
        pytest.skip("RapidOCR not installed")
    img = synth.render(plan, PPM, labels=True, dims=True)
    a = read(from_array(img))
    guessed = {r.guess for r in a.regions}
    assert {"kitchen", "living", "dining", "corridor"} <= guessed
    mode, res = auto_scale(a)
    assert mode == "dims" and res.scale == pytest.approx(1 / PPM, rel=0.02)


def test_pdf_text_and_scale(tmp_path, plan):
    pdfium = pytest.importorskip("pypdfium2")
    pytest.importorskip("reportlab")
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    from floorplan.trace import load
    img = synth.render(plan, PPM, labels=False, dims=False)
    png = tmp_path / "p.png"
    cv2.imwrite(str(png), img)
    pdf = tmp_path / "p.pdf"
    h, w = img.shape
    c = canvas.Canvas(str(pdf), pagesize=(w * 0.75, h * 0.75 + 40))
    c.drawImage(ImageReader(str(png)), 0, 40, w * 0.75, h * 0.75)
    c.drawString(20, 15, "Kitchen 1:100")
    c.save()
    src = load(str(pdf), dpi=96)
    assert src.dpi and any("Kitchen" in t.text for t in src.texts)
    a = analyse(src)
    assert len(a.regions) == len(plan.rooms)
