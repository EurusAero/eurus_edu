from EurusEdu import EurusControl
import time

drone = EurusControl("10.42.0.1", 65432)

drone.connect()
time.sleep(1)
print("Статическое свечение")
drone.led_control("static", 255, 50, 0, 50, brightness=0.1)

drone.disconnect()