from EurusEdu import EurusControl
import time

drone = EurusControl("192.168.31.120", 65432)

drone.connect()
time.sleep(1)
print("Базовый режим - свечение синим")
drone.led_control("base")
time.sleep(5)
print("Статическое свечение")
drone.led_control("static", 255, 255, 0, brightness=0.5)
time.sleep(5)
print("Радуга")
drone.led_control("rainbow")
time.sleep(5)
print("Комета")
drone.led_control("komet", 255, 0, 0)
time.sleep(5)
