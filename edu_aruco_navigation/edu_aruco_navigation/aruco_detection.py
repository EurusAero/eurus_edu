import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
import json
import cv2
import numpy as np
import configparser
import os

from std_msgs.msg import Bool
from sensor_msgs.msg import CompressedImage

class ArucoDetector(Node):
    def __init__(self):
        super().__init__('aruco_detection')

        self.aruco_dicts = {
            "4X4_50": cv2.aruco.DICT_4X4_50,
            "4X4_100": cv2.aruco.DICT_4X4_100,
            "4X4_250": cv2.aruco.DICT_4X4_250,
            "4X4_1000": cv2.aruco.DICT_4X4_1000,
            "5X5_50": cv2.aruco.DICT_5X5_50,
            "5X5_100": cv2.aruco.DICT_5X5_100,
            "5X5_250": cv2.aruco.DICT_5X5_250,
            "5X5_1000": cv2.aruco.DICT_5X5_1000
        }

        camera_qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST, depth=1)
        reliable_qos = QoSProfile(reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST, depth=10)
        
        home_dir = os.getenv("HOME")
        ini_path = f"{home_dir}/ros2_ws/src/eurus_edu/edu_aruco_navigation/eurus.ini"
        
        self.dictionary_name = "4X4_50"
        camera_topic = "/edu/camera_frame"
        frequency = 30
        self.aruco_map_path = ""
        self.camera_config_path = ""

        if os.path.exists(ini_path):
            config = configparser.ConfigParser()
            config.read(ini_path)
            
            self.dictionary_name = config["aruco"].get("dict", self.dictionary_name)
            frequency = config["settings"].getint("frequency", frequency)
            camera_topic = config["settings"].get("camera_topic", camera_topic)
            self.aruco_map_path = config["aruco"].get("map_path", "")
            self.camera_config_path = config["settings"].get("camera_config_path", "")

        self.create_subscription(CompressedImage, camera_topic, self.camera_sub, camera_qos)
        # self.create_subscription(Bool, "/edu/aruco_map_nav", self.map_navigation_sub, reliable_qos)
        
        self.aruco_debug_pub = self.create_publisher(CompressedImage, "/edu/aruco_debug", camera_qos)

        self.debug_msg = CompressedImage()
        self.navigation_state = True
        self.last_frame = None
        self.board = None 
        
        self.camera_matrix = None
        self.dist_coeffs = None

        if self.dictionary_name not in self.aruco_dicts:
             self.dictionary_name = "4X4_50"
             
        self.aruco_dict_obj = cv2.aruco.getPredefinedDictionary(self.aruco_dicts[self.dictionary_name])
        parameters = cv2.aruco.DetectorParameters()
        self.aruco_detector = cv2.aruco.ArucoDetector(self.aruco_dict_obj, parameters)

        if self.aruco_map_path:
            self.parse_map_file()
            
        if self.camera_config_path:
            self.load_camera_config()
        else:
            self.get_logger().warn("Camera config path not set in eurus.ini!")

        timer_period = 1 / frequency
        self.timer = self.create_timer(timer_period, self.aruco_handler)

    def parse_map_file(self):
        """
        Парсит .txt файл.
        Line 1: markers_x markers_y marker_length marker_separation
        Line 2: id1 id2 id3 ...
        """
        try:
            self.get_logger().info(f"Loading map from {self.aruco_map_path}")
            with open(self.aruco_map_path, 'r') as f:
                lines = f.readlines()
                
            if len(lines) < 2:
                self.get_logger().error("Map file too short. Needs 2 lines.")
                return

            params = lines[0].strip().split()
            if len(params) != 4:
                self.get_logger().error("Line 1 must have 4 values: x y len sep")
                return
                
            markers_x = int(params[0])
            markers_y = int(params[1])
            marker_len = float(params[2])
            marker_sep = float(params[3])

            ids_str = lines[1].strip().split()
            ids_list = [int(x) for x in ids_str]
            ids_np = np.array(ids_list, dtype=np.int32)

            expected_count = markers_x * markers_y
            if len(ids_list) != expected_count:
                self.get_logger().warn(f"Warning: Expected {expected_count} IDs, found {len(ids_list)}")

            self.board = cv2.aruco.GridBoard(
                (markers_x, markers_y), 
                marker_len, 
                marker_sep, 
                self.aruco_dict_obj, 
                ids_np
            )
            self.get_logger().info(f"GridBoard loaded: {markers_x}x{markers_y}")

        except Exception as e:
            self.get_logger().error(f"Failed to parse map txt: {e}")
            self.board = None

    def load_camera_config(self):
        """
        Загружает матрицу камеры и дисторсию из JSON.
        """
        try:
            if not os.path.exists(self.camera_config_path):
                self.get_logger().error(f"Camera config file not found: {self.camera_config_path}")
                return

            with open(self.camera_config_path, 'r') as f:
                data = json.load(f)
            
            self.camera_matrix = np.array(data["camera_matrix"], dtype=np.float64)
            self.dist_coeffs = np.array(data["dist_coeffs"], dtype=np.float64)
            self.get_logger().info("Camera parameters loaded successfully.")
            
        except Exception as e:
            self.get_logger().error(f"Failed to load camera config: {e}")

    def camera_sub(self, msg):
        np_arr = np.frombuffer(msg.data, np.uint8)
        self.last_frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    
    def map_navigation_sub(self, msg):
        self.navigation_state = msg.data
    
    def aruco_handler(self):
        if self.last_frame is None:
            return
        
        image = self.last_frame.copy()
        corners, ids = self.detect_aruco(image)
        
        # Если включена навигация, есть карта и камера откалибрована
        if (self.navigation_state and 
            self.board is not None and 
            self.camera_matrix is not None and 
            ids is not None):
            
            rvec, tvec = self.calculate_drone_pose(corners, ids, image)
            
            # Если поза найдена, можно рисовать ось координат
            if rvec is not None and tvec is not None:
                # Отрисовка оси координат на маркере (длина оси 0.1м)
                cv2.drawFrameAxes(image, self.camera_matrix, self.dist_coeffs, rvec, tvec, 0.1)

        if ids is not None:
            cv2.aruco.drawDetectedMarkers(image, corners, ids)
        
        self.debug_msg.header.stamp = self.get_clock().now().to_msg()
        self.debug_msg.header.frame_id = "aruco"
        self.debug_msg.format = "jpeg"
        success, encoded_image = cv2.imencode(".jpg", image)
        if success:
            self.debug_msg.data = encoded_image.tobytes()
            self.aruco_debug_pub.publish(self.debug_msg)

    def detect_aruco(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = self.aruco_detector.detectMarkers(gray)
        return corners, ids

    def calculate_drone_pose(self, corners, ids, image):
        """
        Считает положение дрона относительно карты.
        Возвращает rvec, tvec (векторы доски относительно камеры) для визуализации.
        Публикует PoseStamped (позиция камеры относительно доски).
        """
        
        # 1. Сопоставляем найденные углы с углами на доске
        # obj_points: 3D координаты углов на доске
        # img_points: 2D координаты углов на изображении
        obj_points, img_points = self.board.matchImagePoints(corners, ids)

        if len(obj_points) == 0:
            return None, None

        # 2. Solve PnP: находим положение доски относительно камеры
        # rvec, tvec описывают трансформацию ОТ мира (доски) К камере
        retval, rvec, tvec = cv2.solvePnP(obj_points, img_points, self.camera_matrix, self.dist_coeffs)
        
        if retval:
            # 3. Инвертируем трансформацию, чтобы получить положение Камеры (Дрона) в координатах Доски
            # T_board_cam = [R|t]
            # T_cam_board = [R^T | -R^T * t]
            
            R, _ = cv2.Rodrigues(rvec) # Преобразуем вектор вращения в матрицу 3x3
            R_inv = R.T
            t_inv = -np.dot(R_inv, tvec)
            
            # Позиция дрона (x, y, z) в метрах относительно начала координат доски
            drone_x = t_inv[0][0]
            drone_y = t_inv[1][0]
            drone_z = t_inv[2][0]
            
            return rvec, tvec
            
        return None, None

def main(args=None):
    rclpy.init()
    node = ArucoDetector()
    rclpy.spin(node)