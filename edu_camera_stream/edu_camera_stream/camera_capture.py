import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
import os
import configparser
from sensor_msgs.msg import CompressedImage
import time
import threading

import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstApp', '1.0')
# GstApp импортируется ради побочного эффекта: без загрузки его typelib
# appsink приезжает как голый Gst.Element, без pull_sample/try_pull_sample
from gi.repository import Gst, GstApp  # noqa: F401

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
        self.device = f"/dev/video{dev_str}" if dev_str.isdigit() else dev_str

        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=1
        )

        topic_name = f'/edu/{self.camera_name}'
        self.pub = self.node.create_publisher(CompressedImage, topic_name, qos_profile)

        self.pipeline = None
        self.appsink = None
        self.node.get_logger().info(f"[{self.camera_name}] Инициализация потока для устройства {self.device}")

    def setup_camera(self):
        self.release()

        # Камера уже отдаёт MJPEG, поэтому JPEG уходит в топик как есть,
        # без decode/encode. max-buffers=1 drop=true - всегда самый свежий
        # кадр, очередь не копится и не даёт задержки.
        pipeline_str = (
            f"v4l2src device={self.device} io-mode=2 ! "
            f"image/jpeg,width={self.width},height={self.height},framerate={self.fps}/1 ! "
            f"appsink name=sink max-buffers=1 drop=true sync=false"
        )

        try:
            self.pipeline = Gst.parse_launch(pipeline_str)
        except Exception as e:
            self.node.get_logger().warn(f"[{self.camera_name}] Не удалось собрать пайплайн: {e}")
            self.pipeline = None
            return

        self.appsink = self.pipeline.get_by_name("sink")

        if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            self.node.get_logger().warn(f"[{self.camera_name}] Не удалось открыть камеру")
            self.release()
            return

        self.node.get_logger().info(f"[{self.camera_name}] Камера успешно открыта")

    def release(self):
        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.NULL)
        self.pipeline = None
        self.appsink = None

    def run(self):
        self.setup_camera()

        while rclpy.ok() and self.is_running:
            if self.pipeline is None:
                self.node.get_logger().debug(f"[{self.camera_name}]. Попытка переподключения...")
                self.setup_camera()
                time.sleep(0.5)
                continue

            # Камеру выдернули или пайплайн упал
            bus_msg = self.pipeline.get_bus().timed_pop_filtered(
                0, Gst.MessageType.ERROR | Gst.MessageType.EOS)
            if bus_msg is not None:
                self.node.get_logger().warn(f"[{self.camera_name}] Потерян кадр. Переподключение...")
                self.release()
                time.sleep(0.5)
                continue

            # С таймаутом, иначе залипнем навсегда на мёртвой камере
            sample = self.appsink.try_pull_sample(Gst.SECOND)
            if sample is None:
                continue

            buf = sample.get_buffer()
            ok, mapinfo = buf.map(Gst.MapFlags.READ)
            if not ok:
                continue

            try:
                msg = CompressedImage()
                msg.header.stamp = self.node.get_clock().now().to_msg()
                msg.header.frame_id = f"{self.camera_name}_frame"
                msg.format = "jpeg"
                msg.data = bytes(mapinfo.data)
                self.pub.publish(msg)
            finally:
                buf.unmap(mapinfo)

    def stop(self):
        self.is_running = False


class MultiCameraPublisher(Node):
    def __init__(self):
        super().__init__('camera_capture')

        Gst.init(None)

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
            thread.join(timeout=3.0)
            thread.release()
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
