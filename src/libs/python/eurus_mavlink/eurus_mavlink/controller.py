from pymavlink import mavutil
import time
import math


class EurusController:
    def __init__(self):
        self.master = None
        self.connected = False

    def connect(self, port="/dev/fc", baud=115200):
        try:
            self.master = mavutil.mavlink_connection(port, baud=baud)
            self.master.wait_heartbeat()
            print("FC connected!")
            self.connected = True
            return 1
        except Exception as e:
            print(f"Connection error: {e}")
            self.connected = False
            return 0

    def disconnect(self):
        if not self.connected:
            print("Not connected")
            return 0

        try:
            self.master.close()
            self.connected = False
            print("Disconnected from FC")
            return 1
        except Exception as e:
            print(f"Disconnect error: {e}")
            return 0

    def is_armed(self):
        try:
            msg = self.master.recv_match(type="HEARTBEAT", blocking=True, timeout=1)
            if not msg:
                print("No heartbeat")
                return 0

            armed = (msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED) != 0
            return 1 if armed else 0

        except Exception as e:
            print(f"ARM status error: {e}")
            return 0

    def arm(self):
        if not self.connected:
            print("Not connected")
            return 0

        try:
            self.master.motors_armed_wait()
            print("Armed!")
            return 1
        except Exception as e:
            print(f"Arm error: {e}")
            return 0

    def disarm(self):
        if not self.connected:
            print("Not connected")
            return 0

        try:
            self.master.motors_disarmed_wait()
            print("Disarmed!")
            return 1
        except Exception as e:
            print(f"Disarm error: {e}")
            return 0

    def takeoff(self, altitude=2):
        if not self.connected:
            print("Not connected")
            return 0

        try:
            self.master.mav.command_long_send(
                self.master.target_system,
                self.master.target_component,
                mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
                0,
                0, 0, 0, 0,
                0, 0,
                altitude
            )
            print("Takeoff command sent!")
            return 1
        except Exception as e:
            print(f"Takeoff error: {e}")
            return 0

    def land(self):
        if not self.connected:
            print("Not connected")
            return 0

        try:
            self.master.mav.command_long_send(
                self.master.target_system,
                self.master.target_component,
                mavutil.mavlink.MAV_CMD_NAV_LAND,
                0,
                0, 0, 0, 0,
                0, 0,
                0
            )
            print("Land command sent!")
            return 1
        except Exception as e:
            print(f"Land error: {e}")
            return 0

    def goto_local_position(self, x, y, z, yaw_deg):
        if not self.connected:
            print("Not connected")
            return 0

        try:
            yaw = math.radians(yaw_deg)

            frame = mavutil.mavlink.MAV_FRAME_LOCAL_NED

            type_mask = (
                mavutil.mavlink.POSITION_TARGET_TYPEMASK_VX_IGNORE |
                mavutil.mavlink.POSITION_TARGET_TYPEMASK_VY_IGNORE |
                mavutil.mavlink.POSITION_TARGET_TYPEMASK_VZ_IGNORE |
                mavutil.mavlink.POSITION_TARGET_TYPEMASK_AX_IGNORE |
                mavutil.mavlink.POSITION_TARGET_TYPEMASK_AY_IGNORE |
                mavutil.mavlink.POSITION_TARGET_TYPEMASK_AZ_IGNORE |
                mavutil.mavlink.POSITION_TARGET_TYPEMASK_YAW_RATE_IGNORE
            )

            self.master.mav.set_position_target_local_ned_send(
                (time.time() * 1000),
                self.master.target_system, self.master.target_component,
                frame,
                type_mask,
                x, y, z,
                0.0, 0.0, 0.0,
                0.0, 0.0, 0.0,
                yaw, 0.0
            )

            print(f"Local NED sent: x={x}, y={y}, z={z}, yaw={yaw_deg}")
            return 1

        except Exception as e:
            print(f"Local position error: {e}")
            return 0

    def set_mode(self, mode_name):
        if not self.connected:
            print("Not connected")
            return 0

        try:
            mode_map = self.master.mode_mapping()
            if mode_map is None:
                print("Mode mapping not available")
                return 0

            mode_tuple = mode_map.get(mode_name)
            if mode_tuple is None:
                print(f"Mode {mode_name} not supported")
                return 0

            self.master.set_mode(*mode_tuple)

            print(f"Mode change command sent to {mode_name}")
            return 1

        except Exception as e:
            print(f"Set mode error: {e}")
            return 0
