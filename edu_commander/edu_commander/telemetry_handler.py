import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
import json

from geometry_msgs.msg import PoseStamped, TwistStamped
from sensor_msgs.msg import BatteryState
from mavros_msgs.msg import State

from EurusEdu.const import *


class TelemetryHandler(Node):
    def __init__(self):
        sensor_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=5
            )
        
        self.create_subscription(BatteryState, "/mavros/battery", self.battery_updater, sensor_qos)
        self.create_subscription(State, "/mavros/state", self.state_updater, sensor_qos)
        self.create_subscription(PoseStamped, "/mavros/local_position/pose", self.local_position_updater, sensor_qos)
        self.create_subscription(TwistStamped, "/mavros/local_position/velocity_local", self.velocity_updater, sensor_qos)
        self.create_subscription(PoseStamped, "/mavros/setpoint_position/local", self.setpoint_position_updater, sensor_qos)
    
    def battery_updater(self, msg):
        pass
    
    def local_position_updater(self, msg):
        pass
    
    def velocity_updater(self, msg):
        pass
    
    def setpoint_position_updater(self, msg):
        pass
    
    def state_updater(self, msg):
        pass