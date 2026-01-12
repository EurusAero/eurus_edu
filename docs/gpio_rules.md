sudo groupadd gpio
sudo usermod -aG gpio $USER
sudo nano /etc/udev/rules.d/99-gpio.rules

```
SUBSYSTEM=="gpio", KERNEL=="gpiochip*", ACTION=="add", PROGRAM="/bin/sh -c 'chown root:gpio /sys/class/gpio/export /sys/class/gpio/unexport; chmod 220 /sys/class/gpio/export /sys/class/gpio/unexport'"
SUBSYSTEM=="gpio", KERNEL=="gpio*", PROGRAM="/bin/sh -c 'chown root:gpio /sys/class/gpio/%k/value /sys/class/gpio/%k/direction /sys/class/gpio/%k/edge; chmod 660 /sys/class/gpio/%k/value /sys/class/gpio/%k/direction /sys/class/gpio/%k/edge'"
```

sudo reboot
