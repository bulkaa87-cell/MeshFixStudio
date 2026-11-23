"""Write a small STEP test file with OpenCASCADE (OCP).

Two named solids in millimetres:
- "block": a box 10 x 20 x 30 at the origin (volume 6000 mm³),
- "pin": a cylinder with radius 5 and height 20 at x = 40 (volume 1570.8).

    python tests/make_step.py out.step
"""

import sys

BLOCK_VOLUME = 6000.0
PIN_VOLUME = 3.141592653589793 * 5.0 ** 2 * 20.0


def make_step(path: str) -> str:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_AsIs
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    from meshfix import cad
    cad._quiet()                       # no OpenCASCADE text on the console
    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    app.InitDocument(doc)
    XCAFDoc_DocumentTool.SetLengthUnit_s(doc, 0.001)
    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    block = BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()
    pin = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(40.0, 0.0, 0.0), gp_Dir(0.0, 0.0, 1.0)),
        5.0, 20.0).Shape()
    for shape, name in ((block, "block"), (pin, "pin")):
        label = tool.AddShape(shape, False)
        TDataStd_Name.Set_s(label, TCollection_ExtendedString(name))
    writer = STEPCAFControl_Writer()
    writer.SetNameMode(True)
    if not writer.Transfer(doc, STEPControl_AsIs):
        raise RuntimeError("STEP transfer failed")
    if writer.Write(path) != IFSelect_RetDone:
        raise RuntimeError("STEP write failed")
    return path


if __name__ == "__main__":
    print(make_step(sys.argv[1]))
