import time
from EurusEdu import EurusControl

def run_square_mission():
    # --- НАСТРОЙКИ ---
    IP_ADDRESS = "10.42.0.1"
    PORT = 65432
    ALTITUDE = 1              
    SIDE_LENGTH = 0.5            
    LAPS = 1       
    SPEED = 0.2              
    
    # Настройки LED
    # Количество светодиодов
    LEDS_COUNT = 20 
    
    drone = EurusControl(ip=IP_ADDRESS, port=PORT)

    try:
        drone.connect()
        time.sleep(1)
        
        if not drone.is_connected:
            print("Не удалось подключиться к дрону.")
            return

        print("Начало миссии")

        # 1. ПОДГОТОВКА И ВЗЛЕТ (Эффект: BLINK, Желтый)
        print("Включаем мигание (желтый) перед взлетом...")
        drone.led_control(effect="blink", r=255, g=255, b=0, nLED=LEDS_COUNT)
        
        print("Арминг...")
        drone.arm()
        
        print(f"Взлет на высоту {ALTITUDE}м...")
        drone.takeoff(ALTITUDE, speed=SPEED)
        
        # Пауза, чтобы дрон стабилизировался перед полетом
        time.sleep(10)

        # 2. ПОЛЕТ ПО КВАДРАТУ
        print("Включаем эффект 'komet' (синий) для полета...")
        drone.led_control(effect="komet", r=0, g=0, b=255, nLED=LEDS_COUNT)

        for lap in range(1, LAPS + 1):
            print(f"\n--- Круг №{lap} ---")
            
            # Точка 1
            drone.move_to_local_point(x=SIDE_LENGTH, y=SIDE_LENGTH, z=ALTITUDE, speed=SPEED)
            time.sleep(8)
            # Точка 2
            drone.move_to_local_point(x=SIDE_LENGTH, y=-SIDE_LENGTH, z=ALTITUDE, speed=SPEED)
            time.sleep(8)
            # Точка 3
            drone.move_to_local_point(x=-SIDE_LENGTH, y=-SIDE_LENGTH, z=ALTITUDE, speed=SPEED)
            time.sleep(8)
            # Точка 4 (Возврат)
            drone.move_to_local_point(x=-SIDE_LENGTH, y=SIDE_LENGTH, z=ALTITUDE, speed=SPEED)
            time.sleep(8)
            drone.move_to_local_point(x=0, y=0, z=ALTITUDE, speed=SPEED)
            time.sleep(8)

        print("\nПолетная программа завершена.")

    except KeyboardInterrupt:
        print("\nМиссия прервана пользователем!")
    except Exception as e:
        print(f"\nПроизошла ошибка: {e}")
    finally:
        # 3. ПОСАДКА
        if drone.is_connected:
            print("Включаем мигание (красный) для посадки...")
            drone.led_control(effect="blink", r=255, g=0, b=0, nLED=LEDS_COUNT)
            
            print("Приземление...")
            drone.land()
            
            # Ждем пока сядет
            time.sleep(3) 
            
            # Выключаем ленту перед разрывом соединения
            print("Выключение подсветки...")
            drone.led_control(effect="static", r=0, g=0, b=0, nLED=LEDS_COUNT)
            
            print("Отключение...")
            drone.disconnect()

if __name__ == "__main__":
    run_square_mission()