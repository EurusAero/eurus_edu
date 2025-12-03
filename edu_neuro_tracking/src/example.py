import cv2
import os
import time
from ultralytics import YOLO

def process_video(source, model_path, output_folder="output_videos"):
    # 1. Загружаем модель
    model = YOLO(model_path)

    # 2. Открываем источник видео
    # Если нужно видео из файла: укажите путь, например "video.mp4"
    # Если нужна веб-камера: укажите индекс, обычно 0
    cap = cv2.VideoCapture(source)

    if not cap.isOpened():
        print("Ошибка: Не удалось открыть видео.")
        return

    # Получаем параметры видеопотока
    fps = int(cap.get(cv2.CAP_PROP_FPS))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # Если FPS не удалось определить (иногда бывает с потоками), ставим по умолчанию 30
    if fps == 0:
        fps = 30

    # Создаем папку для сохранения, если её нет
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # Настройки для разбивки видео
    frames_per_chunk = fps * 60  # Количество кадров в 1 минуте
    chunk_index = 1
    frames_processed = 0
    
    writer = None

    print(f"Начало обработки. FPS: {fps}, Размер: {width}x{height}")
    print("Нажмите 'q' для остановки.")

    while True:
        ret, frame = cap.read()
        if not ret:
            break  # Конец видеопотока

        # --- ОБРАБОТКА НЕЙРОНКОЙ ---
        # stream=True экономит память при обработке видео
        results = model.predict(frame, verbose=False)
        
        # results[0].plot() возвращает кадр с уже нарисованными квадратами
        annotated_frame = results[0].plot()
        # ---------------------------

        # --- ЛОГИКА ЗАПИСИ ВИДЕО (по 1 минуте) ---
        # Если writer еще не создан или прошла минута -> создаем новый файл
        if writer is None:
            output_filename = os.path.join(output_folder, f"video_part_{chunk_index}.mp4")
            # Кодек mp4v для формата mp4
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            writer = cv2.VideoWriter(output_filename, fourcc, fps, (width, height))
            print(f"Запись файла: {output_filename}")

        # Записываем обработанный кадр
        writer.write(annotated_frame)
        frames_processed += 1

        # Если набрали кадров на 1 минуту
        if frames_processed >= frames_per_chunk:
            writer.release() # Закрываем текущий файл
            writer = None    # Сбрасываем writer, чтобы создать новый на следующем круге
            frames_processed = 0
            chunk_index += 1
        # ----------------------------------------

        # (Опционально) Показать окно с процессом
        # cv2.imshow("YOLO Processing", annotated_frame)
        # if cv2.waitKey(1) & 0xFF == ord('q'):
        #     break

    # Очистка ресурсов
    if writer is not None:
        writer.release()
    cap.release()
    cv2.destroyAllWindows()
    print("Обработка завершена.")

# --- ЗАПУСК ---
if __name__ == "__main__":
    # Укажите путь к вашей модели
    my_model = "./model/best.pt"
    
    # Укажите источник:
    # 0 - веб-камера
    # "./input_video.mp4" - видеофайл
    video_source = "./input_video.mp4" # Замените на 0 для веб-камеры

    process_video(video_source, my_model)