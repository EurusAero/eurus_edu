from EurusEdu import EurusControl

drone = EurusControl("127.0.0.1", 65432)

drone.connect()
drone.arm()
drone.takeoff(2)