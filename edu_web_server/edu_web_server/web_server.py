import threading
import time
import subprocess
import os
from flask import Flask, Response, render_template_string, request, redirect, url_for
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import CompressedImage

# ================= CONFIG =================

SERVICES = [
    "edu_mavros.service",
    "edu_api_server.service"
]

VIDEO_TOPICS = {
    "aruco": "/edu/aruco_debug"
}

APPLICATIONS = {
    "example_app": "/home/user/example_app.py"
}

# ==========================================

app = Flask(__name__)

current_frames = {}
frame_lock = threading.Lock()


# ================= ROS VIDEO NODE =================

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
            self.get_logger().info(f'Подписка на топик "{topic}" создана.')

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


# ================= SYSTEMD FUNCTIONS =================

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


# ================= APPLICATION CONTROL =================

def run_application(path):
    subprocess.Popen(["python3", path])


# ================= ROUTES =================

@app.route('/')
def index():
    return render_template_string("""
    <h1>ROS Web Control Panel</h1>
    <ul>
        <li><a href="/services">Сервисы</a></li>
        <li><a href="/videos">Видео топики</a></li>
        <li><a href="/apps">Приложения</a></li>
    </ul>
    """)


# ---------- SERVICES ----------

@app.route('/services')
def services():
    service_data = [(s, get_service_status(s)) for s in SERVICES]

    return render_template_string("""
    <h2>Сервисы</h2>
    <a href="/">Назад</a>
    <table border="1" cellpadding="10">
        <tr>
            <th>Сервис</th>
            <th>Статус</th>
            <th>Действия</th>
        </tr>
        {% for service, status in services %}
        <tr>
            <td>{{service}}</td>
            <td>{{status}}</td>
            <td>
                <a href="/service/{{service}}/start">Включить</a>
                <a href="/service/{{service}}/stop">Выключить</a>
                <a href="/service/{{service}}/log">Лог</a>
            </td>
        </tr>
        {% endfor %}
    </table>
    """, services=service_data)


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
    <pre style="background:black;color:lime;padding:10px;">
{{log}}
    </pre>
    """, service=service, log=log)


# ---------- VIDEO ----------

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

    return f"""
    <h2>Видео: {topic_name}</h2>
    <a href="/videos">Назад</a><br><br>
    <img src="/stream/{topic_name}" width="800">
    """


@app.route('/stream/<topic_name>')
def stream(topic_name):
    return Response(generate_frames(topic_name),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


# ---------- APPLICATIONS ----------

@app.route('/apps')
def apps():
    return render_template_string("""
    <h2>Приложения</h2>
    <a href="/">Назад</a>
    <table border="1" cellpadding="10">
        <tr>
            <th>Название</th>
            <th>Действие</th>
        </tr>
        {% for name in apps %}
        <tr>
            <td>{{name}}</td>
            <td>
                <a href="/app/run/{{name}}">Запустить</a>
            </td>
        </tr>
        {% endfor %}
    </table>
    """, apps=APPLICATIONS.keys())


@app.route('/app/run/<name>')
def run_app(name):
    if name in APPLICATIONS:
        run_application(APPLICATIONS[name])
    return redirect(url_for('apps'))


# ================= MAIN =================

def start_flask_app():
    app.run(host='0.0.0.0', port=5000, threaded=True, debug=False, use_reloader=False)


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