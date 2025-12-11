from EurusEdu import EurusControl
import time

drone = EurusControl("192.168.31.120", 65432)
drone.connect()

drone.move_to_local_point(0, 0, 0)

# while not drone.point_reached():
#     print(1)
#     time.sleep(0.1)
