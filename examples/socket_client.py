from EurusEdu import EurusControl
import time
import threading

def telem_thread(drone: EurusControl):
    # Проверяем, что дрон подключен, чтобы цикл остановился при дисконнекте
    while drone.is_connected:  
        try:
            a = drone.request_telemetry()
            # if a: print(a) # Лучше проверять, пришло ли что-то
            # print(a)
            time.sleep(1)
        except Exception:
            break

drone = EurusControl("10.42.0.1", 65432)
drone.connect()

# b = threading.Thread(target=telem_thread, args=(drone, ), daemon=True)
# b.start()

drone.arm()
time.sleep(1)
drone.takeoff(1)
time.sleep(5)
drone.set_velocity(0.5, 0, 0)
# drone.move_in_body_frame(0.5, 0, 2, 180)
# time.sleep(5)
# drone.move_in_body_frame(0, -0.5, 2, 180)
# time.sleep(5)
# drone.move_in_body_frame(-0.5, 0, 2, 180)
time.sleep(1)
# drone.set_velocity(0, 0.5, 0, 0)
drone.move_to_local_point(0, 0, 1)
time.sleep(1)
drone.set_velocity(0, 0, 0, 0)
time.sleep(1)
drone.land()
# drone.set_velocity(0, 0, 0, 0)
# try:
#     print("Программа запущена. Нажмите Ctrl+C для выхода.")
#     while True:
#         time.sleep(1) # Просто крутимся и ждем прерывания``

# except KeyboardInterrupt:
#     print("\n[Main] Нажат Ctrl+C! Завершаем работу...")
#     drone.disconnect() # Корректно закрываем сокеты
#     # Поток 'b' сам умрет, так как он daemon=True и основной поток завершается