import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy

import configparser
import os

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
        
        if os.path.exists(ini_path):
            config = configparser.ConfigParser()
            config.read(ini_path)
            frequency = config["publisher"].getint("frequency", frequency)

        self.timer = self.create_timer(1.0 / frequency, self.timer_callback)

        self.latest_msg = None
        self.last_msg_time = 0
        
        # Таймаут в секундах. Если сообщений нет дольше этого времени, перестаем слать в маврос.
        # Так как камера работает на ~30Гц, ставим запас (например, 0.5 сек)
        self.timeout_duration = 0.5 

    def listener_callback(self, msg):
        """Сохраняем последнее полученное сообщение и время прихода"""
        self.latest_msg = msg
        self.last_msg_time = self.get_clock().now().nanoseconds

    def timer_callback(self):
        """Работает на частоте 50 Гц"""
        if self.latest_msg is None:
            return

        # Проверка времени: сколько прошло с последнего сообщения от edu
        now = self.get_clock().now().nanoseconds
        elapsed = (now - self.last_msg_time) / 1e9 # перевод наносекунд в секунды

        if elapsed > self.timeout_duration:
            self.get_logger().warn("Source topic is silent, stopping MAVROS stream", throttle_duration_sec=5)
            return

        msg_to_send = self.latest_msg
        msg_to_send.header.stamp = self.get_clock().now().to_msg()
        
        # Публикуем
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