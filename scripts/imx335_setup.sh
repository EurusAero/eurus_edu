#!/bin/bash

DEVICE="/dev/$1"

/usr/bin/v4l2-ctl -d $DEVICE --set-ctrl exposure_auto=1
/usr/bin/v4l2-ctl -d $DEVICE --set-ctrl exposure_absolute=400
# резервные настройки если не подойдут прошлые
/usr/bin/v4l2-ctl -d $DEVICE --set-ctrl auto_exposure=1
/usr/bin/v4l2-ctl -d $DEVICE --set-ctrl exposure_time_absolute=400
/usr/bin/v4l2-ctl -d $DEVICE --set-ctrl exposure_dynamic_framerate=0
