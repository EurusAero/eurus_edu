import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String

import configparser
import cv2
import numpy as np
import json
import os
from ultralytics import YOLO


class YoloDetectorNode(Node):
    def __init__(self):
        super().__init__('yolo_detector')
        
        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=1
        )

        self.pub = self.create_publisher(String, '/edu/targets', 10)
        
        config = configparser.ConfigParser()
        home_dir = os.getenv("HOME")
        config_path = f"{home_dir}/ros2_ws/src/eurus_edu/edu_neuro_detection/eurus.ini" 
        camera_topic = "/edu/forward_camera"
        self.conf_threshold = 0.5
        
        if os.path.exists(config_path):
            config.read(config_path)
            if "neuro" in config:
                model_path = config["neuro"].get("model_path")
                self.conf_threshold = config["neuro"].getfloat("conf_threshold", 0.5)
                camera_topic = config["neuro"].get("camera_topic", "/edu/forward_camera")
            else:
                self.get_logger().warn(f"Конфигурация для ноды не обнаружена в {config_path}.")
        else:
            self.get_logger().warn(f"Файл конфигурации не обнаружен по адресу {config_path}.")

        self.get_logger().info(f"Загрузка модели YOLO из {model_path}...")
        
        self.sub = self.create_subscription(
            CompressedImage,
            camera_topic,
            self.image_callback,
            qos_profile
        )
        
        try:
            self.model = YOLO(model_path)
            self.class_keys = {
                name: name.replace(" ", "_")
                for name in self.model.names.values()
            }
            self.get_logger().info(
                f"Модель успешно загружена. Классы: {list(self.class_keys.keys())}"
            )
        except Exception as e:
            self.get_logger().error(f"Ошибка загрузки модели: {e}")

        self.get_logger().info("YoloDetector нода создана.")

    def image_callback(self, msg: CompressedImage):
        try:
            np_arr = np.frombuffer(msg.data, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

            if frame is None:
                self.get_logger().debug("Кадр не получен.")
                return

            results = self.model(frame, verbose=False, conf=self.conf_threshold)

            response = {"command": "targets_response", "all_objects": []}
            for key in self.class_keys.values():
                response[key] = []

            result = results[0]

            for box in result.boxes:
                xywh = box.xywh.cpu().numpy()[0]
                x, y, w, h = xywh

                conf = float(box.conf.cpu().numpy()[0])
                cls_id = int(box.cls.cpu().numpy()[0])

                class_name = self.model.names[cls_id]

                target_data = {
                    "x": round(float(x), 2),
                    "y": round(float(y), 2),
                    "w": round(float(w), 2),
                    "h": round(float(h), 2),
                    "conf": round(conf, 2),
                    "class": class_name
                }

                response["all_objects"].append(target_data)

                key = self.class_keys.get(class_name)
                if key is not None:
                    response[key].append(target_data)
                
            json_str = json.dumps(response)
            
            msg_out = String()
            msg_out.data = json_str
            self.pub.publish(msg_out)

        except Exception as e:
            self.get_logger().error(f"Ошибка в цикле детекции: {e}")

def main():
    rclpy.init()
    node = YoloDetectorNode()
    
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()