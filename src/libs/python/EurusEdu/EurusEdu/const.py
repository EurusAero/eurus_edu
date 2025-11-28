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

ACTION_COMPLETE_MSG = {
    "command": str,
    "action": str,
    "code": int,
    "message": str
}

MESSAGES = {
    "goto": GOTO_MSG,
    "takeoff": TAKEOFF_MSG,
    "land": LAND_MSG,
    "response": RESPONSE_MSG,
    "action_complete": ACTION_COMPLETE_MSG,
    "request_telemetry": TELEMETRY_REQUEST_MSG,
    "response_telemetry": TELEMETRY_RESPONSE_MSG,
    "arm": ARM_MSG,
    "disarm": DISARM_MSG
    }

START_MARKER = '<msg>'
END_MARKER = '</msg>'

# Коды состояния действия (Action Codes)
CODE_IN_PROGRESS = 100  # Действие принято и выполняется
CODE_SUCCESS     = 200  # Действие успешно завершено
CODE_DENIED      = 400  # Отказ в выполнении или ошибка