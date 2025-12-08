import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
import cv2
import numpy as np
import os
import configparser
from sensor_msgs.msg import CompressedImage 

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
        
        width = 640
        height = 480
        fps = 30
        device = "/dev/video0"
        
        if os.path.exists(config_path):
            self.get_logger().info(f"Loading config from {config_path}")
            config.read(config_path)
            if "camera" in config:
                width = config["camera"].getint("width", width)
                height = config["camera"].getint("height", height)
                fps = config["camera"].getint("fps", fps)
                dev_str = config["camera"].get("device", str(device))
                device = int(dev_str) if dev_str.isdigit() else dev_str
                
        self.cap = cv2.VideoCapture(device)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, fps)

        self.timer = self.create_timer(1.0 / fps, self.timer_callback)

    def timer_callback(self):
        ret, frame = self.cap.read()
        if ret:
            msg = CompressedImage()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.header.frame_id = "camera_frame"
            msg.format = "jpeg" 

            success, encoded_img = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 50])
            
            if success:
                msg.data = encoded_img.tobytes()
                self.pub.publish(msg)

    def __del__(self):
        if self.cap.isOpened():
            self.cap.release()

def main(args=None):
    rclpy.init(args=args)
    node = MJPEGCameraPublisher()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()