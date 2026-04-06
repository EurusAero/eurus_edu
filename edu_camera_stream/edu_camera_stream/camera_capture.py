import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
import cv2
import os
import configparser
from sensor_msgs.msg import CompressedImage 
import time
import threading

class CameraStreamThread(threading.Thread):
    def __init__(self, node, camera_name, config_section):
        super().__init__()
        self.node = node
        self.camera_name = camera_name
        self.is_running = True
        
        self.width = config_section.getint("width", 640)
        self.height = config_section.getint("height", 480)
        self.fps = config_section.getint("fps", 30)
        
        # Определение устройства (число для /dev/video0 или строка для /dev/imx...)
        dev_str = config_section.get("device", "0")
        self.device = int(dev_str) if dev_str.isdigit() else dev_str
        
        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=1
        )
        
        topic_name = f'/edu/{self.camera_name}'
        self.pub = self.node.create_publisher(CompressedImage, topic_name, qos_profile)
        
        self.cap = None
        self.node.get_logger().info(f"[{self.camera_name}] Инициализация потока для устройства {self.device}")

    def setup_camera(self):
        if self.cap is not None:
            self.cap.release()
            
        self.cap = cv2.VideoCapture(self.device)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)
        
        if self.cap.isOpened():
            self.node.get_logger().info(f"[{self.camera_name}] Камера успешно открыта")
        else:
            self.node.get_logger().warn(f"[{self.camera_name}] Не удалось открыть камеру")

    def run(self):
        self.setup_camera()
        
        while rclpy.ok() and self.is_running:
            if self.cap is None or not self.cap.isOpened():
                self.node.get_logger().debug(f"[{self.camera_name}]. Попытка переподключения...")
                self.setup_camera()
                time.sleep(0.5)
                continue

            ret, frame = self.cap.read()
            if ret:
                msg = CompressedImage()
                msg.header.stamp = self.node.get_clock().now().to_msg()
                msg.header.frame_id = f"{self.camera_name}_frame"
                msg.format = "jpeg" 

                success, encoded_img = cv2.imencode('.jpg', frame)
                if success:
                    msg.data = encoded_img.tobytes()
                    self.pub.publish(msg)
            else:
                self.node.get_logger().warn(f"[{self.camera_name}] Потерян кадр. Переподключение...")
                self.cap.release()
                time.sleep(0.5)

    def stop(self):
        self.is_running = False
        if self.cap is not None and self.cap.isOpened():
            self.cap.release()


class MultiCameraPublisher(Node):
    def __init__(self):
        super().__init__('camera_capture')
        
        config = configparser.ConfigParser()
        home_dir = os.getenv("HOME")
        config_path = f"{home_dir}/ros2_ws/src/eurus_edu/edu_camera_stream/eurus.ini" 
        
        self.camera_threads = []
        
        if os.path.exists(config_path):
            self.get_logger().info(f"Загрузка конфига из {config_path}")
            config.read(config_path)
            
            for section in config.sections():
                if config.has_option(section, "enable") and config.getboolean(section, "enable"):
                    if config.has_option(section, "device"):
                        cam_thread = CameraStreamThread(self, section, config[section])
                        self.camera_threads.append(cam_thread)
                        cam_thread.start()
        else:
            self.get_logger().error(f"Файл конфигурации не найден: {config_path}")
        
        self.get_logger().info("Camera publisher нода создана")

    def stop_all(self):
        self.get_logger().info("Остановка всех потоков камер...")
        for thread in self.camera_threads:
            thread.stop()
            thread.join()
        self.get_logger().info("Все камеры остановлены.")

def main():
    rclpy.init()
    node = MultiCameraPublisher()
    
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("Получен сигнал прерывания (Ctrl+C)")
    finally:
        node.stop_all()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()