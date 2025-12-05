import cv2
import threading
import time
import os
import datetime
from flask import Flask, Response, render_template_string, jsonify

# --- КОНФИГУРАЦИЯ ---
# Индекс камеры. Обычно 0 - встроенная, 1 - внешняя USB (/dev/video1)
# Если у вас точно путь /dev/camera1, попробуйте заменить цифру 1 на строку '/dev/camera1'
CAMERA_SOURCE = 1 
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
FPS = 30.0
VIDEO_FOLDER = "videos"

# Создаем папку для видео, если нет
if not os.path.exists(VIDEO_FOLDER):
    os.makedirs(VIDEO_FOLDER)

# Инициализация Flask
app = Flask(__name__)

class VideoController:
    def __init__(self):
        self.camera = cv2.VideoCapture(CAMERA_SOURCE)
        
        # Настройка разрешения на уровне железа камеры
        self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
        self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        self.camera.set(cv2.CAP_PROP_FPS, FPS)
        
        # Переменные для хранения кадра и синхронизации
        self.lock = threading.Lock()
        self.current_frame = None
        self.jpeg_frame = None
        
        self.is_running = True
        self.is_recording = False
        
        # Запускаем поток захвата изображения с камеры
        self.capture_thread = threading.Thread(target=self._update_camera, daemon=True)
        self.capture_thread.start()

    def _update_camera(self):
        """Фоновый поток: постоянно читает камеру, чтобы не было лагов."""
        while self.is_running:
            ret, frame = self.camera.read()
            if ret:
                with self.lock:
                    self.current_frame = frame.copy()
                    # Кодируем в JPEG заранее для стрима (снижаем нагрузку на http поток)
                    _, buffer = cv2.imencode('.jpg', frame)
                    self.jpeg_frame = buffer.tobytes()
            else:
                # Если камера отвалилась, пробуем переподключиться
                time.sleep(0.1)

    def start_recording(self):
        """Запускает поток записи видео."""
        if self.is_recording:
            return {"status": "already_recording"}
        
        self.is_recording = True
        self.record_thread = threading.Thread(target=self._record_video, daemon=True)
        self.record_thread.start()
        return {"status": "started"}

    def stop_recording(self):
        """Останавливает запись."""
        if not self.is_recording:
            return {"status": "not_recording"}
        
        self.is_recording = False
        return {"status": "stopped"}

    def _record_video(self):
        """Логика записи видео в файл."""
        filename = datetime.datetime.now().strftime("rec_%Y-%m-%d_%H-%M-%S.avi")
        filepath = os.path.join(VIDEO_FOLDER, filename)
        
        # Кодек XVID (avi) или mp4v (mp4)
        fourcc = cv2.VideoWriter_fourcc(*'XVID')
        out = cv2.VideoWriter(filepath, fourcc, FPS, (FRAME_WIDTH, FRAME_HEIGHT))
        
        print(f"[REC] Начата запись: {filepath}")
        
        # Контроль времени для стабильных FPS
        frame_duration = 1.0 / FPS
        
        while self.is_recording:
            start_time = time.time()
            
            with self.lock:
                if self.current_frame is not None:
                    # Пишем кадр
                    out.write(self.current_frame)
            
            # Небольшая пауза, чтобы соответствовать FPS и не грузить CPU впустую
            elapsed = time.time() - start_time
            delay = max(0, frame_duration - elapsed)
            time.sleep(delay)
            
        out.release()
        print(f"[REC] Запись завершена: {filepath}")

    def get_jpeg(self):
        """Возвращает байты текущего кадра (безопасно)."""
        with self.lock:
            return self.jpeg_frame

    def release(self):
        self.is_running = False
        self.camera.release()


# Глобальный объект контроллера
video_controller = VideoController()


# --- ВЕБ МАРШРУТЫ ---

@app.route('/')
def index():
    # Простой HTML интерфейс
    return render_template_string('''
    <html>
        <head>
            <title>Camera Stream</title>
            <style>
                body { font-family: sans-serif; text-align: center; background: #222; color: #fff; }
                h1 { margin-top: 20px; }
                img { border: 2px solid #555; max-width: 100%; }
                .controls { margin-top: 20px; }
                button { 
                    padding: 15px 30px; font-size: 18px; cursor: pointer; 
                    border: none; border-radius: 5px; color: white; margin: 10px;
                }
                .btn-start { background-color: #28a745; }
                .btn-stop { background-color: #dc3545; }
                #status { margin-top: 10px; font-weight: bold; color: #ffd700; }
            </style>
        </head>
        <body>
            <h1>IP Camera Recorder</h1>
            <div>
                <img src="{{ url_for('video_feed') }}">
            </div>
            <div class="controls">
                <button class="btn-start" onclick="control('start')">Начать запись</button>
                <button class="btn-stop" onclick="control('stop')">Остановить</button>
            </div>
            <div id="status">Ожидание...</div>

            <script>
                function control(action) {
                    let url = action === 'start' ? '/start_recording' : '/stop_recording';
                    fetch(url)
                        .then(response => response.json())
                        .then(data => {
                            document.getElementById('status').innerText = "Статус: " + data.status;
                            console.log(data);
                        })
                        .catch(err => console.error(err));
                }
            </script>
        </body>
    </html>
    ''')

def generate_frames():
    """Генератор потока для браузера."""
    while True:
        frame_bytes = video_controller.get_jpeg()
        if frame_bytes:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        else:
            time.sleep(0.1)

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/start_recording')
def start_recording():
    res = video_controller.start_recording()
    return jsonify(res)

@app.route('/stop_recording')
def stop_recording():
    res = video_controller.stop_recording()
    return jsonify(res)

if __name__ == '__main__':
    try:
        # host='0.0.0.0' делает сервер доступным в локальной сети
        # threaded=True позволяет обрабатывать несколько запросов одновременно
        print(f"Сервер запущен. Откройте в браузере http://<IP_ADDRESS>:5000")
        app.run(host='0.0.0.0', port=5000, threaded=True, debug=False)
    finally:
        video_controller.release()