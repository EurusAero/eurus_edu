"""
Safe demo: detect and follow colored drones using EurusEdu SDK.

What it does:
1) connect() -> sleep(1)
2) takeoff(1) -> sleep(10)
3) aruco_map_navigation(True) -> sleep(5)
4) starts visual tracking of blue/red drones and follows target with distance hold
5) shows camera stream with neural detections and control telemetry

Autonomous firing is intentionally omitted.
"""

import os
import sys
import time
from typing import Dict, List, Optional, Tuple
import threading

import cv2

# EurusEdu path relative to this script
from EurusEdu import EurusControl, EurusCamera


# =========================
# Configurable constants
# =========================
DRONE_IP = "10.42.0.1"
DRONE_PORT = 65432
CAMERA_PORT = 8001

TAKEOFF_ALTITUDE_M = 0.7
BASE_MARKER_ID = 124   # Marker on field used as respawn base
BASE_MARKER_ALT_M = 0.5   # Altitude for move_to_marker during dead state
BASE_MOVE_SPEED = 1.0
TELEMETRY_POLL_SEC = 0.2

# Team setup:
# - TEAM_COLOR: our team color in game mode ("red" or "blue")
# - Target color is selected automatically as opposite team.
TEAM_COLOR = "red"  # "red" | "blue"

ALLOWED_CLASSES = {
    "red": {"red drone"},
    "blue": {"blue drone"},
    "both": {"red drone", "blue drone"},
}

# Priority for tracking:
# 1) enemy drone
# 2) enemy target (if drone is not visible)
TRACK_PRIORITY_CLASSES = {
    "red": [{"red drone"}, {"red target"}],
    "blue": [{"blue drone"}, {"blue target"}],
    "both": [{"red drone", "blue drone"}, {"red target", "blue target"}],
}

MIN_CONFIDENCE = 0.50
MAX_TRACK_STALE_SEC = 0.8

# Desired target apparent size on screen.
# If target is larger than this, drone moves backward.
TARGET_MAX_BBOX_PX = 150
TARGET_MIN_BBOX_PX = 120

# Simple P-controller gains
K_YAW = 25.0         # deg/s for normalized X error
K_FORWARD = 0.012    # m/s per px of bbox error

MAX_YAW_RATE = 30.0
MAX_FORWARD_VX = 0.35
MAX_VERTICAL_VZ = 0.22

# Aim point offset in image coordinates:
# negative => aim above screen center.
AIM_OFFSET_Y_PX = -45
K_VERTICAL = 0.002

CTRL_PERIOD_SEC = 0.25
SHOW_WINDOW = True
WINDOW_NAME = "Drone Follow"
SHOW_FULLSCREEN = True

AUTO_LAND_ON_EXIT = True

# "Ready shot" criteria (status only, no firing):
# ready_shot is True when aim point is inside target bbox.
# For "center + 50px above" use AIM_OFFSET_Y_PX = -50..-60.
# If target area is bigger than drone area by this multiplier,
# it gets engagement priority.
TARGET_OVERSIZE_RATIO_FOR_PRIORITY = 1.20

# Skip sending set_velocity if command is effectively unchanged
CMD_EPS_VX = 0.01
CMD_EPS_VZ = 0.01
CMD_EPS_YAW = 1.0


def get_target_mode_for_team(team_color: str) -> str:
    if team_color == "red":
        return "blue"
    if team_color == "blue":
        return "red"
    raise ValueError("TEAM_COLOR must be 'red' or 'blue'")


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def extract_objects(detections: Dict) -> List[Dict]:
    if not detections:
        return []
    if "all_objects" in detections and isinstance(detections["all_objects"], list):
        return detections["all_objects"]
    if "all_targets" in detections and isinstance(detections["all_targets"], list):
        return detections["all_targets"]
    return []


def pick_target(detections: Dict, color_mode: str) -> Optional[Dict]:
    objects = extract_objects(detections)
    allowed = ALLOWED_CLASSES[color_mode]

    best = None
    best_area = -1.0
    for obj in objects:
        cls_name = str(obj.get("class", "")).lower()
        conf = float(obj.get("conf", 0.0))
        w = float(obj.get("w", 0.0))
        h = float(obj.get("h", 0.0))

        if cls_name not in allowed:
            continue
        if conf < MIN_CONFIDENCE:
            continue
        area = w * h
        if area > best_area:
            best_area = area
            best = obj
    return best


def pick_target_with_priority(detections: Dict, color_mode: str) -> Optional[Dict]:
    objects = extract_objects(detections)
    if color_mode not in TRACK_PRIORITY_CLASSES:
        return None

    for class_group in TRACK_PRIORITY_CLASSES[color_mode]:
        best = None
        best_area = -1.0
        for obj in objects:
            cls_name = str(obj.get("class", "")).lower()
            conf = float(obj.get("conf", 0.0))
            w = float(obj.get("w", 0.0))
            h = float(obj.get("h", 0.0))

            if cls_name not in class_group:
                continue
            if conf < MIN_CONFIDENCE:
                continue

            area = w * h
            if area > best_area:
                best_area = area
                best = obj

        if best is not None:
            return best

    return None


def pick_preferred_engagement(detections: Dict, color_mode: str) -> Optional[Dict]:
    """
    Safe engagement preference (status only):
    - default priority: enemy drone
    - if enemy target is significantly larger on screen, prefer target
    """
    objects = extract_objects(detections)
    if color_mode == "red":
        drone_classes = {"red drone"}
        target_classes = {"red target"}
    elif color_mode == "blue":
        drone_classes = {"blue drone"}
        target_classes = {"blue target"}
    elif color_mode == "both":
        drone_classes = {"red drone", "blue drone"}
        target_classes = {"red target", "blue target"}
    else:
        return None

    best_drone = None
    best_drone_area = -1.0
    best_target = None
    best_target_area = -1.0

    for obj in objects:
        cls_name = str(obj.get("class", "")).lower()
        conf = float(obj.get("conf", 0.0))
        if conf < MIN_CONFIDENCE:
            continue
        area = float(obj.get("w", 0.0)) * float(obj.get("h", 0.0))

        if cls_name in drone_classes and area > best_drone_area:
            best_drone_area = area
            best_drone = obj
        elif cls_name in target_classes and area > best_target_area:
            best_target_area = area
            best_target = obj

    if best_drone is None:
        return best_target
    if best_target is None:
        return best_drone

    if best_target_area >= best_drone_area * TARGET_OVERSIZE_RATIO_FOR_PRIORITY:
        return best_target
    return best_drone


def compute_control(target: Dict, frame_shape: Tuple[int, int, int]) -> Tuple[float, float, float]:
    h, w = frame_shape[:2]
    cx = float(target["x"])
    cy = float(target["y"])
    box_w = float(target["w"])
    box_h = float(target["h"])
    box_size = max(box_w, box_h)

    # Normalized horizontal error: -1..1
    err_x = (cx - (w / 2.0)) / (w / 2.0)
    yaw_rate = clamp(-K_YAW * err_x, -MAX_YAW_RATE, MAX_YAW_RATE)

    # Vertical alignment to an offset aim point (above center by AIM_OFFSET_Y_PX).
    desired_y = (h / 2.0) + AIM_OFFSET_Y_PX
    err_y = cy - desired_y
    # PX4 NED: positive vz is down. Keep sign configurable via gain.
    vz = -clamp(K_VERTICAL * err_y, -MAX_VERTICAL_VZ, MAX_VERTICAL_VZ)

    # Keep target size inside range (distance hold)
    if box_size > TARGET_MAX_BBOX_PX:
        size_err = box_size - TARGET_MAX_BBOX_PX
        vx = -K_FORWARD * size_err
    elif box_size < TARGET_MIN_BBOX_PX:
        size_err = TARGET_MIN_BBOX_PX - box_size
        vx = K_FORWARD * size_err
    else:
        vx = 0.0
    vx = clamp(vx, -MAX_FORWARD_VX, MAX_FORWARD_VX)

    return vx, yaw_rate, vz


def is_ready_shot(target: Optional[Dict], frame_shape: Tuple[int, int, int]) -> bool:
    if target is None:
        return False

    h, w = frame_shape[:2]
    target_cx = float(target["x"])
    target_cy = float(target["y"])
    box_w = float(target["w"])
    box_h = float(target["h"])

    x1 = target_cx - (box_w / 2.0)
    y1 = target_cy - (box_h / 2.0)
    x2 = target_cx + (box_w / 2.0)
    y2 = target_cy + (box_h / 2.0)

    aim_x = w / 2.0
    aim_y = (h / 2.0) + AIM_OFFSET_Y_PX
    return (x1 <= aim_x <= x2) and (y1 <= aim_y <= y2)


def draw_overlay(
    frame,
    detections: Dict,
    target: Optional[Dict],
    vx: float,
    yaw_rate: float,
    vz: float,
    ready_shot: bool,
    preferred_shot_class: str,
    is_alive: Optional[bool],
):
    objects = extract_objects(detections)
    for obj in objects:
        try:
            cx = float(obj["x"])
            cy = float(obj["y"])
            bw = float(obj["w"])
            bh = float(obj["h"])
            cls_name = str(obj.get("class", "unknown"))
            conf = float(obj.get("conf", 0.0))

            x1 = int(cx - bw / 2)
            y1 = int(cy - bh / 2)
            x2 = int(cx + bw / 2)
            y2 = int(cy + bh / 2)

            color = (0, 200, 0)
            if "red" in cls_name.lower():
                color = (0, 0, 255)
            elif "blue" in cls_name.lower():
                color = (255, 0, 0)

            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                frame,
                f"{cls_name} {conf:.2f} w:{int(bw)} h:{int(bh)}",
                (x1, max(15, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                color,
                2,
            )
        except Exception:
            continue

    if target:
        cx = int(float(target["x"]))
        cy = int(float(target["y"]))
        cv2.drawMarker(frame, (cx, cy), (0, 255, 255), cv2.MARKER_CROSS, 24, 2)
    h, w = frame.shape[:2]
    aim_x = int(w / 2)
    aim_y = int((h / 2) + AIM_OFFSET_Y_PX)
    cv2.drawMarker(frame, (aim_x, aim_y), (255, 255, 0), cv2.MARKER_TILTED_CROSS, 20, 2)

    cv2.putText(
        frame,
        f"cmd vx={vx:+.2f} vz={vz:+.2f} yaw_rate={yaw_rate:+.1f}",
        (10, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (40, 255, 40),
        2,
    )
    status_color = (0, 255, 0) if ready_shot else (0, 180, 255)
    status_text = f"ready_shot={ready_shot}"
    cv2.putText(
        frame,
        status_text,
        (10, 50),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        status_color,
        2,
    )
    cv2.putText(
        frame,
        f"preferred_shot={preferred_shot_class}",
        (10, 102),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (180, 255, 180),
        2,
    )
    alive_text = "is_alive=unknown" if is_alive is None else f"is_alive={is_alive}"
    alive_color = (100, 220, 255) if is_alive is None else ((0, 255, 0) if is_alive else (0, 0, 255))
    cv2.putText(
        frame,
        alive_text,
        (10, 128),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        alive_color,
        2,
    )


def parse_is_alive(telemetry: Optional[Dict]) -> Optional[bool]:
    if not telemetry:
        return None

    if "is_alive" in telemetry:
        try:
            return bool(telemetry.get("is_alive"))
        except Exception:
            return None

    state = telemetry.get("state", {})
    if isinstance(state, dict) and "is_alive" in state:
        try:
            return bool(state.get("is_alive"))
        except Exception:
            return None
    return None


def control_worker(drone: EurusControl, shared: Dict, lock: threading.Lock, stop_event: threading.Event, target_color_mode: str):
    last_sent_cmd = {"vx": None, "vz": None, "yaw_rate": None}
    while not stop_event.is_set():
        with lock:
            frame = shared.get("frame")
            active_det = shared.get("active_det")
            pause_tracking = shared.get("pause_tracking", False)

        target = None
        if not pause_tracking:
            target = pick_target_with_priority(active_det, target_color_mode) if active_det else None
        preferred_shot = pick_preferred_engagement(active_det, target_color_mode) if active_det else None

        vx_cmd = 0.0
        yaw_cmd = 30.0
        vz_cmd = 0.0
        if frame is not None and target is not None and not pause_tracking:
            vx_cmd, yaw_cmd, vz_cmd = compute_control(target, frame.shape)

        should_send_cmd = True
        if last_sent_cmd["vx"] is not None:
            same_vx = abs(vx_cmd - last_sent_cmd["vx"]) < CMD_EPS_VX
            same_vz = abs(vz_cmd - last_sent_cmd["vz"]) < CMD_EPS_VZ
            same_yaw = abs(yaw_cmd - last_sent_cmd["yaw_rate"]) < CMD_EPS_YAW
            should_send_cmd = not (same_vx and same_vz and same_yaw)

        if should_send_cmd:
            try:
                drone.set_velocity(vx=vx_cmd, vy=0.0, vz=vz_cmd, yaw_rate=yaw_cmd)
                last_sent_cmd["vx"] = vx_cmd
                last_sent_cmd["vz"] = vz_cmd
                last_sent_cmd["yaw_rate"] = yaw_cmd
            except Exception:
                stop_event.set()
                break

        ready_shot = (not pause_tracking) and frame is not None and is_ready_shot(target, frame.shape)
        if ready_shot:
            drone.laser_shot()

        preferred_shot_class = "none"
        if preferred_shot is not None:
            preferred_shot_class = str(preferred_shot.get("class", "unknown"))

        with lock:
            shared["target"] = target
            shared["vx_cmd"] = vx_cmd
            shared["yaw_cmd"] = yaw_cmd
            shared["vz_cmd"] = vz_cmd
            shared["ready_shot"] = ready_shot
            shared["preferred_shot_class"] = preferred_shot_class

        time.sleep(CTRL_PERIOD_SEC)


def life_state_worker(drone: EurusControl, shared: Dict, lock: threading.Lock, stop_event: threading.Event):
    last_alive = None
    in_dead_state = False

    while not stop_event.is_set():
        telemetry = drone.get_telemetry()
        is_alive = parse_is_alive(telemetry)

        with lock:
            shared["is_alive"] = is_alive

        if is_alive is None:
            time.sleep(TELEMETRY_POLL_SEC)
            continue

        # Transition alive -> dead: return to base immediately
        if is_alive is False and last_alive is not False:
            in_dead_state = True
            with lock:
                shared["pause_tracking"] = True
            # try:
            #     drone.set_velocity(0.0, 0.0, 0.0, 0.0)
            #     time.sleep(2)
            # except Exception:
            #     pass
            try:
                drone.move_to_marker(marker_id=BASE_MARKER_ID, z=BASE_MARKER_ALT_M, speed=BASE_MOVE_SPEED)
            except Exception:
                pass

        # Transition dead -> alive: takeoff and resume tracking
        if is_alive is True and last_alive is False and in_dead_state:
            try:
                drone.takeoff(TAKEOFF_ALTITUDE_M)
                time.sleep(6)
                drone.aruco_map_navigation(True, True)
                time.sleep(3)
                drone.set_velocity(0.0, 0.0, 0.0, 30.0)
            except Exception:
                pass
            with lock:
                shared["pause_tracking"] = False
            in_dead_state = False

        last_alive = is_alive
        time.sleep(TELEMETRY_POLL_SEC)


def view_worker(shared: Dict, lock: threading.Lock, stop_event: threading.Event, target_color_mode: str):
    if SHOW_WINDOW:
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
        if SHOW_FULLSCREEN:
            cv2.setWindowProperty(WINDOW_NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    while not stop_event.is_set():
        with lock:
            frame = None if shared.get("frame") is None else shared["frame"].copy()
            active_det = shared.get("active_det") or {}
            target = shared.get("target")
            vx_cmd = shared.get("vx_cmd", 0.0)
            yaw_cmd = shared.get("yaw_cmd", 0.0)
            vz_cmd = shared.get("vz_cmd", 0.0)
            ready_shot = shared.get("ready_shot", False)
            preferred_shot_class = shared.get("preferred_shot_class", "none")
            is_alive = shared.get("is_alive")

        if frame is None:
            time.sleep(0.01)
            continue

        if SHOW_WINDOW:
            draw_overlay(frame, active_det, target, vx_cmd, yaw_cmd, vz_cmd, ready_shot, preferred_shot_class, is_alive)
            cv2.putText(
                frame,
                f"team={TEAM_COLOR} target={target_color_mode}",
                (10, 76),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
            )
            cv2.imshow(WINDOW_NAME, frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                stop_event.set()
                break
        else:
            time.sleep(0.02)


def main():
    target_color_mode = get_target_mode_for_team(TEAM_COLOR)
    if target_color_mode not in ALLOWED_CLASSES:
        raise ValueError(f"target_color_mode must be one of: {list(ALLOWED_CLASSES.keys())}")

    drone = EurusControl(ip=DRONE_IP, port=DRONE_PORT)
    cam = EurusCamera(DRONE_IP, CAMERA_PORT)

    shared = {
        "frame": None,
        "active_det": None,
        "target": None,
        "vx_cmd": 0.0,
        "yaw_cmd": 0.0,
        "vz_cmd": 0.0,
        "ready_shot": False,
        "preferred_shot_class": "none",
        "is_alive": None,
        "pause_tracking": False,
    }
    lock = threading.Lock()
    stop_event = threading.Event()
    control_thread = None
    view_thread = None
    life_thread = None

    last_det = None
    last_det_time = 0.0

    try:
        drone.connect()
        time.sleep(1.0)
        cam.connect()
        cam.start_stream()
        drone.start_game(True, TEAM_COLOR)

        drone.takeoff(TAKEOFF_ALTITUDE_M)
        time.sleep(10.0)
        drone.aruco_map_navigation(True, True)
        time.sleep(5.0)

        print("Tracking started. Press 'q' to stop.")

        control_thread = threading.Thread(
            target=control_worker,
            args=(drone, shared, lock, stop_event, target_color_mode),
            daemon=True,
        )
        view_thread = threading.Thread(
            target=view_worker,
            args=(shared, lock, stop_event, target_color_mode),
            daemon=True,
        )
        life_thread = threading.Thread(
            target=life_state_worker,
            args=(drone, shared, lock, stop_event),
            daemon=True,
        )
        control_thread.start()
        view_thread.start()
        life_thread.start()

        # Acquisition loop: keep camera and detections fresh for both threads
        while not stop_event.is_set():
            ret, frame = cam.read()
            if not ret:
                time.sleep(0.01)
                continue

            det = cam.get_detection(blocking=False)
            if det:
                last_det = det
                last_det_time = time.time()

            active_det = None
            if last_det and (time.time() - last_det_time) <= MAX_TRACK_STALE_SEC:
                active_det = last_det

            with lock:
                shared["frame"] = frame
                shared["active_det"] = active_det

            time.sleep(0.005)

    except KeyboardInterrupt:
        stop_event.set()
    finally:
        stop_event.set()

        if control_thread and control_thread.is_alive():
            control_thread.join(timeout=1.0)
        if view_thread and view_thread.is_alive():
            view_thread.join(timeout=1.0)
        if life_thread and life_thread.is_alive():
            life_thread.join(timeout=1.0)

        try:
            drone.set_velocity(0.0, 0.0, 0.0, 0.0)
        except Exception:
            pass

        if AUTO_LAND_ON_EXIT:
            try:
                drone.land()
            except Exception:
                pass

        try:
            cam.stop_stream()
        except Exception:
            pass
        cam.disconnect()
        drone.disconnect()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
