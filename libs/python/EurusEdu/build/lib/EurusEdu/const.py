ARM_MSG = {
    "command": str
}

DISARM_MSG = {
    "command": str
}

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


SET_MODE_MSG = {
    "command": str,
    "mode": str
}

TELEMETRY_REQUEST_MSG = {
    "command": str,
}

TELEMETRY_RESPONSE_MSG = {
    "command": str,
    "telemetry": dict
}

RESPONSE_MSG = {
    "command": str,
    "status": str,
    "message": str
}

ACTION_STATUS_MSG = {
    "command": str,
    "action": str,
    "status": str,
    "message": str
}

MESSAGES = {
    "goto": GOTO_MSG,
    "takeoff": TAKEOFF_MSG,
    "land": LAND_MSG,
    "response": RESPONSE_MSG,
    "action_status": ACTION_STATUS_MSG,
    "request_telemetry": TELEMETRY_REQUEST_MSG,
    "response_telemetry": TELEMETRY_RESPONSE_MSG,
    "arm": ARM_MSG,
    "disarm": DISARM_MSG,
    "set_mode": SET_MODE_MSG
    }

PENDING_STATUS = "pending"
RUNNING_STATUS = "running"
DENIED_STATUS = "denied"
COMPLETED_STATUS = "success"

STATUS_LIST = [PENDING_STATUS, RUNNING_STATUS, DENIED_STATUS, COMPLETED_STATUS]

DRONE_COMMANDS = ["goto", "takeoff", "land", "arm", "disarm", "set_mode"]

START_MARKER = '<msg>' # Маркер в начале каждого json сообщения
END_MARKER = '</msg>' # Маркер в конце каждого json сообщения

