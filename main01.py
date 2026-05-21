import cv2
import numpy as np
from fast_alpr import ALPR

# Inicializa ALPR
alpr = ALPR(
    detector_model="yolo-v9-t-384-license-plate-end2end",
    ocr_model="cct-xs-v1-global-model",
)

# Webcam
cap = cv2.VideoCapture(10)

# Tenta aumentar resolução
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

# Ângulos para testar
angles = [-15, -10, -5, 0, 5, 10, 15]


def rotate_image(image, angle):
    h, w = image.shape[:2]

    center = (w // 2, h // 2)

    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)

    rotated = cv2.warpAffine(
        image,
        matrix,
        (w, h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE
    )

    return rotated


def enhance(image):
    # Sharpen
    kernel = np.array([
        [0, -1, 0],
        [-1, 5, -1],
        [0, -1, 0]
    ])

    sharp = cv2.filter2D(image, -1, kernel)

    return sharp


while True:

    ret, frame = cap.read()

    if not ret:
        break

    best_results = []

    # Melhoria de nitidez
    enhanced = enhance(frame)

    # Testa várias rotações
    for angle in angles:

        rotated = rotate_image(enhanced, angle)

        try:
            results = alpr.predict(rotated)

            if results:
                best_results.extend(results)

        except Exception as e:
            print(e)

    # Desenha resultados
    for result in best_results:

        try:
            x1, y1, x2, y2 = result.detection.bounding_box

            text = result.ocr.text
            conf = result.ocr.confidence

            if conf < 0.5:
                continue

            cv2.rectangle(
                frame,
                (int(x1), int(y1)),
                (int(x2), int(y2)),
                (0, 255, 0),
                2
            )

            cv2.putText(
                frame,
                f"{text} ({conf:.2f})",
                (int(x1), int(y1) - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2
            )

            print(text, conf)

        except Exception:
            pass

    cv2.imshow("ALPR", frame)

    key = cv2.waitKey(1)

    if key == 27:
        break

cap.release()
cv2.destroyAllWindows()