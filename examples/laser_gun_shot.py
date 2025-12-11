from EurusEdu import EurusControl
import time

drone = EurusControl("192.168.31.120", 65432)

drone.connect()
time.sleep(5)
drone.laser_shot()
time.sleep(2)