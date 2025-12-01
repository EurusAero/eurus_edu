INSTALLATION

```bash
colcon build --packages-select eurus_msgs
source install/setup.bash
```

Проверка наличия сообщений

```bash
ros2 interface show eurus_msgs/msg/Command
```

Должно вывести

```bash
float64 timestamp
string command
string data
string status
```
