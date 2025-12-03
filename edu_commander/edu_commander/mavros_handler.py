import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
import json
import threading
import time
import math

from transforms3d.euler import euler2quat
from mavros_msgs.srv import CommandBool, CommandTOL, SetMode
from geometry_msgs.msg import PoseStamped
from edu_msgs.msg import Command
from EurusEdu.const import *


class MavrosHandler(Node):
    def __init__(self):
        super().__init__("edu_commander")
        
        # Настройка QoS
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
        
        self._wait_for_services()

        self.cmd_sub = self.create_subscription(
            Command,
            'edu/command',
            self.command_callback,
            10
        )

        self.status_pub = self.create_publisher(Command, 'edu/command', 10)
        
        self.target_pose = PoseStamped()
        self.target_pose.pose.position.x = 0.0
        self.target_pose.pose.position.y = 0.0
        self.target_pose.pose.position.z = 0.0
        self.target_pose.pose.orientation.w = 1.0
        
        self.timer = self.create_timer(0.05, self.cmd_loop)

        self.current_task_thread = None
        self.get_logger().info("MavrosHandler готов к работе.")

    def cmd_loop(self):
        self.target_pose.header.stamp = self.get_clock().now().to_msg()
        self.target_pose.header.frame_id = 1
        self.local_pos_pub.publish(self.target_pose)

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
            if cmd_name == "arm":
                success, error_msg = self.do_arm()
            elif cmd_name == "disarm":
                success, error_msg = self.do_disarm()
            elif cmd_name == "takeoff":
                altitude = data.get("altitude", 2.0)
                success, error_msg = self.do_takeoff(altitude)
            elif cmd_name == "land":
                success, error_msg = self.do_land()
            elif cmd_name == "goto": 
                success, error_msg = self.do_goto(data)
            elif cmd_name == "set_mode":
                mode = data.get("mode", "OFFBOARD")
                success, error_msg = self.do_set_mode(mode)
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

        self.target_pose.pose.position.z = float(altitude)

        self.do_set_mode("OFFBOARD")
        self.do_arm()
        return True, "Takeoff initiated"

    def do_land(self):
        req = CommandTOL.Request()
        res = self._call_service_sync(self.land_client, req)
        if res.success:
            return True, "Landing (Service)"
        return False, "Landing failed"

    def do_goto(self, data):
        try:
            x = data.get("x", self.target_pose.pose.position.x)
            y = data.get("y", self.target_pose.pose.position.y)
            z = data.get("z", self.target_pose.pose.position.z)
            yaw = data.get("yaw", 0.0)

            self.target_pose.pose.position.x = float(x)
            self.target_pose.pose.position.y = float(y)
            self.target_pose.pose.position.z = float(z)

            qw, qx, qy, qz = euler2quat(0, 0, yaw)
            self.target_pose.pose.orientation.x = qx
            self.target_pose.pose.orientation.y = qy
            self.target_pose.pose.orientation.z = qz
            self.target_pose.pose.orientation.w = qw

            self.get_logger().info(f"GOTO: x={x}, y={y}, z={z}, yaw={yaw}")
            
            self.do_set_mode("OFFBOARD")

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