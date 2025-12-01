from EurusEdu import EurusControl

drone = EurusControl("192.168.31.251", 65432)

drone.connect()
drone.arm()
drone.takeoff(2)