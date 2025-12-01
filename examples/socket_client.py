from EurusEdu import EurusControl

drone = EurusControl("192.168.31.164", 65432)

drone.connect()
drone.arm()
drone.takeoff(2)