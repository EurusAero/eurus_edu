from EurusEdu import EurusControl
import time

drone = EurusControl("10.42.0.1", 65432)

drone.connect()

drone.arm()
time.sleep(4)
drone.disarm()
