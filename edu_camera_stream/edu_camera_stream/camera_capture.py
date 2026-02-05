import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
import cv2
import numpy as np
import os
import configparser
from sensor_msgs.msg import CompressedImage 
import time

class MJPEGCameraPublisher(Node):
    def __init__(self):
        super().__init__('camera_capture')
        
        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=1
        )
        
        self.pub = self.create_publisher(CompressedImage, '/edu/camera_frame', qos_profile)
        
        config = configparser.ConfigParser()
        config_path = "/home/orangepi/ros2_ws/src/eurus_edu/edu_camera_stream/eurus.ini" 
        
        self.camera_is_open = False
        self.camera_lost_timestamp = 0
        
        self.cap = None
        self.width = 640
        self.height = 480
        self.fps = 30
        self.device = "/dev/video0"
        
        if os.path.exists(config_path):
            self.get_logger().info(f"Loading config from {config_path}")
            config.read(config_path)
            if "camera" in config:
                self.width = config["camera"].getint("width", self.width)
                self.height = config["camera"].getint("height", self.height)
                self.fps = config["camera"].getint("fps", self.fps)
                dev_str = config["camera"].get("device", str(self.device))
                self.device = int(dev_str) if dev_str.isdigit() else dev_str
        
        self.setup_camera()
        
        self.timer = self.create_timer(1.0 / self.fps, self.timer_callback)
        
    def setup_camera(self):
        self.cap = cv2.VideoCapture(self.device)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)        

    def timer_callback(self):
        ret, frame = self.cap.read()
        if ret:
            if not self.camera_is_open:
                self.camera_is_open = True
            
            msg = CompressedImage()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.header.frame_id = "camera_frame"
            msg.format = "jpeg" 

            # success, encoded_img = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            success, encoded_img = cv2.imencode('.jpg', frame)
            if success:
                msg.data = encoded_img.tobytes()
                self.pub.publish(msg)
        else:
            if self.camera_is_open:
                self.camera_is_open = False
                self.camera_lost_timestamp = time.time()

            if (time.time() - self.camera_lost_timestamp) > 0.5:
                self.setup_camera()
                self.camera_lost_timestamp = time.time()
            
    def __del__(self):
        if self.cap.isOpened():
            self.cap.release()

def main():
    rclpy.init()
    node = MJPEGCameraPublisher()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()