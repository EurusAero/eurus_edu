#!/usr/bin/python3
import wiringpi
import time
import threading
import json
import sys

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

class WS2812Controller:
    def __init__(self, nLED, channel=4, port=1, speed=3200000, brightness=1.0, order="GRB"):
        self.nLED = nLED
        self.channel = channel
        self.port = port
        self.speed = speed
        self.brightness = brightness
        self.order = order.upper() # GRB или RGB
        
        self._running = False
        self._thread = None
        self._mode = "base"
        self._color = [0, 0, 0]
        self._effect_speed = 0.05
        self._step = 0
        
        # Настройка SPI
        try:
            wiringpi.wiringPiSPISetupMode(self.channel, self.port, self.speed, 0)
        except Exception as e:
            print(f"Ошибка инициализации SPI (нужны права root?): {e}")
            sys.exit(1)

    def _apply_brightness(self, rgb_list):
        b = self.brightness
        return [[int(c * b) for c in rgb] for rgb in rgb_list]

    def _encode_ws2812(self, data):
        """
        Кодировка для SPI: 1 бит данных -> 4 бита SPI.
        0 -> 1000 (0x8), 1 -> 1100 (0xC).
        """
        tx = []
        for rgb in data:
            if self.order == "GRB":
                color_bytes = (rgb[1], rgb[0], rgb[2])
            elif self.order == "RGB":
                color_bytes = (rgb[0], rgb[1], rgb[2])
            else:
                color_bytes = (rgb[1], rgb[0], rgb[2]) 

            for byte_val in color_bytes:
                for i in range(3, -1, -1):
                    bit1 = (byte_val >> (2*i + 1)) & 1
                    bit2 = (byte_val >> (2*i)) & 1
                    
                    val = 0
                    if bit1: val |= 0xC0 
                    else:    val |= 0x80 
                    
                    if bit2: val |= 0x0C 
                    else:    val |= 0x08 
                    
                    tx.append(val)
        
        tx.append(0x00)
        return bytes(tx)

    def _show(self, rgb_list):
        dimmed_list = self._apply_brightness(rgb_list)
        spi_data = self._encode_ws2812(dimmed_list)
        wiringpi.wiringPiSPIDataRW(self.channel, spi_data)
        time.sleep(0.0003) 

    def _wheel(self, pos):
        pos = pos % 256
        if pos < 85:
            return [255 - pos*3, pos*3, 0]
        elif pos < 170:
            pos -= 85
            return [0, 255 - pos*3, pos*3]
        else:
            pos -= 170
            return [pos*3, 0, 255 - pos*3]

    def _loop(self):
        while self._running:
            mode = self._mode
            delay = self._effect_speed
            
            if mode == "static":
                self._show([self._color] * self.nLED)
                time.sleep(0.1) 

            elif mode == "base":
                self._show([self._color] * self.nLED)
                time.sleep(0.1)

            elif mode == "blink":
                self._show([self._color] * self.nLED)
                time.sleep(delay)
                self._show([[0,0,0]] * self.nLED)
                time.sleep(delay)

            elif mode == "rainbow":
                frame = []
                for i in range(self.nLED):
                    idx = (i * 256 // self.nLED + self._step) % 256
                    frame.append(self._wheel(idx))
                self._show(frame)
                self._step += 1
                time.sleep(delay)

            elif mode == "komet":
                size = 5
                frame = [[0,0,0]] * self.nLED
                pos_head = self._step % (self.nLED + size)
                for i in range(size):
                    idx = pos_head - i
                    if 0 <= idx < self.nLED:
                        factor = (size - i) / size
                        frame[idx] = [int(c * factor) for c in self._color]
                self._show(frame)
                self._step += 1
                time.sleep(delay)
                
            elif mode == "clear":
                 self._show([[0,0,0]] * self.nLED)
                 time.sleep(0.1)

    def start(self):
        if not self._running:
            self._running = True
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            print("LED Controller started.")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join()
        for _ in range(3):
            self._show([[0,0,0]] * self.nLED)
            time.sleep(0.01)
        print("LED Controller stopped.")

    def set_brightness(self, val):
        self.brightness = max(0.0, min(1.0, val))

    def set_static(self, color):
        self._mode = "static"
        self._color = color
        

    def set_base(self):
        self._mode = "komet"
        self._color = [0, 0, 255]
        self._effect_speed = 0.1
        
    def set_blink(self, color, delay=0.5):
        self._mode = "blink"
        self._color = color
        self._effect_speed = delay

    def set_rainbow(self, speed=0.05):
        self._mode = "rainbow"
        self._effect_speed = speed

    def set_komet(self, color, speed=0.05):
        self._mode = "komet"
        self._color = color
        self._effect_speed = speed

    def clear(self):
        self._mode = "clear"


class LedNode(Node):
    def __init__(self, led_controller: WS2812Controller):
        super().__init__('led_controller')
        self.led = led_controller
        
        # Подписка на топик, куда API сервер кидает JSON
        self.subscription = self.create_subscription(
            String,
            'edu/led_control',
            self.listener_callback,
            10
        )
        self.get_logger().info("LED Driver Node Started. Waiting for commands on 'edu/led_control'...")

    def listener_callback(self, msg):
        try:
            data = json.loads(msg.data)
            
            command = data.get("command")
            effect = data.get("effect", "static")
            brightness = data.get("brightness", 1.0)
            color = data.get("color", [0, 0, 0])
            
            # Установка яркости
            self.led.set_brightness(brightness)
            
            self.get_logger().info(f"Received LED command: {effect} | Color: {color}")

            if effect == "base":
                self.led.set_base()
                
            elif effect == "static":
                self.led.set_static(color)
                
            elif effect == "blink":
                self.led.set_blink(color, delay=0.5)
                
            elif effect == "rainbow":
                self.led.set_rainbow(speed=0.02)
                
            elif effect == "komet":
                self.led.set_komet(color, speed=0.05)
                
            elif effect == "clear":
                self.led.clear()
            
            else:
                self.get_logger().warning(f"Unknown effect: {effect}")

        except json.JSONDecodeError:
            self.get_logger().error(f"Invalid JSON: {msg.data}")
        except Exception as e:
            self.get_logger().error(f"Error processing command: {e}")


def main(args=None):
    # Конфигурация ленты
    N_LEDS = 40
    CHANNEL = 4
    PORT = 1
    SPEED = 3200000 
    
    # Инициализация LED контроллера
    leds = WS2812Controller(nLED=N_LEDS, channel=CHANNEL, port=PORT, speed=SPEED, order="GRB")
    
    # Запускаем поток анимации светодиодов
    try:
        leds.start()
        # Включаем "base" режим по умолчанию при старте
        leds.set_base()
        # Инициализация ROS 2
        rclpy.init(args=args)
        node = LedNode(leds)
        # Spin блокирует этот поток, пока ROS узел работает
        rclpy.spin(node)
        
    except KeyboardInterrupt:
        print("\nОстановка по Ctrl+C")
    except Exception as e:
        print(f"Критическая ошибка: {e}")
    finally:
        # Корректное завершение
        leds.stop()
        if rclpy.ok():
            node.destroy_node()
            rclpy.shutdown()

if __name__ == "__main__":
    main()