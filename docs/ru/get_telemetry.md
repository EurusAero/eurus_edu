# Получение телеметрии

**Подключение:**

```python
drone.request_telemetry()
```

**Возвращаемые значения:**

- none - не удалось получить телеметрию
- Telemetry data - телеметрия получена

​
**Структура telemetry_data:**

_state_

- `connected` — есть ли соединение
- `armed` — состояние моторов
- `mode` — текущий режим
- `system_status` — состояние системы

_battery_

- `voltage` - напряжение (В)
- `cell_voltage` - напряжение на одну ячейку (В)
- `current` - ток (А)
- `percentage` — заряд (%)

_local_position_

- `x, y, z` - позиция (м)
- `roll, pitch, yaw` - углы (градусы)

_velocity_

- `vx, vy, vz`- скорости (м/с)

_point_reached_

- `True` - целевая точка достигнута
- `False` - целевая точка не достигнута

**Пример получения телеметрии на Python:**

```python​
telemetry = drone.request_telemetry() # Запрашиваем телеметрию
​
​
if telemetry is not None:
​
    print("Высота:", telemetry["local_position"]["z"]) # Теущая высота
​
    print("Заряд батареи:", telemetry["battery"]["percentage"], "%") # Уровень заряда батареи
```
