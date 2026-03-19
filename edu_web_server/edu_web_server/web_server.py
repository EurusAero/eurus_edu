import threading
import time
import subprocess
import os
import configparser
from flask import Flask, Response, render_template_string, redirect, url_for
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import CompressedImage
from std_srvs.srv import Trigger

config = configparser.ConfigParser()
home_dir = os.getenv("HOME")
config_path = f"{home_dir}/ros2_ws/src/eurus_edu/edu_web_server/eurus.ini" 
config.read(config_path)

HOST = '0.0.0.0'
PORT = 5000
SERVICES = []
VIDEO_TOPICS = {}
APPLICATIONS = {}

if config.has_section('web_server'):
    HOST = config['web_server'].get('host', HOST)
    PORT = config['web_server'].getint('port', PORT)

if config.has_section('video_topics'):
    for key, value in config.items('video_topics'):
        VIDEO_TOPICS[key] = value

if config.has_section('applications'):
    for key, value in config.items('applications'):
        APPLICATIONS[key] = value

if config.has_section('systemd'):
    services_path = config['systemd'].get('services_path', '/etc/systemd/system/')
    if os.path.exists(services_path):
        for file in os.listdir(services_path):
            if file.endswith('.service'):
                SERVICES.append(file)
        SERVICES.sort()
    else:
        print(f"[WARN] Путь к systemd сервисам не найден: {services_path}")

app = Flask(__name__)

current_frames = {}
frame_lock = threading.Lock()


class MultiVideoSubscriber(Node):
    def __init__(self):
        super().__init__('web_video_server_multi')

        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )

        for name, topic in VIDEO_TOPICS.items():
            self.create_subscription(
                CompressedImage,
                topic,
                lambda msg, topic_name=name: self.listener_callback(msg, topic_name),
                qos_profile
            )
            self.get_logger().info(f'Подписка на топик "{topic}" (имя: {name}) создана.')

    def listener_callback(self, msg, topic_name):
        with frame_lock:
            current_frames[topic_name] = bytes(msg.data)


def generate_frames(topic_name):
    fps = 30
    frame_time = 1 / fps
    while True:
        start_time = time.time()

        with frame_lock:
            frame_data = current_frames.get(topic_name)

        if frame_data is not None:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n')

        delta_time = time.time() - start_time
        time.sleep(max(frame_time - delta_time, 0))


def get_service_status(service):
    result = subprocess.run(
        ["systemctl", "is-active", service],
        capture_output=True,
        text=True
    )
    return result.stdout.strip()


def control_service(service, action):
    subprocess.run(["systemctl", action, service])


def get_service_log(service):
    result = subprocess.run(
        ["journalctl", "-u", service, "-n", "50", "--no-pager"],
        capture_output=True,
        text=True
    )
    return result.stdout


def run_application(path):
    subprocess.Popen(["python3", path])


@app.route('/')
def index():
    return render_template_string("""
    <h1>ROS Web Control Panel</h1>
    <ul>
        <li><a href="/services">Сервисы</a></li>
        <li><a href="/videos">Видео топики</a></li>
        <li><a href="/apps">Приложения</a></li>
        <li><a href="/map_snapshot">Снапшот ArUco карты</a></li> <!-- ДОБАВЛЕНА ССЫЛКА -->
    </ul>
    """)


@app.route('/map_snapshot')
def map_snapshot():
    try:
        node_name = f'web_aruco_snapshot_client_{int(time.time() * 1000)}'
        
        temp_node = rclpy.create_node(node_name, enable_rosout=False)
        client = temp_node.create_client(Trigger, '/edu/get_aruco_board_snapshot')

        if not client.wait_for_service(timeout_sec=3.0):
            temp_node.destroy_node()
            return """
            <h2>Ошибка</h2>
            <p>Сервис /edu/get_aruco_board_snapshot недоступен. Убедитесь, что узел aruco_detection запущен.</p>
            <a href="/">Назад</a>
            """

        req = Trigger.Request()
        future = client.call_async(req)
        
        rclpy.spin_until_future_complete(temp_node, future)
        response = future.result()
        
        temp_node.destroy_node()

        if response is not None and response.success:
            base64_img = response.message
            
            return render_template_string("""
            <h2>Снапшот ArUco карты</h2>
            <a href="/">Назад</a><br><br>
            <div style="margin-top: 20px;">
                <img src="data:image/jpeg;base64,{{ img_data }}" style="max-width: 90%; max-height: 80vh; border: 2px solid black; box-shadow: 5px 5px 15px rgba(0,0,0,0.3);">
            </div>
            """, img_data=base64_img)
        else:
            error_msg = response.message if response else "Неизвестная ошибка"
            return f"<h2>Ошибка генерации карты</h2><p>{error_msg}</p><a href='/'>Назад</a>"

    except Exception as e:
        return f"<h2>Внутренняя ошибка сервера</h2><p>{str(e)}</p><a href='/'>Назад</a>"


@app.route('/services')
def services():
    service_data = [(s, get_service_status(s)) for s in SERVICES]

    return render_template_string("""
    <h2>Сервисы (Найдено: {{ count }})</h2>
    <a href="/">Назад</a>
    <table border="1" cellpadding="10" style="margin-top: 10px; border-collapse: collapse;">
        <tr style="background-color: #f2f2f2;">
            <th>Сервис</th>
            <th>Статус</th>
            <th>Действия</th>
        </tr>
        {% for service, status in services %}
        <tr>
            <td>{{service}}</td>
            <td style="color: {% if status == 'active' %}green{% else %}red{% endif %}; font-weight: bold;">
                {{status}}
            </td>
            <td>
                <a href="/service/{{service}}/start">[Включить]</a>
                <a href="/service/{{service}}/stop">[Выключить]</a>
                <a href="/service/{{service}}/restart">[Рестарт]</a>
                <a href="/service/{{service}}/log">[Лог]</a>
            </td>
        </tr>
        {% endfor %}
    </table>
    """, services=service_data, count=len(service_data))


@app.route('/service/<service>/<action>')
def service_action(service, action):
    if service in SERVICES and action in ["start", "stop", "restart"]:
        control_service(service, action)
    return redirect(url_for('services'))


@app.route('/service/<service>/log')
def service_log(service):
    if service in SERVICES:
        log = get_service_log(service)
    else:
        log = "Сервис не найден"

    return render_template_string("""
    <h2>Лог {{service}}</h2>
    <a href="/services">Назад</a>
    <pre style="background:black;color:lime;padding:10px;overflow-x:auto;">
{{log}}
    </pre>
    """, service=service, log=log)


@app.route('/videos')
def videos():
    return render_template_string("""
    <h2>Видео топики</h2>
    <a href="/">Назад</a>
    <ul>
    {% for name in topics %}
        <li><a href="/video/{{name}}">{{name}}</a></li>
    {% endfor %}
    </ul>
    """, topics=VIDEO_TOPICS.keys())


@app.route('/video/<topic_name>')
def video_page(topic_name):
    if topic_name not in VIDEO_TOPICS:
        return "Топик не найден"

    return render_template_string("""
    <h2>Видео: {{ topic_name }}</h2>
    <a href="/videos">Назад</a><br><br>
    <img src="/stream/{{ topic_name }}" width="800" style="border: 1px solid black;">
    """, topic_name=topic_name)


@app.route('/stream/<topic_name>')
def stream(topic_name):
    return Response(generate_frames(topic_name),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/apps')
def apps():
    return render_template_string("""
    <h2>Приложения</h2>
    <a href="/">Назад</a>
    <table border="1" cellpadding="10" style="margin-top: 10px; border-collapse: collapse;">
        <tr style="background-color: #f2f2f2;">
            <th>Название</th>
            <th>Путь</th>
            <th>Действие</th>
        </tr>
        {% for name, path in apps.items() %}
        <tr>
            <td>{{name}}</td>
            <td><small>{{path}}</small></td>
            <td>
                <a href="/app/run/{{name}}">[Запустить]</a>
            </td>
        </tr>
        {% endfor %}
    </table>
    """, apps=APPLICATIONS)


@app.route('/app/run/<name>')
def run_app(name):
    if name in APPLICATIONS:
        run_application(APPLICATIONS[name])
    return redirect(url_for('apps'))



def start_flask_app():
    print(f"Запуск Web-сервера на {HOST}:{PORT}")
    app.run(host=HOST, port=PORT, threaded=True, debug=False, use_reloader=False)


def main(args=None):
    rclpy.init(args=args)

    video_node = MultiVideoSubscriber()

    flask_thread = threading.Thread(target=start_flask_app)
    flask_thread.daemon = True
    flask_thread.start()

    try:
        rclpy.spin(video_node)
    except KeyboardInterrupt:
        pass
    finally:
        video_node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()