import cv2
import time
from EurusEdu import EurusCamera

def main():
    cam = EurusCamera("10.42.0.1", 8001)

    try:
        cam.connect()

        cam.start_stream()
        time.sleep(1)

        while True:
            ret, frame = cam.read()
            if ret:
                cv2.imshow("Drone Feed", frame)
        
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
                
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        cam.stop_stream()
        cam.disconnect()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()