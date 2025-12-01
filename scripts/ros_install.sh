#!/usr/bin/env bash

set -e

# Colors
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
NC="\033[0m"

log_stage() {
    echo -e "${YELLOW}==> $1${NC}"
}

log_ok() {
    echo -e "${GREEN}[OK] $1${NC}"
}

log_error() {
    echo -e "${RED}[ERROR] $1${NC}" >&2
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "Запустите скрипт от root или через sudo."
        exit 1
    fi
}

check_command() {
    if ! command -v "$1" &>/dev/null; then
        log_error "Команда '$1' не найдена. Установите её и повторите попытку."
        exit 1
    fi
}

check_root

log_stage "Обновление списков пакетов"
apt update && apt upgrade -y
log_ok "Списки пакетов обновлены"

log_stage "Установка зависимостей"
apt install -y locales curl wget gnupg2 lsb-release build-essential
log_ok "Зависимости установлены"

log_stage "Настройка локали"
locale-gen en_US en_US.UTF-8
update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
export LANG=en_US.UTF-8
log_ok "Локаль настроена"

log_stage "Добавление репозитория ROS2 Humble"
curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key | apt-key add -
sh -c 'echo "deb [arch=$(dpkg --print-architecture)] http://packages.ros.org/ros2/ubuntu $(lsb_release -sc) main" > /etc/apt/sources.list.d/ros2.list'
log_ok "Репозиторий добавлен"

log_stage "Обновление списков пакетов после добавления репозитория"
apt update
log_ok "Обновлено"

log_stage "Установка ROS2 Humble (ros-core)"
apt install -y ros-humble-ros-core
log_ok "ROS2 Humble Core установлен"

log_stage "Установка инструментов разработки ROS2"
apt install -y ros-dev-tools python3-colcon-common-extensions
log_ok "Инструменты разработки установлены"

log_stage "Добавление среды ROS2 в .bashrc"
if ! grep -q "source /opt/ros/humble/setup.bash" ~/.bashrc; then
    echo "source /opt/ros/humble/setup.bash" >> ~/.bashrc
    log_ok "Добавлено в .bashrc"
else
    log_ok "Источник ROS2 уже присутствует в .bashrc"
fi

log_stage "Проверка установки"
check_command ros2
log_ok "ROS2 успешно установлен"

echo -e "${GREEN}=== Установка завершена успешно! Перезапустите терминал. ===${NC}"
