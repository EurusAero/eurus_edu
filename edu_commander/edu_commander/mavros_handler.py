import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
from rclpy.time import Time
import json
import threading
import time
import configparser
import os
from math import dist, radians, cos, sin
import csv

from transforms3d.euler import euler2quat, quat2euler
from mavros_msgs.srv import CommandBool, CommandTOL, SetMode
from mavros_msgs.msg import PositionTarget, State
from geometry_msgs.msg import PoseStamped
from std_msgs.msg import String, Bool
from edu_msgs.msg import Command
from EurusEdu.const import *


class MavrosHandler(Node):
    def __init__(self):
        super().__init__("edu_commander")
        
        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )

        self.arming_client = self.create_client(CommandBool, '/mavros/cmd/arming')
        self.set_mode_client = self.create_client(SetMode, '/mavros/set_mode')
        self.takeoff_client = self.create_client(CommandTOL, '/mavros/cmd/takeoff')
        self.land_client = self.create_client(CommandTOL, '/mavros/cmd/land')

        self.local_pos_pub = self.create_publisher(PoseStamped, '/mavros/setpoint_position/local', qos_profile)
        self.raw_velocity_pub = self.create_publisher(PositionTarget, "/mavros/setpoint_raw/local", qos_profile)
        self.point_reached_pub = self.create_publisher(Bool, "/edu/point_reached", qos_profile)
        
        self.local_pose = PoseStamped()
        self.home_position = PoseStamped()

        self._wait_for_services()

        mavros_qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )
        
        self.create_subscription(
            Command,
            'edu/command',
            self.command_callback,
            10
        )
        self.create_subscription(
            PoseStamped,
            "/mavros/local_position/pose",
            self.local_pos_updater,
            mavros_qos_profile
        )
        self.create_subscription(
            State,
            "/mavros/state",
            self.state_updater,
            mavros_qos_profile
        )
        
        self.create_subscription(
            String,
            "/edu/aruco_map_nav",
            self.aruco_nav_updater,
            mavros_qos_profile
        )

        self.status_pub = self.create_publisher(Command, 'edu/command', 10)
        
        home_dir = os.getenv("HOME")
        ini_path = f"{home_dir}/ros2_ws/src/eurus_edu/edu_aruco_navigation/eurus.ini"
        handler_ini_path = f"{home_dir}/ros2_ws/src/eurus_edu/edu_commander/eurus.ini"
        
        self.aruco_map_path = ""
        self.map_height_max = float("-inf")
        self.map_width_max = float("-inf")
        
        self.map_height_min = float("inf")
        self.map_width_min = float("inf")
        self.aruco_map = {}
        if os.path.exists(ini_path):
            config = configparser.ConfigParser()
            config.read(ini_path)
            self.aruco_map_path = config["aruco"].get("map_path", "")
        else:
            self.get_logger().warn(f"Конфиг не найден по адресу: {ini_path}")
        
        if self.aruco_map_path and os.path.exists(self.aruco_map_path):
            with open(self.aruco_map_path, "r") as f:
                markers_info = csv.DictReader(f, delimiter=";")
                for row in markers_info:
                    self.aruco_map[row["id"]] = {
                        "x": float(row["x"]),
                        "y": float(row["y"]),
                        "z": float(row["z"])
                    }
                    self.map_width_max = max(self.map_width_max, float(row["x"]))
                    self.map_height_max = max(self.map_height_max, float(row["y"]))
                    
                    self.map_width_min = min(self.map_width_min, float(row["x"]))
                    self.map_height_min = min(self.map_height_min, float(row["y"]))
        else:
            self.get_logger().warn(f"Аруко карта не создана.")    

        self.Kp = 1.5
        self.max_corr = 1.0
        self.aruco_border_indent = 0.3
        self.point_reached_diff = 0.2
        if os.path.exists(handler_ini_path):
            config = configparser.ConfigParser()
            config.read(handler_ini_path)
            self.Kp = config.getfloat("velocity", "aruco_borders_kp")
            self.max_corr = config.getfloat("velocity", "aruco_borders_correlation_speed")
            self.aruco_border_indent = config.getfloat("velocity", "aruco_border_indent")
            
            self.point_reached_diff = config.getfloat("local_position", "point_reached_diff")
        
        self.setpoint_pose = PoseStamped()
        self.start_position = PoseStamped()
        self.target_pose = PoseStamped()
        self.setpoint_raw = PositionTarget()
        self.target_raw = PositionTarget()
        self.state_msg = State()
        self.point_reached = Bool()
        
        self.aruco_nav_status = {
            "aruco_nav_status": False,
            "map_in_vision": False,
            "timestamp": 0.0,
            "fly_in_borders": False
        }
        
        self.prev_map_in_vision = False
        self.aruco_active_prev = False
        self.hold_zero_velocity = False
        self.frame_alignment_counter = 0
        self.ALIGNMENT_DURATION = 20

        self.timer = self.create_timer(0.02, self.cmd_loop)

        self.only_arm = True
        self.current_task_thread = None
        self.current_control_method = "LOCAL_POSITION"
        self.setpoint_speed = 1.0
        self.get_logger().info("MavrosHandler нода создана.")

    def cmd_loop(self):
        is_map_visible = self.aruco_nav_status.get("map_in_vision", False)
        aruco_active = self.aruco_nav_status.get("aruco_nav_status", False)

        if aruco_active and is_map_visible and not self.prev_map_in_vision:
            self.get_logger().info("Аруко карта обнаружена, синхронизирую координаты")
            self.frame_alignment_counter = self.ALIGNMENT_DURATION
        
        if not aruco_active and self.aruco_active_prev:
            self.frame_alignment_counter = self.ALIGNMENT_DURATION
            self.set_home_position(save_altitude=True)
        
        self.aruco_active_prev = aruco_active
        self.prev_map_in_vision = is_map_visible

        if self.current_control_method == "LOCAL_POSITION":
            self.setpoint_pose.header.stamp = self.get_clock().now().to_msg()
            self.setpoint_pose.header.frame_id = "map"
                    

            if self.only_arm:
                self.sync_target_to_local()
                self.setpoint_pose.pose.position.z = self.local_pose.pose.position.z - 2
            
            elif self.frame_alignment_counter > 0:
                self.sync_target_to_local()
                self.frame_alignment_counter -= 1
            
            else:
                self.calculate_next_target_position()
            
            
            self.point_reached.data = self.get_distance(self.local_pose, self.target_pose) < self.point_reached_diff
            self.point_reached_pub.publish(self.point_reached)
            self.local_pos_pub.publish(self.setpoint_pose)

        elif self.current_control_method == "RAW_VELOCITY":
            self.setpoint_raw.header.frame_id = "map"
            self.setpoint_raw.coordinate_frame = 1
            
            self.calculate_next_target_velocity()
            
            self.raw_velocity_pub.publish(self.setpoint_raw)
        

    def sync_target_to_local(self):
        """
        Приравнивает целевую точку (Target и Setpoint) к текущей позиции дрона.
        Используется для сброса "хвостов" управления при смене координат.
        """
        # Копируем позицию
        self.setpoint_pose.pose.position.x = self.local_pose.pose.position.x
        self.setpoint_pose.pose.position.y = self.local_pose.pose.position.y
        self.setpoint_pose.pose.position.z = self.local_pose.pose.position.z
        
        # Копируем ориентацию
        self.setpoint_pose.pose.orientation.x = self.local_pose.pose.orientation.x
        self.setpoint_pose.pose.orientation.y = self.local_pose.pose.orientation.y
        self.setpoint_pose.pose.orientation.z = self.local_pose.pose.orientation.z
        self.setpoint_pose.pose.orientation.w = self.local_pose.pose.orientation.w

        # То же самое для target_pose
        self.target_pose.pose.position.x = self.local_pose.pose.position.x
        self.target_pose.pose.position.y = self.local_pose.pose.position.y
        self.target_pose.pose.position.z = self.local_pose.pose.position.z
        
        self.target_pose.pose.orientation.x = self.local_pose.pose.orientation.x
        self.target_pose.pose.orientation.y = self.local_pose.pose.orientation.y
        self.target_pose.pose.orientation.z = self.local_pose.pose.orientation.z
        self.target_pose.pose.orientation.w = self.local_pose.pose.orientation.w

        # И для start_position
        self.start_position.pose.position.x = self.local_pose.pose.position.x
        self.start_position.pose.position.y = self.local_pose.pose.position.y
        self.start_position.pose.position.z = self.local_pose.pose.position.z
        
        self.start_position.pose.orientation.x = self.local_pose.pose.orientation.x
        self.start_position.pose.orientation.y = self.local_pose.pose.orientation.y
        self.start_position.pose.orientation.z = self.local_pose.pose.orientation.z
        self.start_position.pose.orientation.w = self.local_pose.pose.orientation.w
        
        self.start_position.header.stamp = self.get_clock().now().to_msg()

    def _wait_for_services(self):
        self.get_logger().info("Ожидание сервисов MAVROS...")
        if not self.arming_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().warn("Сервис arming не найден!")
        if not self.set_mode_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().warn("Сервис set_mode не найден!")
        if not self.takeoff_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().warn("Сервис takeoff не найден!")
        self.get_logger().info("Сервисы MAVROS найдены (или таймаут).")

    def publish_status(self, original_msg, status, message=""):
        reply = Command()
        reply.timestamp = original_msg.timestamp
        reply.command = original_msg.command
        reply.status = status
        reply.data = message
        self.status_pub.publish(reply)
        self.get_logger().info(f"Статус '{original_msg.command}': {status} | {message}")

    def local_pos_updater(self, msg: PoseStamped):
        self.local_pose = msg

    def state_updater(self, msg: State):
        self.state_msg = msg
    
    def aruco_nav_updater(self, msg: String):
        try:
            self.aruco_nav_status = json.loads(msg.data)
        except json.JSONDecodeError:
            pass

    def get_distance(self, start, end):
        start_p = [float(start.pose.position.x), float(start.pose.position.y), float(start.pose.position.z)]
        end_p = [float(end.pose.position.x), float(end.pose.position.y), float(end.pose.position.z)]
        return dist(start_p, end_p)
    
    def calculate_next_target_position(self):
        hold_pos = False
        if not self.state_msg.armed:
            self.start_position.header.stamp = self.get_clock().now().to_msg()
        
        aruco_active = self.aruco_nav_status.get("aruco_nav_status", False)
        map_visible = self.aruco_nav_status.get("map_in_vision", False)
        last_seen_ts = self.aruco_nav_status.get("timestamp", 0)
    
        if aruco_active and not map_visible and (time.time() - last_seen_ts) > 0.5:
            self.start_position.header.stamp = self.get_clock().now().to_msg()
            self.start_position.pose.position.x = self.setpoint_pose.pose.position.x
            self.start_position.pose.position.y = self.setpoint_pose.pose.position.y
            self.start_position.pose.position.z = self.setpoint_pose.pose.position.z
            hold_pos = True
            
        stamp = self.start_position.header.stamp
        total_dist = self.get_distance(self.start_position, self.target_pose)
        
        flight_duration = total_dist / self.setpoint_speed if self.setpoint_speed > 0 else 0

        now_time = self.get_clock().now()
        start_time = Time.from_msg(stamp) 
        elapsed_seconds = (now_time - start_time).nanoseconds / 1e9

        if flight_duration > 0 and not hold_pos:
            passed = min((elapsed_seconds / flight_duration), 1.0)
            
            self.setpoint_pose.pose.position.x = self.start_position.pose.position.x + (self.target_pose.pose.position.x - self.start_position.pose.position.x) * passed
            self.setpoint_pose.pose.position.y = self.start_position.pose.position.y + (self.target_pose.pose.position.y - self.start_position.pose.position.y) * passed
            self.setpoint_pose.pose.position.z = self.start_position.pose.position.z + (self.target_pose.pose.position.z - self.start_position.pose.position.z) * passed
        
        # elif not hold_pos:
        #      self.setpoint_pose.pose = self.target_pose.pose

        return self.setpoint_pose
    
    def calculate_next_target_velocity(self):
        aruco_active = self.aruco_nav_status.get("aruco_nav_status", False)
        map_visible = self.aruco_nav_status.get("map_in_vision", False)
        fly_in_borders = self.aruco_nav_status.get("fly_in_borders", False)
        last_seen_ts = self.aruco_nav_status.get("timestamp", 0)
    
        body_vx = self.target_raw.velocity.x
        body_vy = self.target_raw.velocity.y
        
        q = self.local_pose.pose.orientation
        _, _, yaw = quat2euler([q.w, q.x, q.y, q.z])
        
        local_vx = body_vx * cos(yaw) - body_vy * sin(yaw)
        local_vy = body_vx * sin(yaw) + body_vy * cos(yaw)
    
        if aruco_active:
            if not map_visible and (time.time() - last_seen_ts) > 0.5 and not self.hold_zero_velocity:
                local_vx = 0.0
                local_vy = 0.0
                self.set_zero_velocity()
                self.hold_zero_velocity = True
                                        
            elif fly_in_borders and not self.hold_zero_velocity:
                local_x = self.local_pose.pose.position.x
                local_y = self.local_pose.pose.position.y
                
                if local_vx > 0 and local_x > self.map_width_max - self.aruco_border_indent: 
                    local_vx = 0.0
                
                if local_x > self.map_width_max:
                    corr_vx = -self.Kp * (local_x - self.map_width_max)
                    local_vx += max(-self.max_corr, corr_vx) 
                    self.set_zero_velocity(pos_x=self.map_width_max)
                    
                if local_vx < 0 and local_x < self.map_width_min + self.aruco_border_indent: 
                    local_vx = 0.0    
                
                elif local_x < self.map_width_min:
                    corr_vx = self.Kp * (self.map_width_min - local_x)
                    local_vx += min(self.max_corr, corr_vx)
                    self.set_zero_velocity(pos_x=self.map_width_min)

                if local_vy > 0 and local_y > self.map_height_max - self.aruco_border_indent: 
                    local_vy = 0.0
                
                if local_y > self.map_height_max:
                    corr_vy = -self.Kp * (local_y - self.map_height_max)
                    local_vy += max(-self.max_corr, corr_vy)
                    self.set_zero_velocity(pos_y=self.map_height_max)
                    
                if local_vy < 0 and local_y < self.map_height_min + self.aruco_border_indent: 
                    local_vy = 0.0     
                
                elif local_y < self.map_height_min:
                    corr_vy = self.Kp * (self.map_height_min - local_y)
                    local_vy += min(self.max_corr, corr_vy)
                    self.set_zero_velocity(pos_y=self.map_height_min)

                if map_visible and self.hold_zero_velocity:
                    self.hold_zero_velocity = False
        
        self.setpoint_raw.header.stamp = self.get_clock().now().to_msg()
        self.setpoint_raw.type_mask = self.target_raw.type_mask
        self.setpoint_raw.position.x = self.target_raw.position.x
        self.setpoint_raw.position.y = self.target_raw.position.y
        self.setpoint_raw.position.z = self.target_raw.position.z
        
        self.setpoint_raw.velocity.x = local_vx
        self.setpoint_raw.velocity.y = local_vy
        self.setpoint_raw.velocity.z = self.target_raw.velocity.z
        self.setpoint_raw.yaw_rate = self.target_raw.yaw_rate
        
        return self.setpoint_raw
    
    def set_zero_velocity(self, pos_x=None, pos_y=None):
        self.target_raw.type_mask = 2040
        self.target_raw.velocity.x = 0.0
        self.target_raw.velocity.y = 0.0
        # self.target_raw.yaw_rate = 0.0
        
        if pos_x is None:
            self.target_raw.position.x = self.local_pose.pose.position.x
        else:
            self.target_raw.position.x = pos_x
        
        if pos_y is None:
            self.target_raw.position.y = self.local_pose.pose.position.y
        else:
            self.target_raw.position.y = pos_y
            
        if self.target_raw.velocity.z != 0:
            self.target_raw.velocity.z = 0.0
            self.target_raw.position.z = self.local_pose.pose.position.z
    
    def command_callback(self, msg: Command):
        if msg.status != PENDING_STATUS:
            return

        if self.current_task_thread and self.current_task_thread.is_alive():
            self.publish_status(msg, DENIED_STATUS, "Mavros handler is busy")
            return

        self.current_task_thread = threading.Thread(
            target=self.execute_command_logic,
            args=(msg,),
            daemon=True
        )
        self.current_task_thread.start()

    def execute_command_logic(self, msg: Command):
        self.publish_status(msg, RUNNING_STATUS)
        cmd_name = msg.command
        data = {}
        try:
            if msg.data:
                data = json.loads(msg.data)
        except json.JSONDecodeError:
            self.publish_status(msg, DENIED_STATUS, "Invalid JSON data")
            return

        success = False
        error_msg = ""

        try:
            if cmd_name in ["arm", "disarm"]:
                self.only_arm = True
            else:
                self.only_arm = False
                
            if cmd_name == "arm":
                success, error_msg = self.do_arm()
            elif cmd_name == "disarm":
                success, error_msg = self.do_disarm()
            elif cmd_name == "takeoff":
                success, error_msg = self.do_takeoff(data)
            elif cmd_name == "land":
                success, error_msg = self.do_land()
            elif cmd_name == "move_to_local_point":
                success, error_msg = self.do_move_to_local_point(data)
            elif cmd_name == "set_mode": 
                mode = data.get("mode", "OFFBOARD")
                success, error_msg = self.do_set_mode(mode)
            elif cmd_name == "move_in_body_frame":
                success, error_msg = self.do_move_in_body_frame(data)
            elif cmd_name == "set_velocity":
                success, error_msg = self.do_set_velocity(data)
            elif cmd_name == "move_to_marker":
                success, error_msg = self.do_move_to_marker(data)
            else:
                success = False
                error_msg = f"Unknown command: {cmd_name}"
        except Exception as e:
            success = False
            error_msg = str(e)
            self.get_logger().error(f"Ошибка при обработке команды: {e}")

        final_status = COMPLETED_STATUS if success else DENIED_STATUS
        self.publish_status(msg, final_status, error_msg)


    def _call_service_sync(self, client, request):
        future = client.call_async(request)
        while not future.done():
            time.sleep(0.04)
        return future.result()
    
    def set_home_position(self, save_altitude=False):
        if save_altitude:
            self.home_position.pose.position.x = self.local_pose.pose.position.x
            self.home_position.pose.position.y = self.local_pose.pose.position.y
            self.home_position.pose.orientation = self.local_pose.pose.orientation
        else:
            self.home_position.pose = self.local_pose.pose
        self.get_logger().info(f"home position установлена в: x: {self.home_position.pose.position.x}, y: {self.home_position.pose.positon.y}, orientation: {self.home_position.pose.orientation}")

    def do_set_mode(self, mode="OFFBOARD"):
        req = SetMode.Request()
        req.custom_mode = mode
        res = self._call_service_sync(self.set_mode_client, req)
        if res.mode_sent:
            self.get_logger().debug(f"Отправлена команда установки режима {mode}")
            return True, "Mode sent"
        self.get_logger().warn(f"Не удалось отправить команду установки режима {mode}: {res.result}")
        return False, f"Mode sent failed: {res.result}"

    def do_arm(self):
        self.current_control_method = "LOCAL_POSITION"
        self.do_set_mode("OFFBOARD")
        time.sleep(0.5)
        self.set_home_position()
        req = CommandBool.Request()
        req.value = True
        res = self._call_service_sync(self.arming_client, req)
        if res.success:
            return True, "Armed"
        return False, f"Arming failed: {res.result}"

    def do_disarm(self):
        req = CommandBool.Request()
        req.value = False
        res = self._call_service_sync(self.arming_client, req)
        if res.success:
            return True, "Disarmed"
        return False, f"Disarming failed"

    def do_takeoff(self, data):
        self.do_set_mode("OFFBOARD")
        self.do_arm()
        
        altitude = data.get("altitude", 1.0)
        self.setpoint_speed = data.get("speed", 1)
        
        self.get_logger().info(f"Взлёт на высоту {altitude}m")
        
        self.start_position.header = self.local_pose.header
        self.start_position.pose = self.local_pose.pose
        
        self.target_pose.pose.position.x = self.local_pose.pose.position.x
        self.target_pose.pose.position.y = self.local_pose.pose.position.y
        self.target_pose.pose.position.z = altitude
        self.setpoint_pose.pose.orientation.x = self.home_position.pose.orientation.x
        self.setpoint_pose.pose.orientation.y = self.home_position.pose.orientation.y
        self.setpoint_pose.pose.orientation.z = self.home_position.pose.orientation.z
        self.setpoint_pose.pose.orientation.w = self.home_position.pose.orientation.w

        self.start_position.header.stamp = self.get_clock().now().to_msg()
        
        self.frame_alignment_counter = 0
        self.current_control_method = "LOCAL_POSITION"
        
        return True, "Takeoff initiated"

    def do_land(self):
        req = CommandTOL.Request()
        res = self._call_service_sync(self.land_client, req)
        if res.success:
            return True, "Landing (Service)"
        return False, "Landing failed"

    def do_set_velocity(self, data):
        try:
            vx = data.get("vx", self.target_raw.velocity.x)
            vy = data.get("vy", self.target_raw.velocity.y)
            vz = data.get("vz", self.target_raw.velocity.z)
            yaw_rate = data.get("yaw_rate", None)
            self.target_raw.type_mask = 1984
            
            
            if vx or vy:
                self.target_raw.type_mask += 1
                self.target_raw.position.x = 0.0
                self.target_raw.velocity.x = vx
                
                self.target_raw.type_mask += 2
                self.target_raw.position.y = 0.0
                self.target_raw.velocity.y = vy
            else:
                self.target_raw.type_mask += 8
                self.target_raw.position.x = self.local_pose.pose.position.x
                self.target_raw.velocity.x = 0.0
                
                self.target_raw.type_mask += 16
                self.target_raw.position.y = self.local_pose.pose.position.y
                self.target_raw.velocity.y = 0.0
                
            if vz:
                self.target_raw.type_mask += 4
                self.target_raw.position.z = 0.0
                self.target_raw.velocity.z = vz
            else:
                self.target_raw.type_mask += 32
                self.target_raw.position.z = self.local_pose.pose.position.z
                self.target_raw.velocity.z = 0.0
            
            if yaw_rate is not None:
                self.target_raw.yaw_rate = radians(yaw_rate)
                self.target_raw.yaw = 0.0
                
            self.hold_zero_velocity = False
            self.current_control_method = "RAW_VELOCITY"
            return True, f"setting vx={vx}, vy={vy}, vz={vz}, yaw_rate={yaw_rate}rad"
        except ValueError as e:
            return False, f"Invalid values: {e}"
        
    def do_move_to_local_point(self, data):
        try:
            self.start_position.header = self.local_pose.header
            self.start_position.pose = self.local_pose.pose
            
            x = data.get("x", self.setpoint_pose.pose.position.x)
            y = data.get("y", self.setpoint_pose.pose.position.y)
            z = data.get("z", self.setpoint_pose.pose.position.z)
            yaw = data.get("yaw", None)
            self.setpoint_speed = data.get("speed", 1.0)
            
            if self.aruco_nav_status.get("aruco_nav_status"):
                if self.aruco_nav_status.get("map_in_vision"):
                    if self.aruco_nav_status.get("fly_in_borders"):
                        x = max(self.map_width_min, min(x, self.map_width_max))
                        y = max(self.map_height_min, min(y, self.map_height_max))
                    self.target_pose.pose.position.x = x
                    self.target_pose.pose.position.y = y
                    self.target_pose.pose.position.z = z
                else:
                    return False, "No aruco in vision"
            else:
                self.target_pose.pose.position.x = self.home_position.pose.position.x + x
                self.target_pose.pose.position.y = self.home_position.pose.position.y + y
                self.target_pose.pose.position.z = z
                        
            if yaw is not None:
                qw, qx, qy, qz = euler2quat(0, 0, radians(yaw))
                self.setpoint_pose.pose.orientation.x = qx
                self.setpoint_pose.pose.orientation.y = qy
                self.setpoint_pose.pose.orientation.z = qz
                self.setpoint_pose.pose.orientation.w = qw
            
            self.start_position.header.stamp = self.get_clock().now().to_msg()
            self.current_control_method = "LOCAL_POSITION"
            return True, f"Moving to x={x}, y={y}, z={z}"

        except ValueError as e:
            return False, f"Invalid coordinates: {e}"
    
    def do_move_in_body_frame(self, data):
        try:
            self.start_position.header = self.local_pose.header
            self.start_position.pose = self.local_pose.pose
            
            fwd_dist = data.get("x", 0)
            right_dist = data.get("y", 0)
            yaw = data.get("yaw", None)
            self.setpoint_speed = data.get("speed", 1.0)
            
            if yaw is not None:
                calc_yaw_rad = radians(yaw)
                qw, qx, qy, qz = euler2quat(0, 0, radians(yaw))
                self.setpoint_pose.pose.orientation.x = qx
                self.setpoint_pose.pose.orientation.y = qy
                self.setpoint_pose.pose.orientation.z = qz
                self.setpoint_pose.pose.orientation.w = qw
            else:
                q = self.local_pose.pose.orientation
                _, _, calc_yaw_rad = quat2euler([q.w, q.x, q.y, q.z])
                
            delta_north = fwd_dist * cos(calc_yaw_rad) - right_dist * sin(calc_yaw_rad)
            delta_east = fwd_dist * sin(calc_yaw_rad) + right_dist * cos(calc_yaw_rad)

            x = self.local_pose.pose.position.x + delta_north
            y = self.local_pose.pose.position.y + delta_east
            z = data.get("z", self.target_pose.pose.position.z)
            
            if self.aruco_nav_status.get("aruco_nav_status"):
                if self.aruco_nav_status.get("map_in_vision"):
                    if self.aruco_nav_status.get("fly_in_borders"):
                        x = max(self.map_width_min, min(x, self.map_width_max))
                        y = max(self.map_height_min, min(y, self.map_height_max))
                else:
                    return False, "No aruco in vision"
            
            self.target_pose.pose.position.x = x
            self.target_pose.pose.position.y = y
            self.target_pose.pose.position.z = z

            self.start_position.header.stamp = self.get_clock().now().to_msg()
            self.current_control_method = "LOCAL_POSITION"
            
            return True, f"Moving to x={self.target_pose.pose.position.x}, y={self.target_pose.pose.position.y}, z={self.target_pose.pose.position.z}"
        except ValueError as e:
            return False, f"Invalid coordinates: {e}"
    
    def do_move_to_marker(self, data):
        try:
            setpoint_data = {}
            setpoint_data["speed"] = data.get("speed", 1.0)
            target_marker = data.get("marker_id", "")
            marker_info = self.aruco_map.get(target_marker)

            if self.aruco_nav_status.get("aruco_nav_status"):
                if self.aruco_nav_status.get("map_in_vision"):
                    if marker_info:
                        setpoint_data["x"] = marker_info["x"]
                        setpoint_data["y"] = marker_info["y"]
                        setpoint_data["z"] = data.get("z", 0.5)
                    else:
                        return False, f"Marker {target_marker} not found in map"
                    
                    return self.do_move_to_local_point(setpoint_data)
                else:
                    return False, "No aruco map in vision"
            else:
                return False, "Aruco navigation not active"
        
        except Exception as e:
            return False, f"Error: {e}"

def main():
    rclpy.init()
    node = MavrosHandler()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()