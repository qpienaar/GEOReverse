from .remh import Cline
import FreeCAD
import Part
import math

def process_lattice(lattice, id):
    '''
    Replaces lattice with cells
    '''

    # determine universes in lattice
    universes = lattice.U # each universe here appears in each lattice cell --> assume only one universe per cell
    pitch = lattice.pitch # [pitchx, pitchy, pitchz]
    lower_left = lattice.lower_left
    dimension = lattice.dimensions # number of cells in each direction [#x, #y, #z]

    if len(dimension) == 2:
        dimension = [dimension[0], dimension[1], 1] 
        pitch = [pitch[0], pitch[1], 214.2] # z length of c5g7 with 1 layer
        lower_left = [lower_left[0], lower_left[1], 0.0]

    # create a fill cell which holds each universe at its correct location
    cells = []
    for k in range(dimension[2]):   # z
        for j in range(dimension[1]):  # y
            for i in range(dimension[0]):  # x
                # determine the physical location of each universe
                dx = lower_left[0] + (i + 0.5)*pitch[0]
                dy = lower_left[1] + (j + 0.5)*pitch[1]
                dz = lower_left[2] + (k + 0.5)*pitch[2]

                box_origin = FreeCAD.Vector(
                    lower_left[0] + i * pitch[0],
                    lower_left[1] + j * pitch[1],
                    lower_left[2] + k * pitch[2]
                )

                TR = FreeCAD.Matrix(
                    1, 0, 0, dx,
                    0, 1, 0, dy,
                    0, 0, 1, dz,
                    0, 0, 0, 1
                )

                cell = CellCard()
                cell.name = id
                cell.level = None
                cell.MAT = None
                cell.U = lattice.name # this cell will belong to the lattice

                idx = k * dimension[1] * dimension[0] + j * dimension[0] + i
                
                cell.FILL = universes[idx]
                cell.TR = TR
                cell.geom = None
                cell.shape = Part.makeBox(pitch[0], pitch[1], pitch[2], box_origin)

                cells.append(cell)
                id += 1
    return cells, id

class CellCard:

    def __init__(self, data=None):
        self.type = "cell"
        self.shape = None
        if data:
            self.processData(data)

    def processData(self, data):
        self.name = int(data["id"])
        self.level = None

        if "material" in data.keys():
            self.MAT = 0 if data["material"] == "void" else int(data["material"])
        else:
            self.MAT = None

        # if "universe" in data.keys():
        #     self.U = 0 if int(data["universe"]) == 1 else int(data["universe"])
        # else:
        #     self.U = 0

        # In CellCard.processData — remove the universe remapping entirely:

        if "universe" in data.keys():
            self.U = int(data["universe"])   # trust the XML as-is
        else:
            self.U = 0

        if "fill" in data.keys():
            self.FILL = int(data["fill"])
        else:
            self.FILL = None

        if "rotation" in data.keys() or "translation" in data.keys():
            # parse rotation - assume 9 values forming 3x3 matrix
            if "rotation" in data.keys():
                r = [float(x) for x in data["rotation"].split()]
                R = [[r[0], r[1], r[2]],
                    [r[3], r[4], r[5]],
                    [r[6], r[7], r[8]]]
            else:
                R = [[1,0,0],[0,1,0],[0,0,1]]  # identity

            # parse translation - assume 3 values
            if "translation" in data.keys():
                t = [float(x) for x in data["translation"].split()]
            else:
                t = [0, 0, 0]

            self.TR = FreeCAD.Matrix(
                R[0][0], R[0][1], R[0][2], t[0],
                R[1][0], R[1][1], R[1][2], t[1],
                R[2][0], R[2][1], R[2][2], t[2],
                0,       0,       0,       1
            )
        else:
            self.TR = FreeCAD.Matrix() # FreeCAD defaults to Identity

        if "region" in data:
            self.geom = Cline(data["region"].replace("|", ":"))
        else:
            self.geom = None  # this condition was added as some cells do not have a region key

class SurfCard:
    def __init__(self, data):

        self.type = "surface"
        self.processData(data)

    def processData(self, data):
        self.name = int(data["id"])
        self.stype = data["type"]
        self.scoefs = tuple(float(x) for x in data["coeffs"].split())

class LatticeCard:
    def __init__(self, data):

        self.type = "lattice"
        self.processData(data)

    def processData(self, data):
        self.name = int(data.attrib["id"])
        self.pitch = [float(x) for x in data.find('pitch').text.split()]
        #self.outer = int(data.find('outer').text)
        self.dimensions = [int(x) for x in data.find('dimension').text.split()]
        self.lower_left = [float(x) for x in data.find('lower_left').text.split()]
        self.U = [int(x) for x in data.find('universes').text.split()]


def get_cards(root):
    cards = []
    lattices = []
    for c in root:
        if c.tag == "lattice":
            lattices.append(c)
        else:
            cards.append(process_card(c, root))
    
    next_id = max(c.name for c in cards) + 1 # find a valid id to assign new cells
    for i, l in enumerate(lattices):
        lattice = process_card(l, root)
        cells, next_id = process_lattice(lattice, next_id)
        for cell in cells:
            cards.append(cell)

        lattices[i] = lattice # place lattice card in list
    return cards, lattices

def process_card(card, root):
    ctype = card.tag

    # Determine the id of the lattice cell
    if ctype == "lattice":
        print("Processing lattice cell of id " + card.attrib["id"])
        return LatticeCard(card)
    elif ctype == "cell":
        return CellCard(card.attrib)
    elif ctype == "surface":
        return SurfCard(card.attrib)
    else:
        raise ValueError(f"Card type {ctype}")