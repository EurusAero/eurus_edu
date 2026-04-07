import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('sitl_conn', default_value='false', description='Use SITL connection'),
        DeclareLaunchArgument('fcu_device', default_value='/dev/px4fc:57600', description='FCU device path'),
        DeclareLaunchArgument('fcu_ip', default_value='127.0.0.1', description='FCU IP for SITL'),
        DeclareLaunchArgument('gcs_ip', default_value='10.42.0.1', description='GCS IP address'),
        DeclareLaunchArgument('gcs_bridge', default_value='udp-b', description='GCS bridge type (udp, udp-b, udp-pb, tcp)'),
        DeclareLaunchArgument('tgt_system', default_value='1', description='Target system ID'),
        DeclareLaunchArgument('tgt_component', default_value='1', description='Target component ID'),
        DeclareLaunchArgument('log_output', default_value='screen', description='Log output type'),
        DeclareLaunchArgument('fcu_protocol', default_value='v2.0', description='MAVLink protocol version'),
        DeclareLaunchArgument('respawn_mavros', default_value='false', description='Auto-respawn MAVROS node'),
        DeclareLaunchArgument('namespace', default_value='mavros', description='MAVROS node namespace'),

        OpaqueFunction(function=evaluate_urls_and_include)
    ])

def evaluate_urls_and_include(context, *args, **kwargs):
    # Получаем реальные строковые значения аргументов из контекста запуска
    sitl_conn = LaunchConfiguration('sitl_conn').perform(context)
    fcu_device = LaunchConfiguration('fcu_device').perform(context)
    fcu_ip = LaunchConfiguration('fcu_ip').perform(context)
    gcs_ip = LaunchConfiguration('gcs_ip').perform(context)
    gcs_bridge = LaunchConfiguration('gcs_bridge').perform(context)

    # 1. Логика для fcu_url (USB или SITL)
    if sitl_conn.lower() == 'true':
        fcu_url_val = f"udp://:14540@{fcu_ip}:14557"
    else:
        fcu_url_val = fcu_device

    # 2. Логика для gcs_url (TCP или UDP)
    if gcs_bridge == 'tcp':
        gcs_url_val = f"tcp-l://{gcs_ip}:5760"
    else:
        # Автоматически подставит udp, udp-b или udp-pb
        gcs_url_val = f"{gcs_bridge}://{gcs_ip}:14550@14550"

    # Получаем путь к пакету mavros
    mavros_share = get_package_share_directory('mavros')

    # Подключаем node.launch с вычисленными параметрами
    node_launch = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(
            os.path.join(mavros_share, 'launch', 'node.launch')
        ),
        launch_arguments={
            'pluginlists_yaml': os.path.join(mavros_share, 'launch', 'px4_pluginlists.yaml'),
            'config_yaml': os.path.join(mavros_share, 'launch', 'px4_config.yaml'),
            'fcu_url': fcu_url_val,
            'gcs_url': gcs_url_val,
            'tgt_system': LaunchConfiguration('tgt_system'),
            'tgt_component': LaunchConfiguration('tgt_component'),
            'log_output': LaunchConfiguration('log_output'),
            'fcu_protocol': LaunchConfiguration('fcu_protocol'),
            'respawn_mavros': LaunchConfiguration('respawn_mavros'),
            'namespace': LaunchConfiguration('namespace'),
        }.items()
    )

    return [node_launch]
