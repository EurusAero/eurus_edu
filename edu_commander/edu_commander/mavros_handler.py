import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
import json
import threading
import time
from math import dist, radians, cos, sin

from transforms3d.euler import euler2quat, quat2euler
from mavros_msgs.srv import CommandBool, CommandTOL, SetMode
from mavros_msgs.msg import PositionTarget
from geometry_msgs.msg import PoseStamped
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
        
        self.cmd_sub = self.create_subscription(
            Command,
            'edu/command',
            self.command_callback,
            10
        )
        self.local_pos_sub = self.create_subscription(
            PoseStamped,
            "/mavros/local_position/pose",
            self.local_pos_updater,
            mavros_qos_profile
        )
        
        self.status_pub = self.create_publisher(Command, 'edu/command', 10)
        
        self.target_pose = PoseStamped()
        self.target_pose = self.local_pose
        self.target_raw = PositionTarget()
        
        
        self.timer = self.create_timer(0.05, self.cmd_loop)

        self.first_arm = True
        self.only_arm = True
        self.current_task_thread = None
        self.current_control_method = "LOCAL_POSITION" # LOCAL_POSITION, RAW_VELOCITY 
        self.get_logger().info("MavrosHandler готов к работе.")

    def cmd_loop(self):
        if self.current_control_method == "LOCAL_POSITION":
            self.target_pose.header.stamp = self.get_clock().now().to_msg()
            self.target_pose.header.frame_id = "map"
                    
            if self.only_arm:
                self.target_pose.pose.position.x = self.local_pose.pose.position.x
                self.target_pose.pose.position.y = self.local_pose.pose.position.y
                self.target_pose.pose.position.z = self.local_pose.pose.position.z - 2
                self.target_pose.pose.orientation = self.local_pose.pose.orientation
            
            self.local_pos_pub.publish(self.target_pose)
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

    def point_reached(self, deadzone=0.2):
        local = [float(self.local_pose.pose.position.x), float(self.local_pose.pose.position.y), float(self.local_pose.pose.position.z)]
        target = [float(self.target_pose.pose.position.x), float(self.target_pose.pose.position.y), float(self.target_pose.pose.position.z)]
        
        return dist(local, target) < deadzone

    def calculate_takeoff_position(self, altitude):
        self.target_pose.pose.position.x = self.local_pose.pose.position.x
        self.target_pose.pose.position.y = self.local_pose.pose.position.y
        self.target_pose.pose.position.z = altitude
        
        self.current_control_method = "LOCAL_POSITION"
        
        return self.target_pose
    
    def calculate_next_target_position(self, command_coords: list, yaw=None, body_frame=False):
        if body_frame:
            fwd_dist = command_coords[0]
            right_dist = command_coords[1]
            
            if yaw is not None:
                calc_yaw_rad = radians(yaw)
            else:
                q = self.local_pose.pose.orientation
                _, _, calc_yaw_rad = quat2euler([q.w, q.x, q.y, q.z])

            delta_north = fwd_dist * cos(calc_yaw_rad) - right_dist * sin(calc_yaw_rad)
            delta_east  = fwd_dist * sin(calc_yaw_rad) + right_dist * cos(calc_yaw_rad)

            self.target_pose.pose.position.x = self.local_pose.pose.position.x + delta_north
            self.target_pose.pose.position.y = self.local_pose.pose.position.y + delta_east
            self.target_pose.pose.position.z = command_coords[2]
            
        else:
            
            self.target_pose.pose.position.x = self.home_position.pose.position.x + command_coords[0]
            self.target_pose.pose.position.y = self.home_position.pose.position.y + command_coords[1]
            self.target_pose.pose.position.z = command_coords[2]

        if yaw is None:
            pass
        else:
            qw, qx, qy, qz = euler2quat(0, 0, radians(yaw))
            self.target_pose.pose.orientation.x = qx
            self.target_pose.pose.orientation.y = qy
            self.target_pose.pose.orientation.z = qz
            self.target_pose.pose.orientation.w = qw
            
        self.current_control_method = "LOCAL_POSITION"
        
        return self.target_pose
    
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
                altitude = data.get("altitude", 2.0)
                success, error_msg = self.do_takeoff(altitude)
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
        self.home_position = self.local_pose

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

    def do_takeoff(self, altitude):
        self.get_logger().info(f"Takeoff to {altitude}m")
        
        self.calculate_takeoff_position(float(altitude))
    
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
            x = data.get("x", self.target_pose.pose.position.x)
            y = data.get("y", self.target_pose.pose.position.y)
            z = data.get("z", self.target_pose.pose.position.z)
            yaw = data.get("yaw", None)

            self.calculate_next_target_position((x, y, z), yaw)
            
            self.get_logger().info(f"moving to local point: x={x}, y={y}, z={z}, yaw={yaw}")
            
            return True, f"Moving to x={x}, y={y}, z={z}"

        except ValueError as e:
            return False, f"Invalid coordinates: {e}"
    
    def do_move_in_body_frame(self, data):
        try:
            x = data.get("x", self.target_pose.pose.position.x)
            y = data.get("y", self.target_pose.pose.position.y)
            z = data.get("z", self.target_pose.pose.position.z)
            yaw = data.get("yaw", None)

            self.calculate_next_target_position((x, y, z), yaw, body_frame=True)
            
            self.get_logger().info(f"moving to local point: x={x}, y={y}, z={z}, yaw={yaw}")
            
            # self.do_set_mode("OFFBOARD")

            return True, f"Moving to x={x}, y={y}, z={z}"

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