sudo apt install python3-pip

sudo apt install python3-pip ffmpeg libsm6 libxext6 cmake -y

pip install ultralytics

sudo reboot

pip install --upgrade setuptools wheel

pip3 install rknn-toolkit2

pip install onnx==1.19.1

sudo reboot

yolo export model=best.pt format=rknn name=rk3588
