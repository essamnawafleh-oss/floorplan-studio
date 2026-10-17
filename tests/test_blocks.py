import ezdxf

from floorplan.blocks import BUILTIN, BlockLibrary, blocks_from_dxf, furniture_polylines


def test_builtin_blocks_have_geometry():
    assert {"std/bed_double", "std/wc", "std/door_single", "std/win_single"} <= set(BUILTIN)
    for b in BUILTIN.values():
        lines = furniture_polylines(b, 1.0, 2.0, 90, 1.0)
        assert lines and all(len(pl) >= 2 for pl in lines), b.id


def test_import_dxf_blocks_in_mm(tmp_path):
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 4                  # millimetres
    blk = doc.blocks.new("CHAIR")
    blk.add_lwpolyline([(0, 0), (450, 0), (450, 500), (0, 500)], close=True)
    blk.add_circle((225, 250), 100)
    doc.modelspace().add_blockref("CHAIR", (0, 0))
    path = tmp_path / "chair.dxf"
    doc.saveas(path)
    blocks = blocks_from_dxf(str(path), "furniture")
    assert len(blocks) == 1
    b = blocks[0]
    assert abs(b.width - 0.45) < 1e-6 and abs(b.depth - 0.5) < 1e-6
    lib = BlockLibrary(str(tmp_path / "lib"))
    lib.add(b)
    lib2 = BlockLibrary(str(tmp_path / "lib"))
    assert lib2.get(b.id).width == b.width
    lib2.add(blocks_from_dxf(str(path), "furniture")[0])        # same name -> new id, no overwrite
    assert len([x for x in lib2.blocks if x.startswith("user/CHAIR")]) == 2
