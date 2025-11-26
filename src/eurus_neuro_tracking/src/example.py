from eurus_mavlink.controller import EurusController

controller = EurusController()
controller.connect()
controller.set_mode("OFFBOARD")
# controller.arm()

# controller.takeoff(2)

# controller.land()

# controller.disarm()
# controller.disconnect()