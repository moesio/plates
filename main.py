import cv2
from fast_alpr import ALPR

alpr = ALPR()

cap = cv2.VideoCapture(10)

while True:
    ret, frame = cap.read()

    if not ret:
        break

    results = alpr.predict(frame)

    for result in results:
        x1, y1, x2, y2 = result.detection.bounding_box
        text = result.ocr.text

        cv2.rectangle(
            frame,
            (int(x1), int(y1)),
            (int(x2), int(y2)),
            (0, 255, 0),
            2
        )

        cv2.putText(
            frame,
            text,
            (int(x1), int(y1) - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0),
            2
        )

    cv2.imshow("ALPR", frame)

    if cv2.waitKey(1) == 27:
        break

cap.release()
cv2.destroyAllWindows()