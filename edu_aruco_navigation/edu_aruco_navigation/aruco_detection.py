import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
import json
import cv2
import numpy as np
import configparser
import os
import math
from transforms3d.euler import euler2quat, quat2euler


from std_msgs.msg import String
from sensor_msgs.msg import CompressedImage
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped

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

        # QoS
        camera_qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST, depth=1)
        reliable_qos = QoSProfile(reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST, depth=10)
        
        # Чтение конфига
        home_dir = os.getenv("HOME")
        ini_path = f"{home_dir}/ros2_ws/src/eurus_edu/edu_aruco_navigation/eurus.ini"
        
        # Дефолтные настройки
        self.dictionary_name = "4X4_50"
        camera_topic = "/edu/camera_frame"
        frequency = 30
        self.aruco_map_path = ""
        self.camera_config_path = ""
        
        self.map_origin = "BR"
        self.camera_yaw_offset_deg = 0

        if os.path.exists(ini_path):
            config = configparser.ConfigParser()
            config.read(ini_path)
            
            self.dictionary_name = config["aruco"].get("dict", self.dictionary_name)
            self.aruco_map_path = config["aruco"].get("map_path", "")
            self.map_origin = config["aruco"].get("map_origin", "BR")
            
            frequency = config["settings"].getint("frequency", frequency)
            camera_topic = config["settings"].get("camera_topic", camera_topic)
            self.camera_config_path = config["settings"].get("camera_config_path", "")
            self.camera_yaw_offset_deg = config["settings"].getint("camera_direction", 0)

        self.create_subscription(CompressedImage, camera_topic, self.camera_sub, camera_qos)
        self.create_subscription(String, "/edu/aruco_map_nav", self.map_navigation_sub, reliable_qos)
        
        self.aruco_nav_pub = self.create_publisher(String, "/edu/aruco_map_nav", reliable_qos)
        self.aruco_debug_pub = self.create_publisher(CompressedImage, "/edu/aruco_debug", camera_qos)
        self.vpe_publisher = self.create_publisher(PoseStamped, "/mavros/vision_pose/pose", reliable_qos)
        self.vpe_cov_publisher = self.create_publisher(PoseWithCovarianceStamped, "/mavros/vision_pose/pose_cov", reliable_qos)

        self.vpe_cov = PoseWithCovarianceStamped()
        self.vpe_pose = PoseStamped()
        self.debug_msg = CompressedImage()
        self.navigation_state = False
        self.map_in_vision = False
        self.last_frame = None
        self.board = None 
        
        self.map_width_m = 0.0
        self.map_height_m = 0.0
        
        self.camera_matrix = None
        self.dist_coeffs = None

        # Инициализация Aruco
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
        Парсит .txt файл и рассчитывает физические размеры доски.
        """
        try:
            self.get_logger().info(f"Loading map from {self.aruco_map_path}")
            with open(self.aruco_map_path, 'r') as f:
                lines = f.readlines()
                
            if len(lines) < 2:
                self.get_logger().error("Map file too short.")
                return

            params = lines[0].strip().split()
            markers_x = int(params[0])
            markers_y = int(params[1])
            marker_len = float(params[2])
            marker_sep = float(params[3])

            ids_str = lines[1].strip().split()
            ids_list = [int(x) for x in ids_str]
            ids_np = np.array(ids_list, dtype=np.int32)
            
            # Сохраняем размеры карты для расчетов Origin
            # Ширина = кол-во маркеров * длину + промежутки
            self.map_width_m = markers_x * marker_len + (markers_x - 1) * marker_sep
            self.map_height_m = markers_y * marker_len + (markers_y - 1) * marker_sep

            self.board = cv2.aruco.GridBoard(
                (markers_x, markers_y), 
                marker_len, 
                marker_sep, 
                self.aruco_dict_obj, 
                ids_np
            )
            self.get_logger().info(f"GridBoard loaded: {markers_x}x{markers_y}. Origin set to: {self.map_origin}")

        except Exception as e:
            self.get_logger().error(f"Failed to parse map txt: {e}")
            self.board = None

    def load_camera_config(self):
        try:
            if not os.path.exists(self.camera_config_path):
                self.get_logger().error(f"Camera config file not found: {self.camera_config_path}")
                return

            with open(self.camera_config_path, 'r') as f:
                data = json.load(f)
            
            self.camera_matrix = np.array(data["camera_matrix"], dtype=np.float64)
            self.dist_coeffs = np.array(data["dist_coeffs"], dtype=np.float64)
            self.get_logger().info(f"Camera parameters loaded. Mount offset: {self.camera_yaw_offset_deg} deg")
            
        except Exception as e:
            self.get_logger().error(f"Failed to load camera config: {e}")

    def camera_sub(self, msg):
        np_arr = np.frombuffer(msg.data, np.uint8)
        self.last_frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    
    def map_navigation_sub(self, msg):
        json_msg = json.loads(msg.data)
        self.navigation_state = json_msg.get("aruco_nav_status")
        self.map_in_vision = json_msg.get("map_in_vision")

    def aruco_handler(self):
        if self.last_frame is None:
            return
        
        image = self.last_frame.copy()
        corners, ids = self.detect_aruco(image)
        
        if (self.board is not None and 
            self.camera_matrix is not None and 
            ids is not None):
            
            rvec, tvec = self.calculate_drone_pose(corners, ids)
            
            if rvec is not None and tvec is not None:
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

    def calculate_drone_pose(self, corners, ids):
        obj_points, img_points = self.board.matchImagePoints(corners, ids)
        if obj_points is None or len(obj_points) == 0:
            if self.map_in_vision:
                self.map_in_vision = False
                payload = {
                        "aruco_nav_status": self.navigation_state,
                        "map_in_vision": self.map_in_vision
                }
                msg = String()
                msg.data = json.dumps(payload)
                self.aruco_nav_pub.publish(msg)
                
            return None, None
        
        retval, rvec, tvec = cv2.solvePnP(obj_points, img_points, self.camera_matrix, self.dist_coeffs)
        
        if retval:
            if self.navigation_state:
                R, _ = cv2.Rodrigues(rvec)
                R_inv = R.T
                t_inv = -np.dot(R_inv, tvec)
                
                # Координаты в системе координат доски
                # Ось X - вправо, Y - вниз (по изображению доски), Z - вверх (от доски)
                raw_x = t_inv[0][0]
                raw_y = t_inv[1][0]
                raw_z = t_inv[2][0]

                # вращение вокруг Z
                yaw_cam = math.atan2(R_inv[1, 0], R_inv[0, 0])

                # Обработка смещения начала координат (Map Origin)
                drone_x, drone_y = raw_x, raw_y

                if self.map_origin == "TR": # Top-Right (Правый Верхний)
                    drone_x = self.map_width_m - raw_x
                    drone_y = raw_y
                elif self.map_origin == "BL": # Bottom-Left (Левый Нижний)
                    drone_x = raw_x
                    drone_y = self.map_height_m - raw_y
                elif self.map_origin == "BR": # Bottom-Right (Правый Нижний)
                    drone_x = self.map_width_m - raw_x
                    drone_y = self.map_height_m - raw_y
                # Если TL, оставляем как есть

                # Переводим градусы из конфига в радианы
                offset_rad = math.radians(self.camera_yaw_offset_deg)
                
                # Итоговый Yaw дрона = Yaw камеры + Смещение установки
                drone_yaw = yaw_cam + offset_rad
                
                # Нормализация угла в диапазон [-pi, pi]
                drone_yaw = (drone_yaw + math.pi) % (2 * math.pi) - math.pi
                
                self.vpe_pose.header.stamp = self.get_clock().now().to_msg()
                self.vpe_pose.header.frame_id = "map"
                
                self.vpe_pose.pose.position.x = drone_x
                self.vpe_pose.pose.position.y = drone_y
                self.vpe_pose.pose.position.z = raw_z
                
                qw, qx, qy, qz = euler2quat(0, 0, drone_yaw)
                self.vpe_pose.pose.orientation.x = qx
                self.vpe_pose.pose.orientation.y = qy
                self.vpe_pose.pose.orientation.z = qz
                self.vpe_pose.pose.orientation.w = qw
                
                self.vpe_cov.header = self.vpe_pose.header
                self.vpe_cov.pose.pose = self.vpe_pose.pose
                
                covariance = [0.0] * 36
                
                covariance[0] = 0.01  # X
                covariance[7] = 0.01  # Y
                covariance[14] = 0.1 # Z 
                covariance[21] = 0.1  # Roll
                covariance[28] = 0.1  # Pitch
                covariance[35] = 0.01 # Yaw
                
                self.vpe_cov.pose.covariance = covariance
                
                # self.vpe_publisher.publish(self.vpe_pose)
                self.vpe_cov_publisher.publish(self.vpe_cov)
            
            if not self.map_in_vision:
                self.map_in_vision = True
                payload = {
                    "aruco_nav_status": self.navigation_state,
                    "map_in_vision": self.map_in_vision
                }
                msg = String()
                msg.data = json.dumps(payload)
                self.aruco_nav_pub.publish(msg)
                
            return rvec, tvec
        
        if self.map_in_vision:
            self.map_in_vision = False
            payload = {
                    "aruco_nav_status": self.navigation_state,
                    "map_in_vision": self.map_in_vision
            }
            msg = String()
            msg.data = json.dumps(payload)
            self.aruco_nav_pub.publish(msg)
            
        return None, None

def main(args=None):
    rclpy.init()
    node = ArucoDetector()
    rclpy.spin(node)