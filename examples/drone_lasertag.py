"""
Максимально упрощенный скрипт: обнаружение и преследование цветных дронов.
Архитектура: 3 потока (Управление+Камера, Отрисовка, Запись видео).
"""

import os
import time
import datetime
import threading
import cv2

from EurusEdu import EurusControl, EurusCamera
from math import radians

# =========================
# Глобальные настройки
# =========================
DRONE_IP = "10.42.0.1"
DRONE_PORT = 65432
CAMERA_PORT = 8001

TEAM_COLOR = "blue"  # "red" или "blue"
TARGET_COLOR = "blue" if TEAM_COLOR == "red" else "red"

TAKEOFF_ALTITUDE_M = 1
MIN_TRACK_ALT_M = 0.7   # Минимальная высота при трекинге
MAX_TRACK_ALT_M = 1.5
ALT_FLOOR_K = 0.8       # Коэффициент подъема, если высота ниже минимальной

BASE_MARKER_ID = 251
BASE_MARKER_ALT_M = 1
BASE_MOVE_SPEED = 0.5

MIN_CONFIDENCE = 0.50
TARGET_MAX_BBOX_PX = 150
TARGET_MIN_BBOX_PX = 120

# Коэффициенты П-регулятора
K_YAW = 25.0
K_FORWARD = 0.012
K_VERTICAL = 0.002

MAX_YAW_RATE = 30.0
MAX_FORWARD_VX = 0.35
MAX_VERTICAL_VZ = 0.22
AIM_OFFSET_Y_PX = -45

RECORD_FPS = 30
RECORD_FILENAME_PREFIX = "recording_raw_"

# Общий словарь для передачи данных между потоками (в Python операции с dict атомарны)
shared_state = {
    "frame": None,
    "detections": {},
    "target": None,
    "vx": 0.0, "vz": 0.0, "yaw": 0.0,
    "is_alive": None,
    "alt": None,
    "ready_shot": False
}
stop_event = threading.Event()

cam = EurusCamera(DRONE_IP, CAMERA_PORT)

cam.connect()
cam.start_stream()

# =========================
# Вспомогательные функции
# =========================
def clamp(value, lo, hi):
    return max(lo, min(hi, value))

def pick_target(detections, target_color):
    """Ищет самую крупную цель нужного цвета (дрон или мишень)"""
    if not detections:
        return None
    
    objects = detections.get("all_objects", []) + detections.get("all_targets", [])
    best_obj = None
    best_area = -1.0
    
    for obj in objects:
        cls_name = str(obj.get("class", "")).lower()
        conf = float(obj.get("conf", 0.0))
        if target_color not in cls_name or conf < MIN_CONFIDENCE:
            continue
            
        area = float(obj.get("w", 0.0)) * float(obj.get("h", 0.0))
        if area > best_area:
            best_area = area
            best_obj = obj
            
    return best_obj

def compute_control(target, frame_shape):
    """Считает скорости vx, vz, yaw_rate для удержания цели в центре"""
    h, w = frame_shape[:2]
    cx, cy = float(target["x"]), float(target["y"])
    box_size = max(float(target["w"]), float(target["h"]))

    # Yaw (поворот)
    err_x = (cx - (w / 2.0)) / (w / 2.0)
    yaw_rate = clamp(-K_YAW * err_x, -MAX_YAW_RATE, MAX_YAW_RATE)

    # Vz (высота)
    desired_y = (h / 2.0) + AIM_OFFSET_Y_PX
    err_y = cy - desired_y
    vz = -clamp(K_VERTICAL * err_y, -MAX_VERTICAL_VZ, MAX_VERTICAL_VZ)

    # Vx (вперед/назад для удержания дистанции)
    if box_size > TARGET_MAX_BBOX_PX:
        vx = -K_FORWARD * (box_size - TARGET_MAX_BBOX_PX)
    elif box_size < TARGET_MIN_BBOX_PX:
        vx = K_FORWARD * (TARGET_MIN_BBOX_PX - box_size)
    else:
        vx = 0.0
    vx = clamp(vx, -MAX_FORWARD_VX, MAX_FORWARD_VX)

    return vx, yaw_rate, vz

def is_ready_shot(target, frame_shape):
    """Проверяет, находится ли прицел внутри bounding box цели"""
    if not target: return False
    h, w = frame_shape[:2]
    cx, cy = float(target["x"]), float(target["y"])
    bw, bh = float(target["w"]), float(target["h"])
    
    aim_x = w / 2.0
    aim_y = (h / 2.0) + AIM_OFFSET_Y_PX
    
    return (cx - bw/2 <= aim_x <= cx + bw/2) and (cy - bh/2 <= aim_y <= cy + bh/2)

def get_detection_color(cls_name):
    cls_name = str(cls_name).lower()
    if "red" in cls_name:
        return (0, 0, 255)
    if "blue" in cls_name:
        return (255, 0, 0)
    return (0, 255, 0)

def draw_overlay(frame):
    """Отрисовка телеметрии и рамок на кадре"""
    detections = shared_state["detections"] or {}
    target = shared_state["target"]
    objects = detections.get("all_objects", []) + detections.get("all_targets", [])

    for obj in objects:
        cx, cy = float(obj.get("x", 0.0)), float(obj.get("y", 0.0))
        bw, bh = float(obj.get("w", 0.0)), float(obj.get("h", 0.0))
        cls_name = str(obj.get("class", "object"))
        conf = float(obj.get("conf", 0.0))

        x1 = int(cx - bw / 2.0)
        y1 = int(cy - bh / 2.0)
        x2 = int(cx + bw / 2.0)
        y2 = int(cy + bh / 2.0)

        color = get_detection_color(cls_name)
        is_target = target is obj
        thickness = 3 if is_target else 2

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)

        label = f"{cls_name} {conf:.2f}"
        if is_target:
            label += " | TARGET"

        (text_w, text_h), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        text_x = max(0, x1)
        text_y = max(text_h + 6, y1 - 8)
        cv2.rectangle(
            frame,
            (text_x, text_y - text_h - baseline - 6),
            (text_x + text_w + 8, text_y + 2),
            color,
            -1
        )
        cv2.putText(
            frame,
            label,
            (text_x + 4, text_y - 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            2
        )

    info = (
        f"Alive: {shared_state['is_alive']} | Alt: {shared_state['alt']}",
        f"Cmd: vx={shared_state['vx']:+.2f} vz={shared_state['vz']:+.2f} yaw={shared_state['yaw']:+.1f}",
        f"Ready Shot: {shared_state['ready_shot']}"
    )
    for i, text in enumerate(info):
        cv2.putText(frame, text, (10, 30 + i*25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

# =========================
# Потоки (UI и Запись)
# =========================
def view_worker():
    cv2.namedWindow("Drone View", cv2.WINDOW_NORMAL)
    while not stop_event.is_set():
        frame = shared_state["frame"]
        if frame is not None:
            display_frame = frame.copy()
            draw_overlay(display_frame)
            cv2.imshow("Drone View", display_frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                stop_event.set()
        else:
            time.sleep(0.02)

def record_worker():
    writer = None
    frame_period = 1.0 / RECORD_FPS
    while not stop_event.is_set():
        start_t = time.time()
        ret, frame = cam.read()
        if ret:
            shared_state["frame"] = frame
            
        # frame = shared_state["frame"]
        
        if frame is not None:
            if writer is None:
                h, w = frame.shape[:2]
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                path = os.path.join(os.path.dirname(__file__), f"{RECORD_FILENAME_PREFIX}{ts}.mp4")
                writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), RECORD_FPS, (w, h))
            writer.write(frame)
            
        elapsed = time.time() - start_t
        time.sleep(max(0, frame_period - elapsed))
        
    if writer: writer.release()

# =========================
# Главный цикл (Управление)
# =========================
def main():
    drone = EurusControl(ip=DRONE_IP, port=DRONE_PORT)
    # cam = EurusCamera(DRONE_IP, CAMERA_PORT)
    frame_period = 1.0 / RECORD_FPS


    drone.connect()
    # cam.connect()
    # cam.start_stream()
    time.sleep(1)
    drone.arm()
    time.sleep(1)
    drone.start_game(True, TEAM_COLOR)
    drone.takeoff(TAKEOFF_ALTITUDE_M, speed=0.2)
    time.sleep(10.0)
    drone.aruco_map_navigation(True, True)
    time.sleep(5.0)

    # Запуск потоков UI и записи
    threading.Thread(target=view_worker, daemon=True).start()
    threading.Thread(target=record_worker, daemon=True).start()

    print("Tracking started. Press 'q' in video window to stop.")
    
    was_alive = None
    
    try:
        while not stop_event.is_set():
            start_t = time.time()

            # 1. Обновление данных (Камера и Телеметрия)
            # ret, frame = cam.read()
            # if ret:
                # shared_state["frame"] = frame
            frame = shared_state["frame"]
            det = cam.get_detection()
            if det: shared_state["detections"] = det

            telemetry = drone.get_telemetry()
            if telemetry:
                shared_state["is_alive"] = telemetry.get("is_alive", True)
                local_pos = telemetry.get("local_position", {})
                shared_state["alt"] = float(local_pos.get("z", 0.0)) if "z" in local_pos else None
                setpoint_vx = telemetry["setpoint_raw"]["vx"]
                setpoint_vy = telemetry["setpoint_raw"]["vy"]
                setpoint_vz = telemetry["setpoint_raw"]["vz"]
                setpoint_yaw_rate = telemetry["setpoint_raw"]["yaw_rate"]
                setpoint_speed = (setpoint_vx ** 2 + setpoint_vy ** 2) ** 0.5

            is_alive = shared_state["is_alive"]
            current_alt = shared_state["alt"]

            # 2. Логика состояния "Мертв"
            if is_alive is False:
                if was_alive is not False:
                    print("Drone is DEAD. Returning to base...")
                    drone.move_to_marker(marker_id=BASE_MARKER_ID, z=BASE_MARKER_ALT_M, speed=BASE_MOVE_SPEED)
                    was_alive = False
                
                # Сбрасываем скорости в UI и пропускаем расчет управления
                shared_state.update({"vx": 0.0, "vz": 0.0, "yaw": 0.0, "target": None, "ready_shot": False})
                time.sleep(0.1)
                continue

            # 3. Логика состояния "Жив" (Воскрешение)
            if is_alive is True and was_alive is False:
                print("Drone RESPAWNED. Resuming tracking...")
                drone.set_velocity(0.0, 0.0, 0.0, 30.0) # Начинаем крутиться для поиска
                was_alive = True
            
            if was_alive is None:
                was_alive = is_alive

            # 4. Расчет управления
            target = pick_target(shared_state["detections"], TARGET_COLOR)
            shared_state["target"] = target

            vx, vz, yaw = 0.0, 0.0, 30.0 # По умолчанию крутимся (ищем цель)
            
            if target and frame is not None:
                vx, yaw, vz = compute_control(target, frame.shape)
                
                ready = is_ready_shot(target, frame.shape)
                shared_state["ready_shot"] = ready
                if ready:
                    drone.laser_shot()
            else:
                shared_state["ready_shot"] = False
            # 5. Регулировка минимальной высоты (Защита от падения)
            if current_alt is not None and current_alt < MIN_TRACK_ALT_M:
                alt_err = MIN_TRACK_ALT_M - current_alt
                vz_up_cmd = clamp(ALT_FLOOR_K * alt_err, 0.0, MAX_VERTICAL_VZ)
                vz = max(vz, vz_up_cmd)
            elif current_alt is not None and current_alt > MAX_TRACK_ALT_M:
                alt_err = MAX_TRACK_ALT_M - current_alt
                vz_down_cmd = clamp(ALT_FLOOR_K * alt_err, -MAX_VERTICAL_VZ, 0.0)
                vz = min(vz, vz_down_cmd)
            
            shared_state.update({"vx": vx, "vz": vz, "yaw": yaw})
            if abs(setpoint_speed - vx) > 0.0001 or vz != setpoint_vz or abs(radians(yaw) - setpoint_yaw_rate) > 0.0001:
                drone.set_velocity(vx=vx, vy=0.0, vz=vz, yaw_rate=yaw)
       
            elapsed = time.time() - start_t
            time.sleep(max(0, frame_period - elapsed))
        

    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        try: drone.set_velocity(0, 0, 0, 0)
        except: pass
        try: drone.land()
        except: pass
        cam.stop_stream()
        cam.disconnect()
        drone.disconnect()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
