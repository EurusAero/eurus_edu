#!/usr/bin/python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import json
import time
import threading
import configparser
import os

from EurusEdu.const import *
from EurusEdu.utils import GpioController


class LasertagNode(Node):
    def __init__(self):
        super().__init__('lasertag_node')
        
        home_dir = os.getenv("HOME")
        ini_path = f"{home_dir}/ros2_ws/src/eurus_edu/edu_lasertag_controller/eurus.ini"
        
        laser_pin = 138
        shots_amount = 5
        if os.path.exists(ini_path):
            config = configparser.ConfigParser()
            config.read(ini_path)
            
            try:
                laser_pin = int(config.get("laser_gun", "shot_pin"))
                shots_amount = int(config.get("laser_gun", "shots_per_command"))
            except Exception as e:
                self.get_logger().error(f"Ошибка при чтении файла конфигурации - {ini_path}: {e}. Используются дефолтные значения.")
        else:
            self.get_logger().warn(f"Не обнаружен файл конфигурации по пути - {ini_path}. Используются дефолтные значения")
        
        self.shooting_sleep = shots_amount * 0.1
        
        self.laser_gpio = GpioController(laser_pin)
        
        try:
            self.laser_gpio.export()     
            self.laser_gpio.set_mode("out")
            self.laser_gpio.write(0)
            
            self.get_logger().info(f"GPIO инициализирован через Sysfs. GPIO лазера: {laser_pin}")
        except Exception as e:
            self.get_logger().error(f"Ошибка при инициализации GPIO: {e}")

        self.lasertag_sub = self.create_subscription(
            String,
            '/edu/lasertag',
            self.lasertag_callback,
            10
        )

        self.lasertag_pub = self.create_publisher(
            String,
            '/edu/lasertag',
            10
        )

        self.get_logger().info(f"Lasertag нода создана. Слушает /edu/lasertag...")
        
        self._shooting_lock = threading.Lock()

    def lasertag_callback(self, msg):
        try:
            data = json.loads(msg.data)
            
            cmd_name = data.get("command")
            status = data.get("status")
            timestamp = data.get("timestamp")

            if cmd_name == "shoot" and status == PENDING_STATUS:
                self.get_logger().info(f"Команда на выстрел получена (T:{timestamp}). Выстрел...")
                
                threading.Thread(
                    target=self.perform_shot, 
                    args=(timestamp,), 
                    daemon=True
                ).start()

        except json.JSONDecodeError:
            self.get_logger().error(f"Получен некорректный JSON в lasertag_callback: {msg.data}")
        except Exception as e:
            self.get_logger().error(f"Ошибка при обработке сообщения в lasertag_callback: {e}")

    def perform_shot(self, cmd_timestamp):
        if not self._shooting_lock.acquire(blocking=False):
            self.get_logger().warn("Команда выстрела проигнорирована: уже стреляет.")
            return

        try:
            self.laser_gpio.write(1)
            
            time.sleep(self.shooting_sleep)
            
            self.laser_gpio.write(0)

            self.send_completed_status(cmd_timestamp)

        except Exception as e:
            self.get_logger().error(f"Ошибка во время выстрела: {e}")
        finally:
            self._shooting_lock.release()

    def send_completed_status(self, timestamp):
        response_data = {
            "timestamp": timestamp,
            "command": "shoot",
            "status": COMPLETED_STATUS,
            "message": "Выстрел произведён успешно."
        }
        
        msg = String()
        msg.data = json.dumps(response_data)
        
        self.lasertag_pub.publish(msg)
        self.get_logger().info(f"Публикация завершена. Ответ: {response_data}")

def main(args=None):
    rclpy.init(args=args)
    node = LasertagNode()
    
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            node.laser_gpio.write(0)
        except:
            pass
            
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()