#!/bin/bash

DEVICE="/dev/$1"

/usr/bin/v4l2-ctl -d $DEVICE --set-ctrl exposure_auto=1
/usr/bin/v4l2-ctl -d $DEVICE --set-ctrl exposure_absolute=400
