## Установка ROS1 Noetic

Устанавливаем ubuntu focal (20.04, server, linux5) для [Orange Pi 5](https://drive.google.com/drive/folders/1i5zQOg1GIA4_VNGikFl2nPM0Y2MBw2M0)
Установить ROS Noetic как в [документации](https://wiki.ros.org/noetic/Installation/Ubuntu), качаем ros-noetic-ros-base
Создаем catkin workspace согласно [документации](https://wiki.ros.org/catkin/Tutorials/create_a_workspace)

## Установка MAVROS

```bash
sudo apt-get install ros-${ROS_DISTRO}-mavros ros-${ROS_DISTRO}-mavros-extras ros-${ROS_DISTRO}-mavros-msgs -y
wget https://raw.githubusercontent.com/mavlink/mavros/master/mavros/scripts/install_geographiclib_datasets.sh
sudo bash ./install_geographiclib_datasets.sh
```

## Установка Clover

Клонируем репозиторий кловера и драйверов led ленты в рабочее пространство

```bash
cd ~/catkin_ws/src
git clone https://github.com/EurusAero/clover.git clover
git clone https://github.com/EurusAero/ros_led.git ros_led
echo "source ~/catkin_ws/devel/setup.bash
export ROS_HOSTNAME=10.42.0.1" >> ~/.bashrc
```

Устанавливаем зависимости

```bash
sudo apt install ros-noetic-image-transport ros-noetic-gazebo-plugins ros-noetic-image-proc ros-noetic-xacro ros-noetic-image-geometry ros-noetic-ros-pytest ros-noetic-led-msgs ros-noetic-tf2-web-republisher ros-noetic-tf2-geometry-msgs ros-noetic-image-publisher ros-noetic-web-video-server ros-noetic-rosbridge-server ros-noetic-cv-camera -y
```

```bash
cd ~/catkin_ws/
rosdep install -y --from-paths src --ignore-src
catkin_make -j1
```

Ставим udev правила для всех устройств

```bash
sudo cp ~/catkin_ws/src/clover/clover/udev/*.rules /lib/udev/rules.d
sudo udevadm trigger
```

## WIFI hotspot

```bash
sudo nano /etc/netplan/orangepi-default.yaml
```

```
network:
  version: 2
  renderer: NetworkManager
  wifis:
    wlx90de80a49f46:
      dhcp4: true
      optional: true
      access-points:
        "EURUS_EDU_CLOVER":
          auth:
            key-management: psk
            password: "euruswifi"
          mode: ap
          band: 5GHz
          networkmanager:
            passthrough:
              wifi-security.proto: "rsn" # WPA2 only
```

```bash
sudo netplan apply
```

## Запуск сервисов

```bash
sudo cp ~/catkin_ws/src/clover/builder/assets/clover.service /etc/systemd/system
sudo cp ~/catkin_ws/src/clover/builder/assets/roscore.service /etc/systemd/system
```

```bash
sudo systemctl enable clover.service roscore.service
```

## Включение интерфейса SPI

```bash
sudo nano /boot/orangepiEnv.txt
```

Добавляем

```
overlays=spi4-m0-cs1-spidev
```
