#!/usr/bin/python3
import rclpy
import json
import time
import threading
import configparser
import os

from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy

from std_msgs.msg import String, Bool

from EurusEdu.const import *
from EurusEdu.utils import GpioController


class HitControllerNode(Node):
    def __init__(self):
        super().__init__("hit_controller_node")
        
        home_dir = os.getenv("HOME")
        ini_path = f"{home_dir}/ros2_ws/src/eurus_edu/edu_lasertag_controller/eurus.ini"
        
        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )
        
        self.led_pub = self.create_publisher(String, 'edu/led_control', qos_profile)
        self.alive_pub = self.create_publisher(Bool, 'edu/is_alive', qos_profile)
        
        self.team_color = [255, 0, 0]
        self.hit_color = [255, 255, 255]
        self.game_started = False
        self.game_started_prev = False
        self.led_msg = String()
        self.hit_blinking_speed = 0.3
        self.nled = 45
        
        hit_pin = 139
        if os.path.exists(ini_path):
            config = configparser.ConfigParser()
            config.read(ini_path)
            
            try:
                hit_pin = int(config.get("hit_controller", "hit_pin"))
                self.hit_color = list(map(int, config.get("hit_controller", "hit_color").split()))
                self.led_brightness = float(config.get("hit_controller", "led_brightness"))
                self.hit_blinking_speed = float(config.get("hit_controller", "hit_blinking_speed"))
                self.nled = int(config.get("hit_controller", "nled"))
            except Exception as e:
                self.get_logger().warn(f"Ошибка при чтении файла конфигурации {ini_path}: {e}. Используются значения по умолчанию.")
        else:
            self.get_logger().warn(f"Файл конфигурации не обнаружен по пути: {ini_path}.") 
     
        self.hit_gpio = GpioController(hit_pin)

        self._init_gpio_with_retry(hit_pin)

        self.gamestart_sub = self.create_subscription(
            String,
            '/edu/game_started',
            self.gamestart_callback,
            10
        )
        self.timer = self.create_timer(0.2, self.hit_controller)
        self.get_logger().info("Hit controller нода создана.")

    def _init_gpio_with_retry(self, hit_pin, retry_delay=1.0):
        """
        Инициализирует GPIO через Sysfs с повторными попытками.

        При старте сервиса права на sysfs-файлы GPIO могут ещё не быть выданы
        (udev-правило применяется асинхронно), из-за чего запись падает с
        'Permission denied' (OSError). В этом случае повторяем попытку, пока
        инициализация не пройдёт успешно.
        """
        attempt = 0
        while True:
            attempt += 1
            try:
                self.hit_gpio.export()
                self.hit_gpio.set_mode("in")

                self.get_logger().info(f"GPIO инициализирован через Sysfs. GPIO попадания: {hit_pin}")
                return
            except Exception as e:
                self.get_logger().warn(
                    f"Не удалось инициализировать GPIO (попытка {attempt}): {e}. "
                    f"Повтор через {retry_delay} с..."
                )
                time.sleep(retry_delay)

    def gamestart_callback(self, msg):
        try:
            data = json.loads(msg.data)
            
            color = data.get("team_color")
            if type(color) is str:
                if color == "blue":
                    self.team_color = [0, 0, 255]
                elif color == "red":
                    self.team_color = [255, 0, 0]
            
            elif type(color) is list:
                self.team_color = color
            
            else:
                 self.team_color = (255,255,255)
            
            self.game_started = data.get("start_game", False)

            self.get_logger().info("Отправлен запрос на начало игры.")
        except json.JSONDecodeError:
            self.ros_node.get_logger().error(f"Ошибка при декодировании JSON сообщения во время коллбека начала игры: {e}")
        except Exception as e:
            self.get_logger().error(f"Ошибка при обработке запроса на начало игры: {e}")
    
    def hit_controller(self):
        try:
            if self.game_started:
                alive = self.hit_gpio.read()
                self.game_started_prev = True
                
                if alive:
                    self.alive_pub.publish(Bool(data=True))
                    
                    msg = {
                        "command": "led_control",
                        "nLED": self.nled,
                        "effect": "static",
                        "brightness": self.led_brightness,
                        "color": self.team_color,
                        "speed": None
                        }
                    
                else:
                    self.alive_pub.publish(Bool(data=False))

                    msg = {
                        "command": "led_control",
                        "nLED": self.nled,
                        "effect": "blink",
                        "brightness": self.led_brightness,
                        "color": self.hit_color,
                        "speed": self.hit_blinking_speed
                        }
                    
                    self.get_logger().info("Зарегистрировано попадание.")
                
                self.led_msg.data = json.dumps(msg)
                self.led_pub.publish(self.led_msg)
            else:
                if self.game_started_prev:
                    msg = {
                        "command": "led_control",
                        "nLED": self.nled,
                        "effect": "base",
                        "brightness": 1.0,
                        "color": [255, 255, 255],
                        "speed": None
                    }
                    self.game_started_prev = False
                    self.led_msg.data = json.dumps(msg)
                    self.led_pub.publish(self.led_msg)
        except Exception as e:
            self.get_logger().error(f"Ошибка в контроллере попадания: {e}.")

def main(args=None):
    rclpy.init(args=args)
    node = HitControllerNode()
    
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:        
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()