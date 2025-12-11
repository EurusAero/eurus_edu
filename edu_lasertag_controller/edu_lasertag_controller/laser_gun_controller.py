#!/usr/bin/python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import json
import wiringpi
import time
import threading

from EurusEdu.const import *

LASER_PIN = 13

class LasertagNode(Node):
    def __init__(self):
        super().__init__('lasertag_node')
        
        try:
            wiringpi.wiringPiSetup() 
            wiringpi.pinMode(LASER_PIN, wiringpi.OUTPUT)
            wiringpi.digitalWrite(LASER_PIN, 0)
            self.get_logger().info(f"GPIO initialized. Laser Pin wPi: {LASER_PIN}")
        except Exception as e:
            self.get_logger().error(f"Failed to init wiringPi: {e}")

        # Слушаем команды
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

        self.get_logger().info(f"Lasertag Node Started. Watching /edu/lasertag...")
        
        self._shooting_lock = threading.Lock()

    def lasertag_callback(self, msg):
        try:
            data = json.loads(msg.data)
            
            cmd_name = data.get("command")
            status = data.get("status")
            timestamp = data.get("timestamp")

            if cmd_name == "shoot" and status == PENDING_STATUS:
                self.get_logger().info(f"Shoot command received (T:{timestamp}). Firing...")
                
                threading.Thread(
                    target=self.perform_shot, 
                    args=(timestamp,), 
                    daemon=True
                ).start()

        except json.JSONDecodeError:
            self.get_logger().error(f"Invalid JSON received: {msg.data}")
        except Exception as e:
            self.get_logger().error(f"Error in callback: {e}")

    def perform_shot(self, cmd_timestamp):
        """
        Выполнение выстрела и отправка ответа в edu/lasertag
        """
        if not self._shooting_lock.acquire(blocking=False):
            return

        try:
            # 1. Включаем лазер
            wiringpi.digitalWrite(LASER_PIN, 1)
            
            time.sleep(0.5)
            
            wiringpi.digitalWrite(LASER_PIN, 0)

            self.send_completed_status(cmd_timestamp)

        finally:
            self._shooting_lock.release()

    def send_completed_status(self, timestamp):
        """
        Формирует JSON с новым статусом и отправляет в edu/lasertag
        """
        response_data = {
            "timestamp": timestamp,
            "command": "shoot",
            "status": COMPLETED_STATUS,
            "message": "Shot fired successfully"
        }
        
        msg = String()
        msg.data = json.dumps(response_data)
        
        self.lasertag_pub.publish(msg)
        self.get_logger().info(f"Published completion {response_data}")

def main(args=None):
    rclpy.init(args=args)
    node = LasertagNode()
    
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        wiringpi.digitalWrite(LASER_PIN, 0)
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()