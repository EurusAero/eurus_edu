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
import base64

from std_srvs.srv import Trigger
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

        camera_qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST, depth=1)
        reliable_qos = QoSProfile(reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST, depth=10)

        home_dir = os.getenv("HOME")
        ini_path = f"{home_dir}/ros2_ws/src/eurus_edu/edu_aruco_navigation/eurus.ini"

        self.dictionary_name = "4X4_250"
        camera_topic = "/edu/camera_frame"
        self.aruco_map_path = ""
        self.camera_config_path = ""
        self.aruco_debug = False

        self.camera_yaw_offset_deg = 0

        self.min_marker_size_ratio = 0.7


        if os.path.exists(ini_path):
            try:
                config = configparser.ConfigParser()
                config.read(ini_path)

                self.dictionary_name = config["aruco"].get("dictionary", self.dictionary_name)
                self.aruco_map_path = config["aruco"].get("map_path", "")

                camera_topic = config["settings"].get("camera_topic", camera_topic)
                self.camera_config_path = config["settings"].get("camera_config_path", "")
                self.camera_yaw_offset_deg = config["settings"].getint("camera_direction", 0)
                self.aruco_debug = config["settings"].getboolean("aruco_debug", False)
                self.min_marker_size_ratio = config["settings"].getfloat("min_marker_size_ratio", self.min_marker_size_ratio)
            except Exception as e:
                self.get_logger().error(f"При чтении конфига - {ini_path} произошла ошибка: {e}")
        else:
            self.get_logger().warn(f"Не найден файл конфигурации по пути: {ini_path}")

        self.create_subscription(CompressedImage, camera_topic, self.camera_sub, camera_qos)
        self.create_subscription(String, "/edu/aruco_map_nav", self.map_navigation_sub, reliable_qos)

        self.create_service(Trigger, "/edu/get_aruco_board_snapshot", self.aruco_board_snapshot_callback)

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
        else:
            self.get_logger().warn("Конфигурация для аруко карты не найдена.")

        if self.camera_config_path:
            self.load_camera_config()
        else:
            self.get_logger().warn("Конфигурация камеры не установлена в eurus.ini!")

        # Обработка кадров вынесена в отдельный поток, чтобы тяжёлые CV-вычисления
        # не блокировали исполнитель ROS (rclpy.spin). Очередь на 1 кадр: всегда
        # берём самый свежий, старые отбрасываем. Так узел не "зависает" под
        # нагрузкой, а все вызовы OpenCV выполняются строго из одного потока
        # (конкурентный вызов cv2 из разных потоков может привести к deadlock).
        self.frame_queue = queue.Queue(maxsize=1)

        self.processing_thread = threading.Thread(target=self.processing_worker, daemon=True)
        self.processing_thread.start()

        if self.aruco_debug:
            self.get_logger().debug("Установлен режим отладки")
        self.get_logger().info("Aruco detector нода создана")
        

    def parse_map_file(self):
        try:
            self.get_logger().info(f"Загрузка карты из {self.aruco_map_path}")

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
                self.get_logger().warn("Файл карты пустой или в неправильном формате.")
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

            self.get_logger().info(f"Пользовательское поле загружено. Количество маркеров: {len(ids_list)}.")

        except Exception as e:
            self.get_logger().error(f"Ошибка при чтении csv карты: {e}")
            self.board = None

    def load_camera_config(self):
        try:
            if not os.path.exists(self.camera_config_path):
                self.get_logger().error(f"Файл конфигурации камеры не найден по пути: {self.camera_config_path}")
                return

            with open(self.camera_config_path, 'r') as f:
                data = json.load(f)

            self.camera_matrix = np.array(data["camera_matrix"], dtype=np.float64)
            self.dist_coeffs = np.array(data["dist_coeffs"], dtype=np.float64)
            self.get_logger().info(f"Параметры камеры загружены. Смещение места установки: {self.camera_yaw_offset_deg} deg")

        except Exception as e:
            self.get_logger().error(f"Ошибка при загрузке конфигурации камеры: {e}")

    def camera_sub(self, msg):
        # Callback исполнителя ROS: никакой тяжёлой работы, только передаём
        # самый свежий кадр в рабочий поток. Если очередь занята - выбрасываем
        # устаревший кадр и кладём новый, чтобы не накапливать задержку.
        if not (self.navigation_state or self.aruco_debug):
            return

        item = (msg.data, msg.header.stamp)
        try:
            self.frame_queue.put_nowait(item)
        except queue.Full:
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.frame_queue.put_nowait(item)
            except queue.Full:
                pass

    def processing_worker(self):
        # Единственный поток, выполняющий декодирование и все CV-вычисления.
        while rclpy.ok():
            try:
                data, timestamp = self.frame_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            try:
                np_arr = np.frombuffer(data, np.uint8)
                image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if image is None:
                    continue

                self.process_frame(image, timestamp)
            except Exception as e:
                self.get_logger().error(f"Ошибка при обработке кадра: {e}")


    def aruco_board_snapshot_callback(self, request, response):
        if self.board is None or self.map_width_m <= 0:
            self.get_logger().error("Аруко поле не инициализировано или размер карты = 0.")
            response.success = False
            response.message = "Аруко поле не инициализировано или размер карты = 0."
            return response

        try:
            pixels_per_meter = 1000
            margin_px = 50

            min_x, min_y = float('inf'), float('inf')
            max_x, max_y = float('-inf'), float('-inf')
            markers_data = []

            with open(self.aruco_map_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter=';')
                for row in reader:
                    m_id = int(row['id'])
                    m_len = float(row['length'])
                    x = float(row['x'])
                    y = float(row['y'])
                    markers_data.append({'id': m_id, 'len': m_len, 'x': x, 'y': y})

                    half_l = m_len / 2.0
                    min_x = min(min_x, x - half_l)
                    max_x = max(max_x, x + half_l)
                    min_y = min(min_y, y - half_l)
                    max_y = max(max_y, y + half_l)

            map_width_m = max_x - min_x
            map_height_m = max_y - min_y

            width_px = int(map_width_m * pixels_per_meter) + margin_px * 2
            height_px = int(map_height_m * pixels_per_meter) + margin_px * 2

            if width_px > 10000 or height_px > 10000:
                scale_factor = 10000.0 / max(width_px, height_px)
                pixels_per_meter = int(pixels_per_meter * scale_factor)
                width_px = int(map_width_m * pixels_per_meter) + margin_px * 2
                height_px = int(map_height_m * pixels_per_meter) + margin_px * 2

            self.get_logger().info(f"Ручная отрисовка карты. Разрешение: {width_px}x{height_px} px")

            image = np.full((height_px, width_px, 1), 255, dtype=np.uint8)

            for mk in markers_data:
                m_id = mk['id']
                m_len = mk['len']
                x = mk['x']
                y = mk['y']

                size_px = int(m_len * pixels_per_meter)
                if size_px < 10:
                    self.get_logger().warn(f"Маркер {m_id} слишком мал для отрисовки ({size_px} px), пропускаем.")
                    continue

                marker_img = cv2.aruco.generateImageMarker(self.aruco_dict_obj, m_id, size_px, borderBits=1)

                x_tl_px = int((x - m_len / 2.0 - min_x) * pixels_per_meter) + margin_px
                y_tl_px = int((max_y - (y + m_len / 2.0)) * pixels_per_meter) + margin_px

                y1, y2 = y_tl_px, y_tl_px + size_px
                x1, x2 = x_tl_px, x_tl_px + size_px

                if 0 <= y1 < height_px and 0 <= x1 < width_px:
                    image[y1:y2, x1:x2, 0] = marker_img

            success_enc, jpg_buffer = cv2.imencode(".jpg", image)
            if not success_enc:
                self.get_logger().error("Не удалось сжать изображение в JPEG.")
                response.success = False
                response.message = "Не удалось сжать изображение в JPEG."
                return response

            response.success = True
            response.message = base64.b64encode(jpg_buffer.tobytes()).decode('utf-8')
            return response

        except Exception as e:
            self.get_logger().error(f"Критическая ошибка при генерации карты: {e}")
            response.success = False
            response.message = str(e)
            return response


    def map_navigation_sub(self, msg):
        try:
            json_msg = json.loads(msg.data)
            timestamp = json_msg.get("timestamp")
            self.navigation_state = json_msg.get("aruco_nav_status")
            self.map_in_vision = json_msg.get("map_in_vision")
            self.fly_in_borders = json_msg.get("fly_in_borders")
            self.payload["timestamp"] = timestamp
            self.payload["aruco_nav_status"] = self.navigation_state
            self.payload["map_in_vision"] = self.map_in_vision
            self.payload["fly_in_borders"] = self.fly_in_borders
        except Exception as e:
            self.get_logger().error(f"Ошибка при получении данных из /edu/aruco_map_nav : {e}")


    def process_frame(self, image, timestamp):
        try:
            corners, ids = self.detect_aruco(image)
            rvec, tvec = None, None
            msg = String()

            if (self.board is not None and
                self.camera_matrix is not None and
                ids is not None):
                rvec, tvec = self.calculate_drone_pose(corners, ids, timestamp)


            elif self.map_in_vision:
                self.map_in_vision = False
                self.payload["timestamp"] = time.time()
                self.payload["map_in_vision"] = self.map_in_vision
                msg.data = json.dumps(self.payload)
                self.aruco_nav_pub.publish(msg)

            if self.aruco_debug and self.aruco_debug_pub.get_subscription_count() > 0:
                self.publish_debug_frame(image, corners, ids, rvec, tvec, timestamp)

        except Exception as e:
            self.get_logger().error(f"Ошибка при обработке кадра: {e}")

    def detect_aruco(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = self.aruco_detector.detectMarkers(gray)
        corners, ids = self.filter_small_markers(corners, ids)
        return corners, ids

    def draw_axes_safe(self, image, rvec, tvec, length=0.1):
        # Безопасная замена cv2.drawFrameAxes.
        # При позе от одиночного/неоднозначного маркера проекция осей может
        # уходить в NaN/Inf или гигантские координаты, и внутренний cv2.line
        # намертво зависает при растеризации такой линии. Поэтому сначала
        # проецируем точки сами, проверяем их, и только потом рисуем.
        h, w = image.shape[:2]
        axis_points = np.float32([
            [0, 0, 0],
            [length, 0, 0],
            [0, length, 0],
            [0, 0, length],
        ]).reshape(-1, 3)

        try:
            img_pts, _ = cv2.projectPoints(axis_points, rvec, tvec, self.camera_matrix, self.dist_coeffs)
        except Exception as e:
            self.get_logger().debug(f"draw_axes_safe: projectPoints не удался ({e}), оси не рисуем")
            return

        img_pts = img_pts.reshape(-1, 2)

        if not np.all(np.isfinite(img_pts)):
            self.get_logger().debug("draw_axes_safe: не-конечные координаты (NaN/Inf), оси не рисуем")
            return

        # Ограничение на разумный диапазон пикселей: если проекция вылетела
        # далеко за пределы кадра - поза мусорная, рисовать нельзя (иначе cv2.line зависнет).
        limit = 5 * max(w, h)
        if np.any(np.abs(img_pts) > limit):
            self.get_logger().debug("draw_axes_safe: координаты вне допустимого диапазона, оси не рисуем")
            return

        origin = tuple(np.int32(img_pts[0]))
        x_tip = tuple(np.int32(img_pts[1]))
        y_tip = tuple(np.int32(img_pts[2]))
        z_tip = tuple(np.int32(img_pts[3]))

        cv2.line(image, origin, x_tip, (0, 0, 255), 2)  # X - красный
        cv2.line(image, origin, y_tip, (0, 255, 0), 2)  # Y - зелёный
        cv2.line(image, origin, z_tip, (255, 0, 0), 2)  # Z - синий

    def publish_debug_frame(self, image, corners, ids, rvec, tvec, timestamp):
        # Вызывается из processing_worker - тот же поток, что и детекция,
        # поэтому все вызовы OpenCV сериализованы и безопасны.
        try:
            if ids is not None:
                cv2.aruco.drawDetectedMarkers(image, corners, ids)

            if rvec is not None and tvec is not None and self.camera_matrix is not None:
                self.draw_axes_safe(image, rvec, tvec, 0.1)

            debug_msg = CompressedImage()
            debug_msg.header.stamp = timestamp
            debug_msg.header.frame_id = "aruco"
            debug_msg.format = "jpeg"

            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 80]
            success, encoded_image = cv2.imencode(".jpg", image, encode_param)

            if success:
                debug_msg.data = encoded_image.tobytes()
                self.aruco_debug_pub.publish(debug_msg)

        except Exception as e:
            self.get_logger().error(f"Ошибка в режиме отладки: {e}")

    def filter_small_markers(self, corners, ids):
        """
        Защита от случайных ArUco маркеров.

        За эталон берётся самый большой маркер в кадре. Все маркеры, чей
        линейный размер меньше self.min_marker_size_ratio от самого большого,
        отбрасываются. При min_marker_size_ratio <= 0 фильтр отключён.
        """
        if (ids is None or len(corners) <= 1 or self.min_marker_size_ratio <= 0):
            return corners, ids

        # Линейный размер маркера как корень из площади четырёхугольника,
        # чтобы порог отношения был в тех же единицах, что и стороны маркера.
        sizes = [math.sqrt(abs(cv2.contourArea(c.reshape(-1, 2).astype(np.float32)))) for c in corners]
        max_size = max(sizes)
        if max_size <= 0:
            return corners, ids

        threshold = max_size * self.min_marker_size_ratio

        filtered_corners = []
        filtered_ids = []
        for corner, marker_id, size in zip(corners, ids, sizes):
            if size >= threshold:
                filtered_corners.append(corner)
                filtered_ids.append(marker_id)

        if not filtered_ids:
            return corners, ids

        return tuple(filtered_corners), np.array(filtered_ids, dtype=ids.dtype)

    def calculate_drone_pose(self, corners, ids, timestamp):
        try:
            obj_points, img_points = self.board.matchImagePoints(corners, ids)
            msg = String()

            if obj_points is None or len(obj_points) == 0:
                if self.map_in_vision:
                    self.map_in_vision = False
                    self.payload["timestamp"] = time.time()
                    self.payload["map_in_vision"] = self.map_in_vision
                    msg.data = json.dumps(self.payload)
                    self.aruco_nav_pub.publish(msg)
                else:
                    self.get_logger().debug("Аруко карта не видна")

                return None, None
            else:
                self.get_logger().debug("Не обнаружено аруко маркеров")


            retval, rvec, tvec = cv2.solvePnP(obj_points, img_points, self.camera_matrix, self.dist_coeffs)
        except Exception as e:
            self.get_logger().error(f"Ошибка при расчете позиции по аруко маркерам: {e}")
            return None, None


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