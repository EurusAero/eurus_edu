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
drone.goto(1, 0, 1, 0)
time.sleep(5)
drone.goto(1, 0, 1, 0)
drone.land()
time.sleep(5)
# drone.disconnect()
# drone.disarm()
# drone.disconnect()