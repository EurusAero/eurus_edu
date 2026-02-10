import threading
import time
from flask import Flask, Response
import numpy as np
import cv2

# Библиотеки ROS 2
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import CompressedImage

app = Flask(__name__)

current_frame = None
frame_lock = threading.Lock()

class VideoSubscriber(Node):
    def __init__(self):
        super().__init__('web_video_server')
        
        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )

        self.subscription = self.create_subscription(
            CompressedImage,
            '/edu/aruco_debug',
            self.listener_callback,
            qos_profile
        )
        self.get_logger().info('Подписка на топик "aruco_debug" создана.')

    def listener_callback(self, msg):
        global current_frame
        with frame_lock:
            current_frame = bytes(msg.data)


def generate_frames():
    global current_frame
    fps = 30
    frame_time = 1 / fps
    while True:
        start_time = time.time()
        with frame_lock:
            if current_frame is None:
                frame_data = None
            else:
                frame_data = current_frame
        
        if frame_data is not None:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n')
        
        delta_time = time.time() - start_time
        
        time.sleep(max(frame_time - delta_time, 0))

@app.route('/')
def index():
    """Простая HTML страница с ссылкой"""
    html = """
    <html>
        <head>
        </head>
        <body>
            <div class="link-box">
                <a href="/aruco">Aruco debug /aruco</a>
            </div>
        </body>
    </html>
    """
    return html

@app.route('/aruco')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

def start_flask_app():
    app.run(host='0.0.0.0', port=5000, threaded=True, debug=False, use_reloader=False)


def main(args=None):
    rclpy.init(args=args)

    video_subscriber = VideoSubscriber()

    flask_thread = threading.Thread(target=start_flask_app)
    flask_thread.daemon = True
    flask_thread.start()

    try:
        rclpy.spin(video_subscriber)
    except KeyboardInterrupt:
        pass
    finally:
        video_subscriber.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
