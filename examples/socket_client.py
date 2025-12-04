from EurusEdu import EurusControl
import time

drone = EurusControl("10.42.0.1", 65432)

drone.connect()

# drone.set_mode("OFFBOARD")

# time.sleep(4)
# time.sleep(2)
drone.arm()
drone.takeoff(1)
time.sleep(5)
drone.move_to_local_point(0, 0, 1, 180)
time.sleep(5)
drone.move_to_local_point(1, 0, 1, 180)
time.sleep(5)
drone.land()
time.sleep(5)
drone.disconnect()
# drone.disarm()
# drone.disconnect()