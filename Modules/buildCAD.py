import BOPTools.SplitAPI
from tqdm import tqdm
import FreeCAD

from .buildSolidCell import FuseSolid
from .Utils.booleanFunction import BoolSequence
from .Utils.boundBox import myBox


def interferencia(container, cell, mode="slice"):
    """
    Clip a cell's shape to the spatial extent of its container cell.

    This is the core geometric confinement step in the universe hierarchy
    build process.  When a universe is placed inside a container cell, the
    cells of that universe may geometrically extend beyond the container's
    boundary (because they were built against their own bounding box, not
    the container's).  ``interferencia`` trims a single cell shape back to
    the volume that lies within the container, producing the correct
    physical solid for export.

    Two clipping strategies are available via the ``mode`` parameter:

    ``"slice"`` (default)
        Uses ``BOPTools.SplitAPI.slice`` to partition the cell shape by the
        container surface, then retains only the fragments whose centre of
        mass lies inside the container.  Fragments that fall outside are
        discarded.  If no fragments survive the inside test (e.g. the cell
        sits entirely outside the container after transformation), the
        original unclipped cell shape is returned unchanged rather than
        raising an error, allowing the caller to decide how to handle the
        degenerate case.  Multiple surviving fragments are fused into a
        single solid via ``FuseSolid`` before being returned.

    ``"common"``
        Uses FreeCAD's ``Shape.common`` boolean intersection directly.
        This is faster and more robust for simple convex shapes but can
        fail or produce invalid geometry for complex or near-tangent
        surfaces where the BOP kernel struggles.  Prefer ``"slice"`` for
        production use; ``"common"`` is retained as a fallback or for
        debugging.

    Parameters
    ----------
    container : CadCell
        The parent cell whose shape defines the clipping volume.  Must have
        a valid ``shape`` attribute (a FreeCAD ``TopoShape``).  The
        ``shape.isInside`` method is used in ``"slice"`` mode to test
        fragment membership, so the shape must be a closed solid.
    cell : CadCell
        The child cell to be clipped.  Must have a valid ``shape``
        attribute.  The shape is not modified in place; the clipped result
        is returned and it is the caller's responsibility to assign it back
        (e.g. ``cell.shape = interferencia(container, cell)``).
    mode : {"slice", "common"}, optional
        Clipping strategy to use.  Defaults to ``"slice"``.

    Returns
    -------
    Part.Shape
        The portion of ``cell.shape`` that lies within ``container.shape``.
        In ``"slice"`` mode this is either a fused solid built from the
        surviving fragments or, if no fragments pass the inside test, the
        original ``cell.shape`` unchanged.  In ``"common"`` mode this is
        the raw result of the boolean intersection.
    """
    if mode == "common":
        return cell.shape.common(container.shape)

    Base = cell.shape
    Tool = (container.shape,)
    solids = BOPTools.SplitAPI.slice(Base, Tool, "Split", tolerance=1e-4).Solids
    cellParts = []
    for s in solids:
        if container.shape.isInside(s.CenterOfMass, 0.0, False):
            cellParts.append(s)

    if not cellParts:
        return cell.shape
    else:
        return FuseSolid(cellParts)


def AssignSurfaceToCell(UniverseCells, modelSurfaces):
    for Uid, uniCells in UniverseCells.items():
        for c in uniCells.values():
            c.setSurfaces(modelSurfaces)


def get_universe_containers(levels, Universes):
    Ucontainer = {}
    for lev in range(1, len(levels)):
        for U, name in levels[lev]:
            UFILL = Universes[U][name].FILL
            if UFILL in Ucontainer.keys():
                Ucontainer[UFILL].append((U, name, lev))
            else:
                Ucontainer[UFILL] = [(U, name, lev)]
    return Ucontainer


def BuildUniverseCells(startInfo, ContainerCell, AllUniverses, universeCut=True):
    CADUniverse = []
    Ustart, levelMax = startInfo
    Universe = AllUniverses[Ustart]

    if ContainerCell.name is not None:
        print(f"Build Universe {ContainerCell.FILL} in container cell {ContainerCell.name}")
    else:
        print(f"Build Universe {ContainerCell.FILL}")
    fails = []
    for NTcell in tqdm(Universe.values(), desc="build cell"):

        if NTcell.shape:
            buildShape = False
            if ContainerCell.CurrentTR:
                cell = NTcell.copy()
                cell.transformSolid(ContainerCell.CurrentTR)
            else:
                cell = NTcell
        else:
            CTRF = None
            buildShape = True

        if buildShape:
            if type(NTcell.definition) is not BoolSequence:
                NTcell.definition = BoolSequence(NTcell.definition.str)

            if ContainerCell.shape is not None:
                external_box = myBox(ContainerCell.shape.BoundBox, "Forward")
                if ContainerCell.CurrentTR:
                    external_box.Box = external_box.Box.transformed(ContainerCell.CurrentTR.inverse())
            else:
                external_box = None

            debug = False
            if debug:
                NTcell.build_BoundBox(external_box, enlarge=0.2)
                if NTcell.boundBox.Orientation == "Forward" and NTcell.boundBox.Box is None:
                    NTcell.shape = None
                else:
                    if NTcell.boundBox.Orientation == "Forward":
                        NTcell.externalBox = NTcell.boundBox
                    NTcell.buildShape(simplify=False)
            else:
                try:
                    NTcell.build_BoundBox(external_box, enlarge=0.2)
                    if NTcell.boundBox.Orientation == "Forward" and NTcell.boundBox.Box is None:
                        NTcell.shape = None
                    else:
                        if NTcell.boundBox.Orientation == "Forward":
                            NTcell.externalBox = NTcell.boundBox
                        NTcell.buildShape(simplify=False)
                except:
                    fails.append(NTcell.name)

            if NTcell.shape is None:
                print(f"Cell {NTcell.name} shape is None, skipping")
                continue

            cell = NTcell.copy()
            if ContainerCell.CurrentTR:
                cell.transformSolid(ContainerCell.CurrentTR)

        if universeCut and ContainerCell.shape:
            cell.shape = interferencia(ContainerCell, cell)

        if not cell.FILL or ContainerCell.level + 1 > levelMax:
            CADUniverse.append(cell)
        else:
            if ContainerCell.CurrentTR:
                cell.CurrentTR = ContainerCell.CurrentTR.multiply(cell.TRFL)
            cell.level = ContainerCell.level + 1
            univ, ff = BuildUniverseCells((cell.FILL, levelMax), cell, AllUniverses, universeCut=universeCut)
            CADUniverse.append(univ)
            fails.extend(ff)

    return ((ContainerCell.name, Ustart), CADUniverse), fails


def makeTree(CADdoc, CADCells):

    label, universeCADCells = CADCells
    groupObj = CADdoc.addObject("App::Part", "Materials")

    groupObj.Label = f"Universe_{label[1]}_Container_{label[0]}"

    CADObj = {}
    for i, c in enumerate(universeCADCells):
        if isinstance(c, (tuple, list)):
            groupObj.addObject(makeTree(CADdoc, c))
        else:
            featObj = CADdoc.addObject("Part::FeaturePython", f"solid{i}")
            featObj.Label = f"Cell_{c.name}_{c.MAT}"
            featObj.Shape = c.shape
            if c.MAT not in CADObj.keys():
                CADObj[c.MAT] = [featObj]
            else:
                CADObj[c.MAT].append(featObj)

    for mat, matGroup in CADObj.items():
        groupMatObj = CADdoc.addObject("App::Part", "Materials")
        groupMatObj.Label = f"Material_{mat}_{label[0]}{label[1]}"
        groupMatObj.addObjects(matGroup)
        groupObj.addObject(groupMatObj)

    return groupObj
