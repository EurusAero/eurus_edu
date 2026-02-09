import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
import json
import cv2
import numpy as np
import time
import configparser
import os

from std_msgs.msg import Bool
from sensor_msgs.msg import CompressedImage

class ArucoDetector(Node):
    def __init__(self):
        super().__init__('aruco_detection')

        camera_qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=1
        )
        
        map_qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.Reliable,
            history=HistoryPolicy.KEEP_LAST,
            depth=5
        )
        
        home_dir = os.getenv("HOME")
        config_path = f"{home_dir}/ros2_ws/src/eurus_edu/edu_aruco_navigation/eurus.ini"
        
        dictionary = "4X4_50"
        camera_topic = "/edu/camera_frame"
        frequency = 30
        self.aruco_map_path = ""
        
        if os.path.exists(config_path):
            config = configparser.ConfigParser()
            config.read(config_path)
            
            dictionary = config["aruco"].get("dict", dictionary)
            
            frequency = config["settings"].getint("frequency", frequency)
            camera_topic = config["settings"].get("camera_topic", camera_topic)
            self.aruco_map_path = config["aruco"].get("map_path", self.aruco_map_path)
            
            if dictionary not in self.aruco_dicts:
                dictionary = "4X4_50"
        
        if not os.path.exists(self.aruco_map_path):
            self.aruco_map_path = ""
        
        self.create_subscription(
            CompressedImage,
            camera_topic,
            self.camera_sub,
            camera_qos_profile
            )
        
        self.create_subscription(
            Bool,
            "/edu/aruco_map_nav",
            self.map_navigation_sub,
            map_qos_profile
        )
        
        self.aruco_debug_pub = self.create_publisher(CompressedImage, "/edu/aruco_debug", camera_qos_profile)

        self.debug_msg = CompressedImage()
        self.navigation_state = Bool()

        self.aruco_dicts = {
            "4X4_50": cv2.aruco.DICT_4X4_50,
            "4X4_100": cv2.aruco.DICT_4X4_100,
            "4X4_250": cv2.aruco.DICT_4X4_250,
            "4X4_1000": cv2.aruco.DICT_4X4_1000,
            "5X5_50": cv2.aruco.DICT_5X5_50,
            "5X5_100": cv2.aruco.DICT_5X5_100,
            "5X5_250": cv2.aruco.DICT_5X5_250,
            "5X5_1000": cv2.aruco.DICT_5X5_1000,
            "6X6_50": cv2.aruco.DICT_6X6_50,
            "6X6_100": cv2.aruco.DICT_6X6_100,
            "6X6_250": cv2.aruco.DICT_6X6_250,
            "6X6_1000": cv2.aruco.DICT_6X6_1000,
            "7X7_50": cv2.aruco.DICT_7X7_50,
            "7X7_100": cv2.aruco.DICT_7X7_100,
            "7X7_250": cv2.aruco.DICT_7X7_250,
            "7X7_1000": cv2.aruco.DICT_7X7_1000
        }
        
        self.last_frame = None
            
        aruco_dict = cv2.aruco.getPredefinedDictionary(self.aruco_dicts[dictionary])
        parameters = cv2.aruco.DetectorParameters()
        self.aruco_detector = cv2.aruco.ArucoDetector(aruco_dict, parameters)

        timer_period = 1 / frequency
        self.timer = self.create_timer(timer_period, self.aruco_handler)
    
    def camera_sub(self, msg):
        np_arr = np.frombuffer(msg.data, np.uint8)
        self.last_frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    
    def map_navigation_sub(self, msg):
        self.navigation_state = msg.value
    
    def aruco_handler(self):
        if self.last_frame is None:
            return None
        
        self.debug_msg.header.stamp = self.get_clock().now().to_msg()
        self.debug_msg.header.frame_id = "aruco"
        self.debug_msg.format = "jpeg"
        
        image = self.last_frame.copy()
        
        corners, ids = self.detect_aruco(image)
        
        if self.aruco_map_path:
            self.detect_board()
        
        if ids is not None:
            image = self.draw_aruco(image, corners, ids)
        
        success, encoded_image = cv2.imencode(".jpg", image)
        if success:
            self.debug_msg.data = encoded_image.tobytes()
            self.aruco_debug_pub.publish(self.debug_msg)
            
    def detect_aruco(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        corners, ids, _ = self.aruco_detector.detectMarkers(gray)
        
        return corners, ids

    def detect_board(self):
        pass
    
    def parse_map_file(self):
        pass
    
    def draw_aruco(self, image, aruco_corners, aruco_ids):
        cv2.aruco.drawDetectedMarkers(image, aruco_corners, aruco_ids)

        return image
        

def main(args=None):
    rclpy.init()
    node = ArucoDetector()
    rclpy.spin(node)
