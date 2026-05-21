import cv2
import numpy as np
from fast_alpr import ALPR

# Inicializa ALPR
alpr = ALPR(
    detector_model="yolo-v9-t-384-license-plate-end2end",
    ocr_model="cct-xs-v1-global-model",
)

cap = cv2.VideoCapture(10)

# resolução maior
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)


def preprocess(frame):

    # upscale
    frame = cv2.resize(
        frame,
        None,
        fx=1.5,
        fy=1.5,
        interpolation=cv2.INTER_CUBIC
    )

    # melhora contraste
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)

    l, a, b = cv2.split(lab)

    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8)
    )

    cl = clahe.apply(l)

    limg = cv2.merge((cl, a, b))

    frame = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)

    return frame


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


while True:

    ret, frame = cap.read()

    if not ret:
        break

    display = frame.copy()

    processed = preprocess(frame)

    results = []

    # tentativa frontal normal
    try:
        results = alpr.predict(processed)
    except Exception as e:
        print(e)

    # fallback: pequenas rotações
    if not results:

        for angle in (-10, 10):

            try:
                rotated = rotate_image(processed, angle)

                results = alpr.predict(rotated)

                if results:
                    break

            except Exception:
                pass

    # desenha
    for result in results:

        try:
            x1, y1, x2, y2 = result.detection.bounding_box

            # compensar upscale 1.5x
            x1 /= 1.5
            y1 /= 1.5
            x2 /= 1.5
            y2 /= 1.5

            text = result.ocr.text
            conf = result.ocr.confidence

            if conf < 0.55:
                continue

            cv2.rectangle(
                display,
                (int(x1), int(y1)),
                (int(x2), int(y2)),
                (0, 255, 0),
                2
            )

            cv2.putText(
                display,
                f"{text} {conf:.2f}",
                (int(x1), int(y1) - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2
            )

            print(text, conf)

        except Exception:
            pass

    cv2.imshow("ALPR", display)

    if cv2.waitKey(1) == 27:
        break

cap.release()
cv2.destroyAllWindows()