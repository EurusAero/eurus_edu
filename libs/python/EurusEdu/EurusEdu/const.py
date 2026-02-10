COMMAND_MSG_SAMPLE = {
    "command": str
}

ARM_MSG = COMMAND_MSG_SAMPLE

DISARM_MSG = COMMAND_MSG_SAMPLE

LAND_MSG = COMMAND_MSG_SAMPLE

TELEMETRY_REQUEST_MSG = COMMAND_MSG_SAMPLE

POINT_REACHED_MSG = COMMAND_MSG_SAMPLE

MOVE_TO_LOCAL_POINT = {
    "command": str,
    "x": (float, int),
    "y": (float, int),
    "z": (float, int),
    "yaw": (float, int, type(None)),
    "speed": (float, int)
     }

MOVE_IN_BODY_FRAME = {
    "command": str,
    "x": (float, int),
    "y": (float, int),
    "z": (float, int),
    "yaw": (float, int, type(None)),
    "speed": (float, int)
}

TAKEOFF_MSG = {
    "command": str,
    "altitude": (float, int),
    "speed": (float, int)
    }

SET_MODE_MSG = {
    "command": str,
    "mode": str
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

SET_VELOCITY_MSG = {
    "command": str,
    "vx": (int, float),
    "vy": (int, float),
    "vz": (int, float),
    "yaw_rate": (int, float, type(None))
}

LED_CONTROL_MSG = {
    "command": str,
    "nLED": int,
    "effect": str,
    "brightness": (int, float),
    "color": list
}

GET_FRAME_MSG = COMMAND_MSG_SAMPLE

GET_STREAM_MSG = COMMAND_MSG_SAMPLE

GET_TARGET_MSG = COMMAND_MSG_SAMPLE

LASERTAG_SHOT_MSG = COMMAND_MSG_SAMPLE

ARUCO_MAP_NAV_MSG = {
    "command": str,
    "state": bool
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
    "set_mode": SET_MODE_MSG,
    "point_reached": POINT_REACHED_MSG,
    "get_frame": GET_FRAME_MSG,
    "get_stream": GET_STREAM_MSG,
    "get_target": GET_TARGET_MSG,
    "set_velocity": SET_VELOCITY_MSG,
    "led_control": LED_CONTROL_MSG,
    "laser_shot": LASERTAG_SHOT_MSG,
    "aruco_map_navigation": ARUCO_MAP_NAV_MSG
    }

PENDING_STATUS = "pending"
RUNNING_STATUS = "running"
DENIED_STATUS = "denied"
COMPLETED_STATUS = "success"

STATUS_LIST = [PENDING_STATUS, RUNNING_STATUS, DENIED_STATUS, COMPLETED_STATUS]

DRONE_COMMANDS = ["move_to_local_point", "takeoff", "land", "arm", "disarm", "set_mode", "move_in_body_frame", "set_velocity"]

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
        "cell_voltage": 0.0,
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
    },
    
    "point_reached": False
}