from EurusEdu import EurusControl
import time

drone = EurusControl("10.42.0.1", 65432, socket_timeout_time=7)

drone.connect()
time.sleep(1)
print("Статическое свечение")
drone.led_control("static", 155, 155, 0, brightness=0.1,nLED=50)
time.sleep(5)
drone.sock.close()
print(drone.get_telemetry())
print(drone.point_reached())

print("Статическое свечение")
drone.led_control("static", 0, 155, 155, brightness=0.1,nLED=50)
time.sleep(5)

print(drone.laser_shot())
print(drone.get_telemetry())

print("Статическое свечение")
drone.led_control("static", 255, 105, 105, brightness=0.1,nLED=50)
time.sleep(5)

drone.disconnect()