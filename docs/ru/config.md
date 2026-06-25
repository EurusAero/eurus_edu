# Конфигурационные файлы системы

## Web Server

Настройки встроенного веб-сервера

**Параметры:**

- `host` - IP-адрес, на котором будет запущен веб-сервер

- `port` - Порт веб-сервера

**Пример:**

```
[web_server]
host = 0.0.0.0
port = 5000
```

## Systemd

Настройки поиска системных сервисов

**Параметры:**

- `services_path` - Путь к директории с файлами сервисов systemd

**Пример:**

```
[systemd]
services_path = /home/orangepi/ros2_ws/src/eurus_edu/services
```

Для системных сервисов обычно используется:

`/etc/systemd/system/`

Для пользовательских сервисов:

`/home/<user>/.config/systemd/user/`

## Видео-топики

Настройка ROS-топиков для передачи видеопотоков

**Параметры:**

- `aruco` - Отладочное изображение ArUco-навигации

- `forward_camera` - Поток с передней камеры

- `downward_camera` - Поток с нижней камеры

**Пример:**

```
[video_topics]
aruco = /edu/aruco_debug
forward_camera = /edu/forward_camera
downward_camera = /edu/downward_camera
```

## Пользовательские приложения

Позволяет добавить пользовательские скрипты в панель управления

**Формат записи:**

имя_приложения = /полный/путь/до/скрипта.py

**Пример:**

```
[applications]
example_app = /home/user/example_app.py
test_script = /home/user/test.py
```

## Нейросетевое обнаружение

Параметры модели компьютерного зрения

**Параметры:**

- `model_path` - Путь к директории с нейросетевой моделью.

- `conf_threshold` - Минимальный порог уверенности для обнаружения объекта.

- `camera_topic` - ROS-топик с видеопотоком для обработки.

**Пример:**

```
[neuro]
model_path = ...
conf_threshold = 0.6
camera_topic = /edu/forward_camera
```

## Светодиодная лента

**Параметры:**

Настройки подключения светодиодной ленты

- `amount` - Количество светодиодов.

- `channel` - Используемый канал управления.

- `port` - Номер порта подключения.

- `speed` - Скорость передачи данных.

**Пример:**

```
[led]
amount = 50
channel = 4
port = 1
speed = 3200000
```

## Лазертаг

Лазерная пушка

**Параметры:**

- `shot_pin` - GPIO-пин для выстрела

- `shots_per_command` - Количество выстрелов за одну команду

**Пример:**

[laser_gun]
shot_pin = 138
shots_per_command = 5

## Контроллер попаданий

**Параметры:**

- `hit_pin` - GPIO-пин датчика попадания

- `hit_color` - Цвет индикации попадания в формате RGB

- `led_brightness` - Яркость светодиодов при попадании

- `hit_blinking_speed` - Скорость мигания индикации

- `nled` - Количество используемых светодиодов

Пример:

```
[hit_controller]
hit_pin = 139
hit_color = 255 255 255
led_brightness = 0.3
hit_blinking_speed = 0.3
nled = 45
```
