#!/bin/bash

source /opt/ros/humble/setup.bash
source /home/orangepi/ros2_ws/install/setup.bash

sudo -E env PATH="$PATH" \
            PYTHONPATH="$PYTHONPATH" \
            LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
            ros2 run edu_lasertag_controller laser_gun_controller