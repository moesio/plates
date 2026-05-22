ffmpeg \
  -re \
  -stream_loop -1 \
  -framerate 0.5 \
  -pattern_type glob \
  -i "../dataset/*.jpg" \
  -vf "scale=1280:720,format=yuv420p,rotate=0.03*sin(t)" \
  -pix_fmt yuv420p \
  -f v4l2 /dev/video10