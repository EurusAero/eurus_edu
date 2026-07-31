import time

from EurusEdu import EurusControl

drone = EurusControl("192.168.1.10", 65432)

drone.arm()
time.sleep(2)
print("[MAIN] Начинаем полетную программу...")
drone.takeoff(1, speed=0.3)

time.sleep(1)
while not drone.point_reached():
    time.sleep(0.5)


drone.aruco_map_navigation(True, True)
time.sleep(5)

drone.move_to_marker(344, 1, 0.5)
time.sleep(1)
while not drone.point_reached():
    time.sleep(0.5)

drone.move_to_marker(458, 1, 0.5)
time.sleep(1)
while not drone.point_reached():
    time.sleep(0.5)

drone.land()
