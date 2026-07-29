#!/bin/bash

source /opt/ros/humble/setup.bash
source /home/orangepi/ros2_ws/install/setup.bash

source /home/orangepi/ros2_ws/src/eurus_edu/scripts/set_domain_id.sh
exec ros2 run edu_aruco_navigation aruco_detection