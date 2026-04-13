from EurusEdu import EurusControl
import time

drone = EurusControl("10.42.0.1", 65432)

drone.connect()
time.sleep(1)
print("Статическое свечение")
drone.led_control("static", 255, 255, 0, brightness=0.1,nLED=50)
time.sleep(5)

print("Статическое свечение")
drone.led_control("static", 0, 255, 255, brightness=0.1,nLED=50)
time.sleep(5)

print("Статическое свечение")
drone.led_control("static", 255, 0, 255, brightness=0.1,nLED=50)
time.sleep(5)

drone.led_control(effect="blink", r=255, g=255, b=255, nLED=16, brightness=0.1)
