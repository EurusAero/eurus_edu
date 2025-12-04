from EurusEdu import EurusControl
import time

drone = EurusControl("10.42.0.1", 65432)

drone.connect()

drone.arm()
drone.takeoff(1)
time.sleep(5)
drone.move_to_local_point(0, 0, 1, 0)
time.sleep(5)
drone.move_to_local_point(1, 0, 1, 0)
time.sleep(5)
drone.move_to_local_point(1, 1, 1, 0)
time.sleep(5)
drone.land()
time.sleep(5)
drone.disconnect()
