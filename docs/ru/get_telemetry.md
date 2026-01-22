# Получение телеметрии


**Подключение:**

``` python
request_telemetry()
```

**Возвращаемые значения:**

-   none - не удалось получить телеметрию
-   Telemetry data - телеметрия получена

​
**Структура telemetry_data:**

state

-   telemetry_data["state"]["connected"] = self.state_msg.connected
-   telemetry_data["state"]["armed"] = self.state_msg.armed
-   telemetry_data["state"]["mode"] = self.state_msg.mode
-   telemetry_data["state"]["system_status"] = self.state_msg.system_status

battery (данные о заряде)

-   telemetry_data["battery"]["voltage"] = self.battery_msg.voltage
-   telemetry_data["battery"]["cell_voltage"] = list(self.battery_msg.cell_voltage)
-   telemetry_data["battery"]["current"] = self.battery_msg.current
-   telemetry_data["battery"]["percentage"] = int(self.battery_msg.percentage * 100)

local_position

-   telemetry_data["local_position"]["x"] = pose.x
-   telemetry_data["local_position"]["y"] = pose.y
-   telemetry_data["local_position"]["z"] = pose.z
-   telemetry_data["local_position"]["roll"] = degrees(orientation_angles[0])
-   telemetry_data["local_position"]["pitch"] = degrees(orientation_angles[1])
-   telemetry_data["local_position"]["yaw"] = degrees(orientation_angles[2])

setpoint_local

-   telemetry_data["setpoint_local"]["x"] = setpoint_pose.x
-   telemetry_data["setpoint_local"]["y"] = setpoint_pose.y
-   telemetry_data["setpoint_local"]["z"] = setpoint_pose.z
-   telemetry_data["setpoint_local"]["yaw"] = degrees(setpoint_orientation_angles[2])

velocity

-   telemetry_data["velocity"]["vx"] = velocity.x
-   telemetry_data["velocity"]["vy"] = velocity.y
-   telemetry_data["velocity"]["vz"] = velocity.z

point_reached

-   telemetry_data["point_reached"] = point_reached (bool)


**Пример получения телеметрии на Python:**

``` python​
telemetry = drone.request_telemetry() # Запрашиваем телеметрию
​
​
if telemetry is not None:
​
    print("Высота:", telemetry["local_position"]["z"]) # Теущая высота
​
    print("Заряд батареи:", telemetry["battery"]["percentage"], "%") # Уровень заряда батареи
```