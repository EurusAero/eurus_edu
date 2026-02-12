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

from transforms3d.euler import euler2quat, quat2euler
from mavros_msgs.srv import CommandBool, CommandTOL, SetMode
from mavros_msgs.msg import PositionTarget, State
from geometry_msgs.msg import PoseStamped
from std_msgs.msg import String
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
        
        # Чтение конфига аруко маркеров
        home_dir = os.getenv("HOME")
        ini_path = f"{home_dir}/ros2_ws/src/eurus_edu/edu_aruco_navigation/eurus.ini"
        
        self.aruco_map_path = ""
        self.map_height_m = 0
        self.map_width_m = 0
        
        if os.path.exists(ini_path):
            config = configparser.ConfigParser()
            config.read(ini_path)
            
            self.aruco_map_path = config["aruco"].get("map_path", "")
        
        if self.aruco_map_path and os.path.exists(self.aruco_map_path):
            with open(self.aruco_map_path, "r") as f:
                markers_info = f.readline()
            
            params = markers_info.strip().split()
            markers_x = int(params[0])
            markers_y = int(params[1])
            marker_len = float(params[2])
            marker_sep = float(params[3])
            
            self.map_width_m = markers_x * marker_len + (markers_x - 1) * marker_sep
            self.map_height_m = markers_y * marker_len + (markers_y - 1) * marker_sep
            
        self.setpoint_pose = PoseStamped()
        self.start_position = PoseStamped()
        self.target_pose = PoseStamped()
        # self.setpoint_pose = self.local_pose
        self.target_raw = PositionTarget()
        self.state_msg = State()
        
        
        self.timer = self.create_timer(0.033, self.cmd_loop)

        # self.first_arm = True
        self.only_arm = True
        self.current_task_thread = None
        self.current_control_method = "LOCAL_POSITION" # LOCAL_POSITION, RAW_VELOCITY
        self.setpoint_speed = 1.0
        self.get_logger().info("MavrosHandler готов к работе.")

    def cmd_loop(self):
        if self.current_control_method == "LOCAL_POSITION":
            self.setpoint_pose.header.stamp = self.get_clock().now().to_msg()
            self.setpoint_pose.header.frame_id = "map"
                    
            if self.only_arm:
                self.setpoint_pose.pose.position.x = self.local_pose.pose.position.x
                self.setpoint_pose.pose.position.y = self.local_pose.pose.position.y
                self.setpoint_pose.pose.position.z = self.local_pose.pose.position.z - 2
                self.setpoint_pose.pose.orientation = self.local_pose.pose.orientation
            else:    
                self.calculate_next_target_position()
                
            self.local_pos_pub.publish(self.setpoint_pose)
        elif self.current_control_method == "RAW_VELOCITY":
            self.target_raw.header.stamp = self.get_clock().now().to_msg()
            self.target_raw.header.frame_id = "map"
            
            self.target_raw.coordinate_frame = 8
            self.target_raw.type_mask = 1479
            
            self.raw_velocity_pub.publish(self.target_raw)
            
        
    def _wait_for_services(self):
        """Ждем доступности сервисов MAVROS при запуске."""
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
        self.aruco_nav_status = json.loads(msg.data)

    def get_distance(self, start, end):
        start = [float(start.pose.position.x), float(start.pose.position.y), float(start.pose.position.z)]
        end = [float(end.pose.position.x), float(end.pose.position.y), float(end.pose.position.z)]

        return dist(start, end)
    
    def point_reached(self, deadzone=0.2):
        local = [float(self.local_pose.pose.position.x), float(self.local_pose.pose.position.y), float(self.local_pose.pose.position.z)]
        target = [float(self.target_pose.pose.position.x), float(self.target_pose.pose.position.y), float(self.target_pose.pose.position.z)]
        
        return dist(local, target) < deadzone

    def calculate_next_target_position(self):
        hold_pos = False
        if not self.state_msg.armed:
            self.start_position.header.stamp = self.get_clock().now().to_msg()
        
        if self.aruco_nav_status["aruco_nav_status"] and not self.aruco_nav_status["map_in_vision"] and (time.time() - self.aruco_nav_status["timestamp"]) > 0.5:
            self.start_position.header.stamp = self.get_clock().now().to_msg()
            self.start_position.pose = self.setpoint_pose.pose
            hold_pos = True
            
        stamp = self.start_position.header.stamp
        time = self.get_distance(self.start_position, self.target_pose) / self.setpoint_speed

        now_time = self.get_clock().now()
        start_time = Time.from_msg(stamp) 
        elapsed_seconds = (now_time - start_time).nanoseconds / 1e9

        if time > 0 and not hold_pos:
            passed = min((elapsed_seconds / time), 1)
            
            self.setpoint_pose.pose.position.x = self.start_position.pose.position.x + (self.target_pose.pose.position.x - self.start_position.pose.position.x) * passed
            self.setpoint_pose.pose.position.y = self.start_position.pose.position.y + (self.target_pose.pose.position.y - self.start_position.pose.position.y) * passed
            self.setpoint_pose.pose.position.z = self.start_position.pose.position.z + (self.target_pose.pose.position.z - self.start_position.pose.position.z) * passed
            
        return self.setpoint_pose
    
    def calculate_next_target_velocity(self, vx, vy, vz, yaw_rate=None):
        self.target_raw.velocity.x = vx
        self.target_raw.velocity.y = vy
        self.target_raw.velocity.z = vz
        
        if yaw_rate is not None:
            self.target_raw.yaw_rate = radians(yaw_rate)
        
        self.current_control_method = "RAW_VELOCITY"
        
        return self.target_raw
    
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
            else:
                success = False
                error_msg = f"Unknown command: {cmd_name}"
        except Exception as e:
            success = False
            error_msg = str(e)
            self.get_logger().error(f"Exception: {e}")

        final_status = COMPLETED_STATUS if success else DENIED_STATUS
        self.publish_status(msg, final_status, error_msg)


    def _call_service_sync(self, client, request):
        future = client.call_async(request)
        while not future.done():
            time.sleep(0.04)
        return future.result()
    
    def wait_movement(self):
        pass
    
    def set_home_position(self):
        self.home_position.pose = self.local_pose.pose

    def do_set_mode(self, mode="OFFBOARD"):
        req = SetMode.Request()
        req.custom_mode = mode
        res = self._call_service_sync(self.set_mode_client, req)
        if res.mode_sent:
            return True, "Mode sent"
        return False, f"Mode sent failed: {res.result}"

    def do_arm(self):        
        self.do_set_mode("OFFBOARD")
        time.sleep(0.5)
        
        # if self.first_arm:
        self.set_home_position()
            # self.first_arm = False
        
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
        altitude = data.get("altitude", 2.0)
        self.setpoint_speed = data.get("speed", 1)
        
        self.get_logger().info(f"Takeoff to {altitude}m")
        
        self.start_position.header = self.local_pose.header
        self.start_position.pose = self.local_pose.pose
        
        self.target_pose.pose.position.x = self.local_pose.pose.position.x
        self.target_pose.pose.position.y = self.local_pose.pose.position.y
        self.target_pose.pose.position.z = altitude
        self.current_control_method = "LOCAL_POSITION"
        
        # self.calculate_takeoff_position(float(altitude))
        self.do_set_mode("OFFBOARD")
        self.do_arm()
        
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

            self.calculate_next_target_velocity(vx, vy, vz, yaw_rate)
            
            self.get_logger().info(f"setting velocity: vx={vx}, vy={vy}, vz={vz}, yaw_rate={yaw_rate}")
            
            return True, f"setting vx={vx}, vy={vy}, vz={vz}, yaw_rate={yaw_rate}"
            
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
            
            if self.aruco_nav_status["aruco_nav_status"] and self.aruco_nav_status["map_in_vision"] and self.aruco_nav_status["fly_in_borders"]:
                x = x if x <= self.map_width_m else self.map_width_m
                y = y if y <= self.map_height_m else self.map_height_m
                
            
            self.target_pose.pose.position.x = self.home_position.pose.position.x + x
            self.target_pose.pose.position.y = self.home_position.pose.position.y + y
            self.target_pose.pose.position.z = z
                        
            if yaw is not None:
                qw, qx, qy, qz = euler2quat(0, 0, radians(yaw))
                self.setpoint_pose.pose.orientation.x = qx
                self.setpoint_pose.pose.orientation.y = qy
                self.setpoint_pose.pose.orientation.z = qz
                self.setpoint_pose.pose.orientation.w = qw
            
            # self.calculate_next_target_position((x, y, z), yaw)
            self.current_control_method = "LOCAL_POSITION"

            self.get_logger().info(f"moving to local point: x={x}, y={y}, z={z}, yaw={yaw}")
            
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
            
            if self.aruco_nav_status["aruco_nav_status"] and self.aruco_nav_status["map_in_vision"] and self.aruco_nav_status["fly_in_borders"]:
                x = x if x <= self.map_width_m else self.map_width_m
                y = y if y <= self.map_height_m else self.map_height_m
            
            self.target_pose.pose.position.x = x
            self.target_pose.pose.position.y = y
            self.target_pose.pose.position.z = data.get("z", self.target_pose.pose.position.z)

            # self.calculate_next_target_position((x, y, z), yaw, body_frame=True)
            self.current_control_method = "LOCAL_POSITION"
            self.get_logger().info(f"moving to local point: x={self.target_pose.pose.position.x}, y={self.target_pose.pose.position.y}, z={self.target_pose.pose.position.z}, yaw={yaw}")
            
            # self.do_set_mode("OFFBOARD")

            return True, f"Moving to x={self.target_pose.pose.position.x}, y={self.target_pose.pose.position.y}, z={self.target_pose.pose.position.z}"
        except ValueError as e:
            return False, f"Invalid coordinates: {e}"

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