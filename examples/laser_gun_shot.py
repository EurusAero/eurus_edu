from EurusEdu import EurusControl
import time

drone = EurusControl("192.168.31.164", 65432)

drone.connect()
time.sleep(2)
drone.laser_shot()