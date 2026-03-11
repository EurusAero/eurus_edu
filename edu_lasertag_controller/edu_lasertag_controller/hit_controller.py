#!/usr/bin/python3
import rclpy
import json
import time
import threading
import configparser
import os

from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy

from std_msgs.msg import String

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
        
        self.command_color = [255, 0, 0]
        self.hitted_color = [255, 255, 255]
        self.game_started = False
        self.led_msg = String()
        self.hitted_blinking_speed = 0.3
        
        hit_pin = 139
        if os.path.exists(ini_path):
            config = configparser.ConfigParser()
            config.read(ini_path)
            
            try:
                hit_pin = int(config.get("hit_controller", "hit_pin"))
                self.hitted_color = list(map(int, config.get("hit_controller", "hitted_color").split()))
                self.led_brightness = float(config.get("hit_controller", "led_brightness"))
                self.hitted_blinking_speed = float(config.get("hit_controller", "hitted_blinking_speed"))
            except Exception as e:
                self.get_logger().error(f"Error reading config: {e}. Using defaults.")
            
        self.hit_gpio = GpioController(hit_pin)
        
        try:
            self.hit_gpio.export()
            self.hit_gpio.set_mode("in")
        except Exception as e:
            if "Permission denied" in str(e):
                raise Exception("Permission denied for GPIO access..")
            self.get_logger().error(f"Failed to init GPIO: {e}")
            
        self.gamestart_sub = self.create_subscription(
            String,
            '/edu/game_started',
            self.gamestart_callback,
            10
        )
        self.timer = self.create_timer(0.2, self.hit_controller)
        
    def gamestart_callback(self, msg):
        try:
            data = json.loads(msg)
            
            color = data.get("command_color")
            if type(color) is str:
                if color == "blue":
                    self.command_color = [0, 0, 255]
                elif color == "red":
                    self.command_color = [255, 0, 0]
            
            elif type(color) is list:
                self.command_color = color
            
            self.game_started = data.get("game_start", False)

        except Exception as e:
            self.get_logger().error(f"Error in callback: {e}")
    
    def hit_controller(self):
        if self.game_started:
            hitted = self.hit_gpio.read()
            
            if hitted:
                msg = {
                    "command": "led_control",
                    "nLED": 30,
                    "effect": "static",
                    "brightness": self.led_brightness,
                    "color": self.command_color,
                    "speed": None
                    }
            else:
                msg = {
                    "command": "led_control",
                    "nLED": 30,
                    "effect": "blink",
                    "brightness": self.led_brightness,
                    "color": self.hitted_color,
                    "speed": self.hitted_blinking_speed
                    }
            
                
            self.led_msg.data = json.dumps(msg)
            self.led_pub.publish(self.led_msg)


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