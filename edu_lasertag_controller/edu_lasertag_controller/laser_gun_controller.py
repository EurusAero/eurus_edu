#!/usr/bin/python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import json
import time
import threading

from EurusEdu.const import *
from EurusEdu.utils import GpioController

LASER_PIN = 92

class LasertagNode(Node):
    def __init__(self):
        super().__init__('lasertag_node')
        
        self.laser_gpio = GpioController(LASER_PIN)
        
        try:
            self.laser_gpio.export()     
            self.laser_gpio.set_mode("out")
            self.laser_gpio.write(0)
            
            self.get_logger().info(f"GPIO initialized via Sysfs. Laser GPIO: {LASER_PIN}")
        except Exception as e:
            if "Permission denied" in str(e):
                raise Exception("Permission denied for GPIO access..")
            self.get_logger().error(f"Failed to init GPIO: {e}")

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
            self.get_logger().warn("Shot ignored: already shooting.")
            return

        try:
            self.laser_gpio.write(1)
            
            time.sleep(0.5)
            
            self.laser_gpio.write(0)

            self.send_completed_status(cmd_timestamp)

        except Exception as e:
            self.get_logger().error(f"Hardware error during shot: {e}")
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
        try:
            node.laser_gpio.write(0)
            # node.laser_gpio.cleanup()
        except:
            pass
            
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()