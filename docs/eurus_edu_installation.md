## Установка системы

Устанавливаем ubuntu jammy (22.04, server, linux5) для [Orange Pi 5](https://drive.google.com/drive/folders/1i5zQOg1GIA4_VNGikFl2nPM0Y2MBw2M0)

```bash
sudo apt update && sudo apt upgrade -y
```

## Клонировать репозиторий

```bash
mkdir -p ~/ros2_ws/src
cd ~/ros2_ws/src
git clone https://github.com/EurusAero/eurus_edu
```

## Установить ROS2 Humble

```bash
cd ~/ros2_ws/src/eurus_edu
chmod +x ./scripts/*
sudo ./scripts/ros_install.sh
```

## Устновка зависимостей

```bash
cd ~

git clone --recursive https://github.com/orangepi-xunlong/wiringOP-Python -b next

cd wiringOP-Python
git submodule update --init --remote
python3 generate-bindings.py > bindings.i
sudo python3 setup.py install

sudo apt install python3-pip ffmpeg libsm6 libxext6 cmake ros-humble-mavros -y
pip3 install ~/ros2_ws/src/eurus_edu/libs/python/EurusEdu/ packaging==25.0

wget https://raw.githubusercontent.com/mavlink/mavros/ros2/mavros/scripts/install_geographiclib_datasets.sh
chmod +x install_geographiclib_datasets.sh
sudo ./install_geographiclib_datasets.sh
```

## Установка ultralytics (нейронка)

```bash
pip3 install --upgrade setuptools==79.0.1 pip==25.3 wheel==0.45.1
pip3 install torchvision==0.17 ultralytics==8.4.2 onnx==1.16.1 onnxslim==0.1.82 rknn-toolkit2==2.3.2 rknn-toolkit-lite2==2.3.2

sudo reboot
```

## Сборка проекта

```bash
cd ~/ros2_ws
colcon build
echo "source ~/ros2_ws/src/install/setup.bash" >> ~/.bashrc
```

## Установка udev-правил

```bash
sudo cp ~/ros2_ws/src/eurus_edu/udev/*.rules /etc/udev/rules.d/
sudo udevadm trigger
```

После этого обязательно перезагрузить апельсинку

## Включение интерфейса SPI

```bash
sudo nano /boot/orangepiEnv.txt
```

Добавляем

```
overlays=spi4-m0-cs1-spidev
```

## Запуск сервисов

sudo cp ~/ros2*ws/src/eurus_edu/services/\*.service /etc/systemd/system
sudo systemctl enable start*\*.service

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
        "EURUS_EDU_00":
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
