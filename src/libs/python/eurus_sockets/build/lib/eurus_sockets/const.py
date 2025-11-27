GOTO_MSG = {
    "command": str,
    "x": (float, int),
    "y": (float, int),
    "z": (float, int),
    "yaw": (float, int)
     }

TAKEOFF_MSG = {
    "command": str,
    "altitude": (float, int)
    }

LAND_MSG = {
    "command": str
    }

MESSAGES = {
    "goto": GOTO_MSG,
    "takeoff": TAKEOFF_MSG,
    "land": LAND_MSG
    }
