import time

from EurusEdu import EurusControl

drone = EurusControl("192.168.1.10", 65432)

drone.connect()
time.sleep(2)

drone.start_game(True, "red")
time.sleep(1)

for i in range(20):
    drone.laser_shot()
    time.sleep(0.5)
