# usar ip webcam no celular
# a url padrão é  rtsp://192.168.1.100:8080/h264_ulaw.sdp, podendo mudar o ip

# a visualização do servidor rtsp pode ser feito assim:
# $ ffplay rtsp://192.168.1.100:8080/h264_ulaw.sdp

# Para criar uma câmara IP no computador a partir de uma virtual câmera mostrando um ou mais arquivos de iagens de placa

# 1. Rodar o servidor rtsp mediamtx
mkdir ~/workspace/mediamtx
cd ~/workspace/mediamtx
docker run --rm -it -p 8554:8554 -p 8888:8888 bluenviron/mediamtx

# 2. Start da câmera virtual no OBS

# 3. FFmpeg lendo a virtualcam e publicando no servidor RTSP
ffmpeg -f v4l2 -framerate 30 -video_size 1280x720 -i /dev/video10 -c:v libx264 -preset ultrafast -tune zerolatency -pix_fmt yuv420p -rtsp_transport tcp -f rtsp rtsp://localhost:8554/webca

