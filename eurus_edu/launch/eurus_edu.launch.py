from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.substitutions import ThisLaunchFileDir
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([ThisLaunchFileDir(), "/mavros.launch.py"]),
            launch_arguments={"sitl_conn": "false",
                              "fcu_device": "/dev/px4fc:57600",
                              "fcu_ip": "127.0.0.1",
                              "gcs_ip": "10.42.0.1",
                              "gcs_bridge": "udp-b",
                              }.items()
        ),
        Node(
            package="edu_api_server",
            executable="api_server"
        ),
        Node(
            package="edu_aruco_navigation",
            executable="aruco_detection"
        ),
        Node(
            package="edu_camera_stream",
            executable="camera_capture"
        ),
        Node(
            package="edu_camera_stream",
            executable="camera_socket"
        ),
        Node(
            package="edu_commander",
            executable="commander"
        ),
        Node(
            package="edu_commander",
            executable="telem_sender"
        )
        Node(
            package="edu_lasertag_controller",
            executable="laser_gun_controller"
        ),
        Node(
            package="edu_lasertag_controller",
            executable="hit_controller"
        ),
        Node(
            package="edu_led_controller",
            executable="led_controller"
        ),
        Node(
            package="edu_neuro_detection",
            executable="neuro_detection"
        ),
        Node(
            package="edu_web_server",
            executable="web_server"
        )
    ])