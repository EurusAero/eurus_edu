from EurusEdu import EurusControl
import time

drone = EurusControl("10.42.0.1", 65432)

drone.connect()

# drone.set_mode("OFFBOARD")

# time.sleep(4)
# time.sleep(2)
drone.arm()
time.sleep(10)
# drone.takeoff(2)
# time.sleep(5)
# drone.disconnect()
drone.disarm()
drone.disconnect()