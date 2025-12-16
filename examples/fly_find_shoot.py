from EurusEdu import EurusControl, EurusCamera
import time
import threading
import cv2
import numpy as np

class TargetFinder:
    def __init__(self, ip="10.42.0.1", drone_port=65432, camera_port=8001, target_red = True, target_blue = False):
        self.drone = EurusControl(ip, drone_port)
        self.camera = EurusCamera(ip, camera_port)

        self.target_blue = target_blue
        self.target_red = target_red

        print("1. Подключение...")
        self.drone.connect()
        self.camera.connect()
        
        print("2. Запуск видеопотока...")
        self.camera.start_stream()
        

        self.closest_red_target = None
        self.closest_blue_target = None
        self.closest_target = None
        self.all_targets = None 
        self.running = True

    def start(self):
        # Запускаем потоки обработки данных и управления
        targets_thread = threading.Thread(target=self.targets_update, daemon=True)
        targets_thread.start()
        
        control_thread = threading.Thread(target=self.start_tracking, daemon=True)
        control_thread.start()
    
    def targets_update(self):
        while self.running:
            try:
                # Получаем цели (класс EurusCamera сам отправляет запрос внутри)
                targets = self.camera.get_targets()
                self.all_targets = targets 
                
                temp_closest = None
                
                if self.target_red and targets and isinstance(targets, dict) and "red_targets" in targets:
                    red_list = targets["red_targets"]
                    if red_list:
                        # Ищем цель с самой большой высотой (h)
                        for red_target in red_list:
                            if temp_closest is None:
                                temp_closest = red_target
                            elif red_target["h"] > temp_closest["h"]:
                                temp_closest = red_target
                    
                    self.closest_red_target = temp_closest
                    if self.closest_target is not None and self.closest_red_target["h"] < self.closest_target["h"]:
                        self.closest_target = self.closest_red_target
                    else:
                        self.closest_target = self.closest_target
                else:
                    self.closest_red_target = None

                if self.target_blue and targets and isinstance(targets, dict) and "blue_targets" in targets:
                    blue_list = targets["blue_targets"]
                    if blue_list:
                        # Ищем цель с самой большой высотой (h)
                        for blue_target in blue_list:
                            if temp_closest is None:
                                temp_closest = blue_target
                            elif blue_target["h"] > temp_closest["h"]:
                                temp_closest = blue_target
                    
                    self.closest_blue_target = temp_closest
                    if self.closest_target is not None and self.closest_red_target["h"] < self.closest_target["h"]:
                        self.closest_target = self.closest_red_target
                    else:
                        self.closest_target = self.closest_target
                else:
                    self.closest_blue_target = None
                
                if self.closest_blue_target is not None:
                    if self.closest_red_target is not None:
                        if 
                    
            except Exception as e:
                print(f"Error targets: {e}")
                
            time.sleep(0.05)
    
    def start_tracking(self):
        self.drone.arm()
        time.sleep(2)
        self.drone.takeoff(1)
        time.sleep(5)
        yaw_reached = False
        z_reached = False
        x_reached = False
        while self.running:
            if self.closest_red_target is not None:
                last_target_found = time.time()
                # Координаты и размеры
                tx = self.closest_red_target["x"]
                ty = self.closest_red_target["y"]
                th = self.closest_red_target["h"]
                                
                # Yaw (поворот) - держим x=320 (центр кадра 640x480)
                if tx > 360: yaw_rate = -10
                elif tx < 280: yaw_rate = 10
                else:
                    yaw_rate = 0
                
                # Z (высота) - держим y=240
                if ty > 280: vz = -0.1
                elif ty < 200: vz = 0.1
                else:
                    vz = 0
                
                if th > 150: vx = -0.1  # Слишком близко
                elif th < 100: vx = 0.1 # Слишком далеко
                else:
                    vx = 0
                
                # print(f"Track: vX={vx} vZ={vz} Yaw={yaw_rate} (H={th})")
                self.drone.set_velocity(vx, 0, vz, yaw_rate)
                
            else:
                if (time.time() - last_target_found) >= 5:
                    self.drone.set_velocity(0, 0, 0, 20)
                else:
                    self.drone.set_velocity(0, 0, 0, 0)
            
            time.sleep(0.05)

    def draw_target(self, img, target, color, thickness):
        try:
            x, y = int(target["x"]), int(target["y"])
            w, h = int(target["w"]), int(target["h"])
            
            top_left = (int(x - w / 2), int(y - h / 2))
            bottom_right = (int(x + w / 2), int(y + h / 2))
            
            cv2.rectangle(img, top_left, bottom_right, color, thickness)
            cv2.circle(img, (x, y), 2, color, -1)
        except:
            pass

    def run_display(self):
        print("Открываю окно просмотра...")
        cv2.namedWindow("Eurus View", cv2.WINDOW_NORMAL)
        
        while self.running:
            # Используем метод read() из вашего класса EurusCamera
            ret, frame = self.camera.read()
            
            if ret and frame is not None:
                # 1. Рисуем все найденные (синим)
                if self.all_targets and "red_targets" in self.all_targets:
                    for t in self.all_targets["red_targets"]:
                        self.draw_target(frame, t, (255, 0, 0), 1)

                # 2. Рисуем ту, за которой летим (зеленым)
                if self.closest_red_target:
                    self.draw_target(frame, self.closest_red_target, (0, 255, 0), 3)
                    
                    # Инфо на экране
                    info = f"DIST(H): {int(self.closest_red_target['h'])}"
                    cv2.putText(frame, info, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

                # 3. Прицел
                h, w = frame.shape[:2]
                cv2.line(frame, (w//2, h//2-20), (w//2, h//2+20), (0,255,255), 2)
                cv2.line(frame, (w//2-20, h//2), (w//2+20, h//2), (0,255,255), 2)
                
                cv2.imshow("Eurus View", frame)
                
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    self.running = False
                    break
            else:
                # Если кадр не пришел, немного ждем, чтобы не грузить CPU
                time.sleep(0.01)

        # Очистка
        self.camera.stop_stream()
        self.camera.disconnect()
        cv2.destroyAllWindows()
        self.drone.land()

if __name__ == "__main__":
    # IP адрес дрона/сервера
    finder = TargetFinder("10.42.0.1")
    
    # Запускаем логику в фоне
    finder.start()
    
    # Запускаем отрисовку в главном потоке
    try:
        finder.run_display()
    except KeyboardInterrupt:
        finder.running = False