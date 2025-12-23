from EurusEdu import EurusControl, EurusCamera

import time
import threading
import cv2
import numpy as np

class TargetFinderAndShooter:
    def __init__(self, ip="10.42.0.1", drone_port=65432, camera_port=8001, target_red = True, target_blue = False, switch_between = False):
        self.drone = EurusControl(ip, drone_port)
        self.camera = EurusCamera(ip, camera_port)

        self.camera_wit = 720
        self.wit_diviation = 20
        self.camera_height = 480
        self.height_diviation = 20

        self.max_h = 150
        self.min_h = 50

        self.shoot = False

        self.target_blue = target_blue
        self.target_red = target_red

        if self.target_blue and self.target_red:
            self.switch_between = switch_between 
        else:
            self.switch_between = False

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

        self.speed_mod = 2.0

        # shoot, search, track, takeoff, land
        self.drone.led_control(effect = "static",r = 100,g = 100,b = 100, nLED = 16, brightness = 1)
        self.mode = "default"
        self.modes = {
            "shoot" : ["blink", 255, 0, 0, 16, 1],
            "search" : ["static", 0, 150, 150, 16, 1],
            "track" : ["static", 0, 255, 0, 16, 1],
            "takeoff" : ["blink", 0, 0, 255, 16, 1],
            "land" : ["blink", 0, 255, 0, 16 ,1],
            "default" : ["static", 100, 100, 100, 16 ,1],
            "arm" : ["blink", 255, 255, 255, 16 ,1]
        }
    
    def change_mod(self, mod : str):
        if mod in self.modes.keys() and self.mode != mod:
            self.mode = mod
            mod_param = self.modes[mod]
            self.drone.led_control(effect = mod_param[0],r = mod_param[1],g = mod_param[2],b = mod_param[3], nLED = mod_param[4], brightness = mod_param[5])

    def start(self):
        # Запускаем потоки обработки данных и управления
        targets_thread = threading.Thread(target=self.targets_update, daemon=True)
        targets_thread.start()
        
        control_thread = threading.Thread(target=self.start_tracking, daemon=True)
        control_thread.start() 

        shoot_thread = threading.Thread(target=self.shooter_thread, daemon=True)
        shoot_thread.start() 
    
    def shooter_thread(self):
        while self.running:
            try:
                if self.shoot:
                    self.shoot = False
                    res = self.drone.laser_shot()
                    print("IGiygfyuohaoug")
                    if self.switch_between and res:
                        if self.closest_target["class"] == "red target":
                            self.target_red = False
                            self.target_blue = True
                        else: 
                            self.target_blue = False
                            self.target_red = True
                    
            except Exception as e:
                print(f"Error targets: {e}")
                
            time.sleep(0.05)

    def targets_update(self):
        while self.running:
            try:
                # Получаем цели (класс EurusCamera сам отправляет запрос внутри)
                targets = self.camera.get_targets()
                #print(targets)
                #time.sleep(3)
                self.all_targets = targets 
                self.closest_target = None
                self.closest_blue_target = None
                self.closest_red_target = None
                
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
                    self.closest_red_target = None
                temp_closest = None
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
                    if self.closest_target is not None and self.closest_blue_target["h"] < self.closest_target["h"]:
                        self.closest_target = self.closest_blue_target
                else:
                    self.closest_blue_target = None

                if self.closest_target is None and (self.closest_blue_target is not None or self.closest_red_target is not None):
                    if self.closest_red_target is not None:
                        if self.closest_blue_target is not None:
                            if self.closest_blue_target["h"] < self.closest_red_target["h"]:
                                self.closest_target = self.closest_blue_target
                            else:
                                self.closest_target = self.closest_red_target
                        else:
                            self.closest_target = self.closest_red_target
                    else:
                        self.closest_target = self.closest_blue_target
                    
            except Exception as e:
                print(f"Error targets: {e}")
                
            time.sleep(0.05)
    
    def start_tracking(self):
        self.change_mod("arm")
        self.drone.arm()
        #self.drone.set_velocity(0, 0, 0, 0)
        time.sleep(2)
        self.change_mod("takeoff")
        self.drone.takeoff(1.5)
        time.sleep(5)
        self.change_mod("search")
        last_target_found = time.time()
        last_shot_time = time.time() - 10
        while self.running:
            vx = 0
            vy = 0 
            vz = 0 
            yaw_rate = 0
            if self.closest_target is not None:
                if time.time() - last_shot_time > 1:
                    self.change_mod("track")
                last_target_found = time.time()
                # Координаты и размеры
                tx = self.closest_target["x"]
                ty = self.closest_target["y"]
                th = self.closest_target["h"]
                                
                # Yaw (поворот) - держим x=320 (центр кадра 640x480)
                if tx > self.camera_wit/2 + self.wit_diviation: yaw_rate = -10
                elif tx < self.camera_wit/2 - self.wit_diviation: yaw_rate = 10
                else:
                    yaw_rate = 0
                
                # Z (высота) - держим y=240
                if ty > self.camera_height/2 + self.height_diviation: vz = -0.1
                elif ty < self.camera_height/2 - self.height_diviation: vz = 0.1
                else:
                    vz = 0
                
                if th > self.max_h: vx = -0.1  # Слишком близко
                elif th < self.min_h: vx = 0.1 # Слишком далеко
                else:
                    vx = 0

                # Если достаточно близко к цели стреляет в неё каждые 5 сек
                if th > self.min_h and th < self.max_h and time.time() - last_shot_time > 5:
                    self.change_mod("shoot")
                    last_shot_time = time.time()
                    #threading.Thread()
                    self.shoot = True
                
            else:
                if (time.time() - last_target_found) >= 5:
                    self.change_mod("search")
                    yaw_rate = 20
                    # pass
                        
            self.drone.set_velocity(vx * self.speed_mod, 0 * self.speed_mod, vz * self.speed_mod, yaw_rate)

            time.sleep(0.05)
        else: 
            self.change_mod("search")

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

        cv2.namedWindow("Eurus View", cv2.WINDOW_AUTOSIZE)
        
        while self.running:
            # Используем метод read() из вашего класса EurusCamera
            ret, frame = self.camera.read()
            
            if ret and frame is not None:
                # 1. Рисуем все найденные (синим)
                if self.all_targets:
                    for t in self.all_targets["red_targets"]:
                        self.draw_target(frame, t, (255, 0, 0), 1)
                    for t in self.all_targets["blue_targets"]:
                        self.draw_target(frame, t, (0, 0, 255), 1)

                # 2. Рисуем ту, за которой летим (зеленым)
                if self.closest_target:
                    self.draw_target(frame, self.closest_target, (0, 255, 0), 3)
                    
                    # Инфо на экране
                    info = f"DIST(H): {int(self.closest_target['h'])}"
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
    # Создание объекта для трекинга и стрельбы по целям задаются параметры
    # IP адрес дрона/сервера 
    # стрелять и искать синие цели
    # стрелять и искать краснные цели
    finder = TargetFinderAndShooter("10.42.0.1",target_blue= True, target_red= False, switch_between = False)
    
    # Запускаем логику в фоне
    finder.start()
    
    # Запускаем отрисовку в главном потоке
    try:
        finder.run_display()
    except KeyboardInterrupt:
        finder.running = False