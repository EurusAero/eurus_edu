ARM_MSG = {
    "command": str
}

DISARM_MSG = {
    "command": str
}

MOVE_TO_LOCAL_POINT = {
    "command": str,
    "x": (float, int),
    "y": (float, int),
    "z": (float, int),
    "yaw": (float, int, None)
     }

MOVE_IN_BODY_FRAME = {
    "command": str,
    "x": (float, int),
    "y": (float, int),
    "z": (float, int),
    "yaw": (float, int, None)
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
    "move_to_local_point": MOVE_TO_LOCAL_POINT,
    "move_in_body_frame": MOVE_IN_BODY_FRAME,
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

DRONE_COMMANDS = ["move_to_local_point", "takeoff", "land", "arm", "disarm", "set_mode", "move_in_body_frame"]

START_MARKER = '<msg>'
END_MARKER = '</msg>'

TELEMETRY_DATA = {
    "state": {
        "connected": False,
        "armed": False,
        "mode": "None",
        "system_status": 0
    },
    
    "battery": {
        "voltage": 0.0,
        "current": 0.0,
        "percentage": 0.0
    },
    
    "local_position": {
        "x": 0.0,
        "y": 0.0,
        "z": 0.0,
        "pitch": 0.0,
        "roll": 0.0,
        "yaw": 0.0,
    },
    
    
    "setpoint_local": {
        "x": 0.0,
        "y": 0.0,
        "z": 0.0,
        "yaw": 0.0
    },
    
    "velocity": {
        "vx": 0.0,
        "vy": 0.0,
        "vz": 0.0,
    }
}