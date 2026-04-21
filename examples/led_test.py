from EurusEdu import EurusControl
import time

drone = EurusControl("10.42.0.1", 65432)

drone.connect()
time.sleep(1)
print("Базовый режим - режим кометы с белым цветом")
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
drone.led_control(effect="blink", r=255, g=255, b=255, nLED=16, brightness=0.1)
time.sleep(5)

print('Выключение подсветки...')
drone.led_control("static", 0, 0, 0)
