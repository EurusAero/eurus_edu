import rclpy
from rclpy.node import Node
import json
import threading
import time

from mavros_msgs.srv import CommandBool, CommandTOL, SetMode
from eurus_msgs.msg import Command
from EurusEdu.const import *


class MavrosHandler(Node):
    def __init__(self):
        super().__init__("edu_commander")
        
        self.arming_client = self.create_client(CommandBool, '/mavros/cmd/arming')
        self.set_mode_client = self.create_client(SetMode, '/mavros/set_mode')
        self.takeoff_client = self.create_client(CommandTOL, '/mavros/cmd/takeoff')
        self.land_client = self.create_client(CommandTOL, '/mavros/cmd/land')
        
        self._wait_for_services()

        self.cmd_sub = self.create_subscription(
            Command,
            'eurus/command',
            self.command_callback,
            10
        )

        self.status_pub = self.create_publisher(Command, 'eurus/command', 10)
        
        self.current_task_thread = None
        self.get_logger().info("MavrosHandler готов к работе.")

    def _wait_for_services(self):
        """Ждем доступности сервисов MAVROS при запуске."""
        self.get_logger().info("Ожидание сервисов MAVROS...")
        if not self.arming_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().warn("Сервис arming не найден!")
        if not self.set_mode_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().warn("Сервис set_mode не найден!")
        if not self.takeoff_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().warn("Сервис takeoff не найден!")
        self.get_logger().info("Сервисы MAVROS найдены (или таймаут).")

    def publish_status(self, original_msg, status, message=""):
        """Отправка статуса обратно в API сервер."""
        reply = Command()
        reply.timestamp = original_msg.timestamp
        reply.command = original_msg.command
        reply.status = status
        reply.data = message
        
        self.status_pub.publish(reply)
        self.get_logger().info(f"Статус команды '{original_msg.command}': {status}")

    def command_callback(self, msg: Command):
        """Обработка входящего сообщения из eurus/command."""
        if msg.status != PENDING_STATUS:
            return

        self.get_logger().info(f"Получена команда: {msg.command}")

        if self.current_task_thread and self.current_task_thread.is_alive():
            self.publish_status(msg, DENIED_STATUS, "Mavros handler is busy")
            return

        self.current_task_thread = threading.Thread(
            target=self.execute_command_logic,
            args=(msg,),
            daemon=True
        )
        self.current_task_thread.start()

    def execute_command_logic(self, msg: Command):
        """Логика выполнения команд (запускается в потоке)."""
        
        self.publish_status(msg, RUNNING_STATUS)
        
        cmd_name = msg.command
        data = {}
        try:
            if msg.data:
                data = json.loads(msg.data)
        except json.JSONDecodeError:
            self.publish_status(msg, DENIED_STATUS, "Invalid JSON data")
            return

        success = False
        error_msg = ""

        try:
            if cmd_name == "arm":
                success, error_msg = self.do_arm()
            elif cmd_name == "disarm":
                success, error_msg = self.do_disarm()
            elif cmd_name == "takeoff":
                altitude = data.get("altitude", 2.0)
                success, error_msg = self.do_takeoff(altitude)
            elif cmd_name == "land":
                success, error_msg = self.do_land()
            elif cmd_name == "set_mode":
                mode = data.get("mode", "OFFBOARD")
                success, error_msg = self.do_set_mode(mode)
            else:
                success = False
                
                error_msg = f"Unknown command: {cmd_name}"

        except Exception as e:
            success = False
            error_msg = str(e)
            self.get_logger().error(f"Exception during execution: {e}")

        # 2. Сообщаем результат
        final_status = COMPLETED_STATUS if success else DENIED_STATUS
        self.publish_status(msg, final_status, error_msg)


    # --- MAVROS ACTION WRAPPERS ---

    def _call_service_sync(self, client, request):
        """Вспомогательный метод для синхронного вызова сервиса из потока."""
        future = client.call_async(request)
        # Ждем завершения future. Так как мы в отдельном потоке, 
        # rclpy.spin в главном потоке обработает ответ.
        while not future.done():
            time.sleep(0.1)
        return future.result()

    def do_set_mode(self, mode="OFFBOARD"):
        req = SetMode.Request()
        req.custom_mode = mode
        res = self._call_service_sync(self.set_mode_client, req)
        if res.mode_sent:
            return True, "Mode sent"
        else:
            return False, f"Mode sent failed: Result {res.result}"

    def do_arm(self):
        mode_sent, err = self.do_set_mode("OFFBOARD")
        if not mode_sent:
            return False, "Failed to set OFFBOARD mode"
        
        req = CommandBool.Request()
        req.value = True
        res = self._call_service_sync(self.arming_client, req)
        
        if res.success:
            return True, "Armed"
        else:
            return False, f"Arming failed: Result {res.result}"

    def do_disarm(self):
        req = CommandBool.Request()
        req.value = False
        res = self._call_service_sync(self.arming_client, req)
        
        if res.success:
            return True, "Disarmed"
        else:
            return False, f"Disarming failed: Result {res.result}"

    def do_takeoff(self, altitude):
        mode_sent, err = self.do_set_mode("OFFBOARD")
        if not mode_sent:
            return False, "Failed to set OFFBOARD mode"
        
        # 2. Arm (на всякий случай, если не заармлен)
        # Примечание: ArduPilot может требовать арминг перед вызовом takeoff
        arm_req = CommandBool.Request()
        arm_req.value = True
        arm_res = self._call_service_sync(self.arming_client, arm_req)
        if not arm_res.success:
            # Иногда дрон уже заармлен, это не всегда ошибка, но стоит проверить
            self.get_logger().warn("Arm command returned false (maybe already armed?)")

        time.sleep(1.0) # Небольшая пауза перед взлетом

        # 3. Takeoff
        req = CommandTOL.Request()
        req.altitude = float(altitude)
        req.latitude = 0.0 # Текущая
        req.longitude = 0.0 # Текущая
        req.min_pitch = 0.0
        req.yaw = 0.0
        
        res = self._call_service_sync(self.takeoff_client, req)
        
        if res.success:
            # Ожидание набора высоты можно реализовать здесь через подписку на телеметрию,
            # но для простоты вернем успех запуска команды.
            return True, "Takeoff initiated"
        else:
            return False, f"Takeoff rejected: Result {res.result}"

    def do_land(self):
        req = CommandTOL.Request()
        # Для посадки координаты обычно 0,0 (садиться здесь)
        req.latitude = 0.0
        req.longitude = 0.0
        
        res = self._call_service_sync(self.land_client, req)
        
        if res.success:
            return True, "Landing initiated"
        else:
            # Альтернативный вариант - переключить режим
            self.get_logger().warn("CommandTOL failed, trying SetMode LAND")
            mode_sent, err = self.do_set_mode("LAND")
            if mode_sent:
                return True, "Landing via SetMode"
            return False, "Landing failed"

def main():
    rclpy.init()
    node = MavrosHandler()
    
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
