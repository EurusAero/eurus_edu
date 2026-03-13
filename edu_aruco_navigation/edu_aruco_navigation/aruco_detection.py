import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
import json
import cv2
import numpy as np
import configparser
import os
import math
import time
import csv
import threading
import queue
from transforms3d.euler import euler2quat

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
        self.dictionary_name = "4X4_250"
        camera_topic = "/edu/camera_frame"
        self.aruco_map_path = ""
        self.camera_config_path = ""
        self.aruco_debug = False
        
        self.map_origin = "BR"
        self.camera_yaw_offset_deg = 0

        if os.path.exists(ini_path):
            config = configparser.ConfigParser()
            config.read(ini_path)

            self.dictionary_name = config["aruco"].get("dictionary", self.dictionary_name)
            self.aruco_map_path = config["aruco"].get("map_path", "")
            self.map_origin = config["aruco"].get("map_origin", "BR")

            camera_topic = config["settings"].get("camera_topic", camera_topic)
            self.camera_config_path = config["settings"].get("camera_config_path", "")
            self.camera_yaw_offset_deg = config["settings"].getint("camera_direction", 0)
            self.aruco_debug = config["settings"].getboolean("aruco_debug", False)

        self.create_subscription(CompressedImage, camera_topic, self.camera_sub, camera_qos)
        self.create_subscription(String, "/edu/aruco_map_nav", self.map_navigation_sub, reliable_qos)

        self.aruco_nav_pub = self.create_publisher(String, "/edu/aruco_map_nav", reliable_qos)
        self.aruco_debug_pub = self.create_publisher(CompressedImage, "/edu/aruco_debug", camera_qos)
        self.vpe_publisher = self.create_publisher(PoseStamped, "/mavros/vision_pose/pose", reliable_qos)
        self.vpe_cov_publisher = self.create_publisher(PoseWithCovarianceStamped, "/mavros/vision_pose/pose_cov", reliable_qos)

        self.vpe_cov = PoseWithCovarianceStamped()
        self.vpe_pose = PoseStamped()
        self.navigation_state = False
        self.map_in_vision = False
        self.fly_in_borders = False
        self.payload = {
            "timestamp": time.time(),
            "aruco_nav_status": self.navigation_state,
            "map_in_vision": self.map_in_vision,
            "fly_in_borders": self.fly_in_borders,
        }
        
        self.board = None
        self.map_width_m = 0.0
        self.map_height_m = 0.0
        self.camera_matrix = None
        self.dist_coeffs = None

        if self.dictionary_name not in self.aruco_dicts:
             self.dictionary_name = "4X4_250"

        self.aruco_dict_obj = cv2.aruco.getPredefinedDictionary(self.aruco_dicts[self.dictionary_name])
        parameters = cv2.aruco.DetectorParameters()
        self.aruco_detector = cv2.aruco.ArucoDetector(self.aruco_dict_obj, parameters)

        if self.aruco_map_path:
            self.parse_map_file()

        if self.camera_config_path:
            self.load_camera_config()
        else:
            self.get_logger().warn("Camera config path not set in eurus.ini!")

        if self.aruco_debug:
            self.debug_queue = queue.Queue(maxsize=2)
            self.debug_thread = threading.Thread(target=self.debug_worker, daemon=True)
            self.debug_thread.start()

    def parse_map_file(self):
        try:
            self.get_logger().info(f"Loading map from {self.aruco_map_path}")
            
            obj_points = []
            ids_list = []
            
            min_x, min_y = float('inf'), float('inf')
            max_x, max_y = float('-inf'), float('-inf')

            with open(self.aruco_map_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter=';')
                
                for row in reader:
                    m_id = int(row['id'])
                    m_len = float(row['length'])
                    x = float(row['x'])
                    y = float(row['y'])
                    z = float(row['z'])
                    
                    half_l = m_len / 2.0
                    
                    c1 = [x - half_l, y + half_l, z]  # Top-Left
                    c2 = [x + half_l, y + half_l, z]  # Top-Right
                    c3 = [x + half_l, y - half_l, z]  # Bottom-Right
                    c4 = [x - half_l, y - half_l, z]  # Bottom-Left
                    
                    obj_points.append(np.array([c1, c2, c3, c4], dtype=np.float32))
                    ids_list.append(m_id)
                    
                    min_x = min(min_x, x - half_l)
                    max_x = max(max_x, x + half_l)
                    min_y = min(min_y, y - half_l)
                    max_y = max(max_y, y + half_l)

            if not ids_list:
                self.get_logger().error("Map file is empty or invalid.")
                return

            ids_np = np.array(ids_list, dtype=np.int32)

            self.map_width_m = max_x - min_x if max_x > min_x else 0.0
            self.map_height_m = max_y - min_y if max_y > min_y else 0.0

            self.payload["map_width"] = self.map_width_m
            self.payload["map_height"] = self.map_height_m

            self.board = cv2.aruco.Board(
                np.array(obj_points, dtype=np.float32),
                self.aruco_dict_obj,
                ids_np
            )
            
            self.get_logger().info(f"Custom Board loaded: {len(ids_list)} markers. Origin set to: {self.map_origin}")

        except Exception as e:
            self.get_logger().error(f"Failed to parse map csv: {e}")
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
        if self.navigation_state or self.aruco_debug:
            np_arr = np.frombuffer(msg.data, np.uint8)
            timestamp = msg.header.stamp
            image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            
            self.process_frame(image, timestamp)

    def map_navigation_sub(self, msg):
        json_msg = json.loads(msg.data)
        timestamp = json_msg.get("timestamp")
        self.navigation_state = json_msg.get("aruco_nav_status")
        self.map_in_vision = json_msg.get("map_in_vision")
        self.fly_in_borders = json_msg.get("fly_in_borders")
        self.payload["timestamp"] = timestamp
        self.payload["aruco_nav_status"] = self.navigation_state
        self.payload["map_in_vision"] = self.map_in_vision
        self.payload["fly_in_borders"] = self.fly_in_borders

    def process_frame(self, image, timestamp):
    
        corners, ids = self.detect_aruco(image)
        rvec, tvec = None, None

        if (self.board is not None and
            self.camera_matrix is not None and
            ids is not None):
            
            rvec, tvec = self.calculate_drone_pose(corners, ids, timestamp)

        if self.aruco_debug_pub.get_subscription_count() > 0 and self.aruco_debug:
            try:
                self.debug_queue.put_nowait((image, corners, ids, rvec, tvec, timestamp))
            except queue.Full:
                pass

    def debug_worker(self):
        while rclpy.ok():
            try:
                item = self.debug_queue.get(timeout=1.0)
                image, corners, ids, rvec, tvec, timestamp = item

                if ids is not None:
                    cv2.aruco.drawDetectedMarkers(image, corners, ids)

                if rvec is not None and tvec is not None and self.camera_matrix is not None:
                    cv2.drawFrameAxes(image, self.camera_matrix, self.dist_coeffs, rvec, tvec, 0.1)

                debug_msg = CompressedImage()
                debug_msg.header.stamp = timestamp
                debug_msg.header.frame_id = "aruco"
                debug_msg.format = "jpeg"
                
                encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 80]
                success, encoded_image = cv2.imencode(".jpg", image, encode_param)
                
                if success:
                    debug_msg.data = encoded_image.tobytes()
                    self.aruco_debug_pub.publish(debug_msg)
                    
            except queue.Empty:
                continue
            except Exception as e:
                self.get_logger().error(f"Debug worker error: {e}")

    def detect_aruco(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = self.aruco_detector.detectMarkers(gray)
        return corners, ids

    def calculate_drone_pose(self, corners, ids, timestamp):
        obj_points, img_points = self.board.matchImagePoints(corners, ids)
        msg = String()

        if obj_points is None or len(obj_points) == 0:
            if self.map_in_vision:
                self.map_in_vision = False
                self.payload["timestamp"] = time.time()
                self.payload["map_in_vision"] = self.map_in_vision
                msg.data = json.dumps(self.payload)
                self.aruco_nav_pub.publish(msg)

            return None, None

        retval, rvec, tvec = cv2.solvePnP(obj_points, img_points, self.camera_matrix, self.dist_coeffs)

        if retval and self.navigation_state:
            R, _ = cv2.Rodrigues(rvec)
            R_inv = R.T
            t_inv = -np.dot(R_inv, tvec)

            # X вправо, Y вверх
            raw_x = t_inv[0][0]
            raw_y = t_inv[1][0]
            raw_z = t_inv[2][0]

            forward_x = -R_inv[0, 1]
            forward_y = -R_inv[1, 1]

            base_yaw = math.atan2(forward_y, forward_x)

            offset_rad = math.radians(self.camera_yaw_offset_deg)
            final_yaw = base_yaw + offset_rad

            final_yaw = (final_yaw + math.pi) % (2 * math.pi) - math.pi

            self.vpe_pose.header.stamp = timestamp
            self.vpe_pose.header.frame_id = "map"

            self.vpe_pose.pose.position.x = raw_x
            self.vpe_pose.pose.position.y = raw_y
            self.vpe_pose.pose.position.z = raw_z
        
            qw, qx, qy, qz = euler2quat(0, 0, final_yaw)
            self.vpe_pose.pose.orientation.x = qx
            self.vpe_pose.pose.orientation.y = qy
            self.vpe_pose.pose.orientation.z = qz
            self.vpe_pose.pose.orientation.w = qw

            self.vpe_cov.header = self.vpe_pose.header
            self.vpe_cov.pose.pose = self.vpe_pose.pose

            covariance = [0.0] * 36
            covariance[0] = 1e-9  # X
            covariance[7] = 1e-9  # Y
            covariance[14] = 0.1  # Z
            covariance[21] = 0.1  # Roll
            covariance[28] = 0.1  # Pitch
            covariance[35] = 1e-9 # Yaw
            self.vpe_cov.pose.covariance = covariance

            # self.vpe_publisher.publish(self.vpe_pose)
            self.vpe_cov_publisher.publish(self.vpe_cov)

            if not self.map_in_vision:
                self.map_in_vision = True
                self.payload["timestamp"] = time.time()
                self.payload["map_in_vision"] = self.map_in_vision
                msg.data = json.dumps(self.payload)
                self.aruco_nav_pub.publish(msg)

            return rvec, tvec
        elif retval:
            return rvec, tvec
            
        return None, None
    
def main(args=None):
    rclpy.init()
    node = ArucoDetector()
    rclpy.spin(node)