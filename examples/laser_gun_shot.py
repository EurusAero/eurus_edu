from EurusEdu import EurusControl
import time

drone = EurusControl("192.168.31.120", 65432)

drone.connect()
time.sleep(1)
drone.laser_shot()
