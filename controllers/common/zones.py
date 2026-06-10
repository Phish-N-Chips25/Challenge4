"""Definicao das zonas da empresa e rotas pelo corredor.

Partilhado pelos controladores (supervisor, robo de patrulha, pessoas).
O edificio tem um corredor central (y entre -1 e 1) que liga todas as zonas;
cada zona tem um unico ponto de passagem (porta) para o corredor.
"""

# nome -> (xmin, xmax, ymin, ymax)
ZONES = {
    "lobby": (-10, 0, -6, -1),
    "break_room": (0, 10, -6, -1),
    "corridor": (-10, 10, -1, 1),
    "work_room_1": (-10, -6, 1, 6),
    "work_room_2": (-6, -2, 1, 6),
    "work_room_3": (-2, 2, 1, 6),
    "work_room_4": (2, 6, 1, 6),
    "datacenter": (6, 10, 1, 6),
}

# nome -> ((ponto no corredor), (ponto dentro da zona)) junto a porta
DOOR_WAYPOINTS = {
    "lobby": ((-5, -0.35), (-5, -1.7)),
    "break_room": ((5, -0.35), (5, -1.7)),
    "work_room_1": ((-8, 0.35), (-8, 1.7)),
    "work_room_2": ((-4, 0.35), (-4, 1.7)),
    "work_room_3": ((0, 0.35), (0, 1.7)),
    "work_room_4": ((4, 0.35), (4, 1.7)),
    "datacenter": ((8, 0.35), (8, 1.7)),
}

# DEF da porta -> posicao (para o supervisor abrir/trancar portas)
DOORS = {
    "DOOR_ENTRANCE": (-5, -6),
    "DOOR_CHECKPOINT": (-5, -1),
    "DOOR_BREAK": (5, -1),
    "DOOR_WR1": (-8, 1),
    "DOOR_WR2": (-4, 1),
    "DOOR_WR3": (0, 1),
    "DOOR_WR4": (4, 1),
    "DOOR_DATACENTER": (8, 1),
}

# gate logico (camara de reconhecimento facial) -> porta que controla
GATE_DOOR = {
    "checkpoint": "DOOR_CHECKPOINT",
    "datacenter": "DOOR_DATACENTER",
}


def zone_of(x, y):
    """Devolve o nome da zona que contem o ponto (x, y), ou None se exterior."""
    for name, (xmin, xmax, ymin, ymax) in ZONES.items():
        if xmin <= x <= xmax and ymin <= y <= ymax:
            return name
    return None


def route(sx, sy, tx, ty):
    """Lista de waypoints de (sx, sy) ate (tx, ty) passando pelo corredor."""
    src = zone_of(sx, sy)
    dst = zone_of(tx, ty)
    if src == dst:
        return [(tx, ty)]
    waypoints = []
    if src not in (None, "corridor"):
        corridor_wp, inside_wp = DOOR_WAYPOINTS[src]
        waypoints += [inside_wp, corridor_wp]
    if dst not in (None, "corridor"):
        corridor_wp, inside_wp = DOOR_WAYPOINTS[dst]
        waypoints += [corridor_wp, inside_wp]
    waypoints.append((tx, ty))
    return waypoints
