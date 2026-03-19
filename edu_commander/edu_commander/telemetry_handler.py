import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
import json

from geometry_msgs.msg import PoseStamped, TwistStamped
from sensor_msgs.msg import BatteryState
from mavros_msgs.msg import State
from std_msgs.msg import String, Bool

from EurusEdu.const import *
from transforms3d.euler import quat2euler
from math import degrees, dist


class TelemetryHandler(Node):
    def __init__(self):
        super().__init__("edu_commander")
        
        sensor_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=5
            )
        
        publisher_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )
        
        self.telemetry_msg = TELEMETRY_DATA
        self.ros_msg = String()
        
        self.telemetry_pub = self.create_publisher(String, "edu/telemetry", publisher_qos)
        
        
        self.create_subscription(BatteryState, "/mavros/battery", self.battery_updater, sensor_qos)
        self.create_subscription(State, "/mavros/state", self.state_updater, sensor_qos)
        self.create_subscription(PoseStamped, "/mavros/local_position/pose", self.local_position_updater, sensor_qos)
        self.create_subscription(TwistStamped, "/mavros/local_position/velocity_local", self.velocity_updater, sensor_qos)
        self.create_subscription(PoseStamped, "/mavros/setpoint_position/local", self.setpoint_position_updater, sensor_qos)
        self.create_subscription(Bool, "/edu/is_alive", )
        
        self.battery_msg = BatteryState()
        self.local_position_msg = PoseStamped()
        self.setpoint_position_msg = PoseStamped()
        self.velocity_msg = TwistStamped()
        self.state_msg = State()
        
        self.timer = self.create_timer(0.05, self.telemetry_publisher)
    
    def battery_updater(self, msg):
        self.battery_msg = msg
    
    def local_position_updater(self, msg):
        self.local_position_msg = msg

    def velocity_updater(self, msg):
        self.velocity_msg = msg
    
    def setpoint_position_updater(self, msg):
        self.setpoint_position_msg = msg
    
    def state_updater(self, msg):
        self.state_msg = msg
    
    def is_alive_updater(self, msg):
        self.is_alive = msg.data
    
    def telemetry_publisher(self):
        self.telemetry_msg["state"]["connected"] = self.state_msg.connected
        self.telemetry_msg["state"]["armed"] = self.state_msg.armed
        self.telemetry_msg["state"]["mode"] = self.state_msg.mode
        self.telemetry_msg["state"]["system_status"] = self.state_msg.system_status
        
        self.telemetry_msg["battery"]["voltage"] = self.battery_msg.voltage
        self.telemetry_msg["battery"]["cell_voltage"] = list(self.battery_msg.cell_voltage)
        self.telemetry_msg["battery"]["current"] = self.battery_msg.current
        self.telemetry_msg["battery"]["percentage"] = int(self.battery_msg.percentage * 100)
        
        pose = self.local_position_msg.pose.position
        orient = self.local_position_msg.pose.orientation
        
        self.telemetry_msg["local_position"]["x"] = pose.x
        self.telemetry_msg["local_position"]["y"] = pose.y
        self.telemetry_msg["local_position"]["z"] = pose.z
        
        orientation_angles = quat2euler((orient.w, orient.x, orient.y, orient.z))
        
        self.telemetry_msg["local_position"]["roll"] = degrees(orientation_angles[0])
        self.telemetry_msg["local_position"]["pitch"] = degrees(orientation_angles[1])
        self.telemetry_msg["local_position"]["yaw"] = degrees(orientation_angles[2])
        
        setpoint_pose = self.setpoint_position_msg.pose.position
        setpoint_orient = self.setpoint_position_msg.pose.orientation
        
        setpoint_orientation_angles = quat2euler((setpoint_orient.w, setpoint_orient.x, setpoint_orient.y, setpoint_orient.z))        
        
        self.telemetry_msg["setpoint_local"]["x"] = setpoint_pose.x
        self.telemetry_msg["setpoint_local"]["y"] = setpoint_pose.y
        self.telemetry_msg["setpoint_local"]["z"] = setpoint_pose.z
        self.telemetry_msg["setpoint_local"]["yaw"] = degrees(setpoint_orientation_angles[2])
        
        velocity = self.velocity_msg.twist.linear
        
        self.telemetry_msg["velocity"]["vx"] = velocity.x
        self.telemetry_msg["velocity"]["vy"] = velocity.y
        self.telemetry_msg["velocity"]["vz"] = velocity.z
        
        point_reached = dist([pose.x, pose.y, pose.z], [setpoint_pose.x, setpoint_pose.y, setpoint_pose.z]) <= 0.2
        
        self.telemetry_msg["point_reached"] = point_reached
        self.telemetry_msg["lasertag_hitted"] = self.is_alive
        
        self.ros_msg.data = json.dumps(self.telemetry_msg)
        
        self.telemetry_pub.publish(self.ros_msg)
        

def main():
    rclpy.init()
    node = TelemetryHandler()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()