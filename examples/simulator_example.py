import time

from EurusEdu import EurusControl

drone = EurusControl("10.42.0.1", 65432)

drone.connect()
time.sleep(1)
drone.arm()
time.sleep(1)

drone.takeoff(1.5)
time.sleep(1)
while not drone.point_reached():
    time.sleep(0.5)

for i in range(10):
    drone.laser_shot()
    time.sleep(1)

drone.move_in_body_frame(1.5, 0, 1.5)
while not drone.point_reached():
    time.sleep(0.5)

for i in range(10):
    drone.laser_shot()
    time.sleep(1)

# drone.move_to_local_point(11, 11, 2)
# time.sleep(30)

# drone.move_to_local_point(-10, -10, 2)
# time.sleep(30)
