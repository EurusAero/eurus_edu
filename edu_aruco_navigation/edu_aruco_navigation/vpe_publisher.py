import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy

import configparser
import os
import math
import numpy as np
from collections import deque

from geometry_msgs.msg import PoseWithCovarianceStamped

class VpePublisher(Node):
    def __init__(self):
        super().__init__('vpe_publisher_node')

        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )

        # Подписка на ваш топик
        self.subscription = self.create_subscription(
            PoseWithCovarianceStamped,
            '/edu/vision_pose_cov',
            self.listener_callback,
            qos_profile
        )

        # Паблишер в MAVROS
        self.publisher = self.create_publisher(
            PoseWithCovarianceStamped,
            '/mavros/vision_pose/pose_cov',
            qos_profile
        )

        home_dir = os.getenv("HOME")
        ini_path = f"{home_dir}/ros2_ws/src/eurus_edu/edu_aruco_navigation/eurus.ini"

        frequency = 50
        self.history_size = 10
        self.timeout_duration = 0.5 
        
        if os.path.exists(ini_path):
            config = configparser.ConfigParser()
            config.read(ini_path)
            frequency = config["publisher"].getint("frequency", frequency)
            self.history_size = config["publisher"].getint("history_size", self.history_size)
            self.timeout_duration = config["publisher"].getfloat("timeout_duration", self.timeout_duration) 

        self.pose_history = deque(maxlen=self.history_size)

        self.timer = self.create_timer(1.0 / frequency, self.timer_callback)

        self.last_msg_time = 0

    def listener_callback(self, msg):
        """Сохраняем сообщение в историю и обновляем время"""
        self.pose_history.append(msg)
        self.last_msg_time = self.get_clock().now().nanoseconds

    def get_averaged_pose(self):
        """Вычисляет среднее значение на основе накопленной истории"""
        n = len(self.pose_history)
        if n == 0:
            return None
        
        sum_x = 0.0
        sum_y = 0.0
        sum_z = 0.0
        
        sum_qx = 0.0
        sum_qy = 0.0
        sum_qz = 0.0
        sum_qw = 0.0
        
        sum_cov = np.zeros(36)

        for msg in self.pose_history:
            p = msg.pose.pose.position
            q = msg.pose.pose.orientation
            
            sum_x += p.x
            sum_y += p.y
            sum_z += p.z
            
            sum_qx += q.x
            sum_qy += q.y
            sum_qz += q.z
            sum_qw += q.w
            
            sum_cov += np.array(msg.pose.covariance)

        avg_msg = PoseWithCovarianceStamped()
        
        avg_msg.header.frame_id = self.pose_history[-1].header.frame_id
        
        avg_msg.pose.pose.position.x = sum_x / n
        avg_msg.pose.pose.position.y = sum_y / n
        avg_msg.pose.pose.position.z = sum_z / n

        avg_qx = sum_qx / n
        avg_qy = sum_qy / n
        avg_qz = sum_qz / n
        avg_qw = sum_qw / n
        
        norm = math.sqrt(avg_qx**2 + avg_qy**2 + avg_qz**2 + avg_qw**2)
        
        if norm > 1e-6:
            avg_msg.pose.pose.orientation.x = avg_qx / norm
            avg_msg.pose.pose.orientation.y = avg_qy / norm
            avg_msg.pose.pose.orientation.z = avg_qz / norm
            avg_msg.pose.pose.orientation.w = avg_qw / norm
        else:
            avg_msg.pose.pose.orientation = self.pose_history[-1].pose.pose.orientation

        avg_msg.pose.covariance = (sum_cov / n).tolist()
        
        return avg_msg

    def timer_callback(self):
        if not self.pose_history:
            return

        now_ns = self.get_clock().now().nanoseconds
        elapsed = (now_ns - self.last_msg_time) / 1e9 

        if elapsed > self.timeout_duration:
            self.get_logger().warn("Source topic is silent, stopping MAVROS stream", throttle_duration_sec=5)
            self.pose_history.clear() 
            return

        msg_to_send = self.get_averaged_pose()
        
        if msg_to_send:
            msg_to_send.header.stamp = self.get_clock().now().to_msg()
            self.publisher.publish(msg_to_send)

def main(args=None):
    rclpy.init(args=args)
    node = VpePublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()