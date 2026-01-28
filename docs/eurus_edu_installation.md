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

sudo apt install $(cat ~/ros2_ws/src/eurus_edu/depends/packages.txt)
pip3 install -r ~/ros2_ws/src/eurus_edu/depends/pip_packages.txt

pip3 install ~/ros2_ws/src/eurus_edu/libs/python/EurusEdu/

wget https://raw.githubusercontent.com/mavlink/mavros/ros2/mavros/scripts/install_geographiclib_datasets.sh
chmod +x install_geographiclib_datasets.sh
sudo ./install_geographiclib_datasets.sh
echo "source /opt/ros/humble/setup.bash" >> ~/.bashrc

sudo reboot
```

## Сборка проекта

```bash
cd ~/ros2_ws
colcon build
echo "source ~/ros2_ws/install/setup.bash" >> ~/.bashrc
```

## Установка udev-правил

```bash
sudo cp ~/ros2_ws/src/eurus_edu/udev/*.rules /etc/udev/rules.d/
sudo udevadm trigger
```

## Включение интерфейса SPI

```bash
sudo nano /boot/orangepiEnv.txt
```

Добавляем

```
overlays=spi4-m0-cs1-spidev
```

После этого обязательно перезагрузить апельсинку

```bash
sudo reboot
```

## Запуск сервисов

sudo cp ~/ros2_ws/src/eurus_edu/services/\*.service /etc/systemd/system

Активируем все сервисы:
sudo systemctl enable edu\_....service

## WIFI hotspot

```bash
sudo cp ~/ros2_ws/src/eurus_edu/scripts/network_setup /etc/init.d/network_setup
```

```bash
sudo chmod +x /etc/init.d/network_setup
sudo chown root:root /etc/init.d/network_setup
sudo update-rc.d network_setup defaults 95
```

Чтоб проверить создавшийся симлинк можно ввести:

```bash
ls -l /etc/rc*.d/*network*
```
