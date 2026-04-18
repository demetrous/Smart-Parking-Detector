FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    procps \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY detector ./detector
COPY draw_slots.py slots.example.json ./

RUN python -c "import json; from pathlib import Path; path = Path('/app/slots.json'); data = json.loads(Path('/app/slots.example.json').read_text(encoding='utf-8')); data['backend_url'] = 'http://backend:8000'; path.write_text(json.dumps(data, indent=2), encoding='utf-8')"
RUN python -c "import cv2, numpy as np; fourcc = cv2.VideoWriter_fourcc(*'mp4v'); out = cv2.VideoWriter('/app/sample.mp4', fourcc, 10.0, (640, 480)); frame = np.zeros((480, 640, 3), dtype=np.uint8); [out.write(frame) for _ in range(30)]; out.release()"

CMD ["sh", "-c", "while true; do python -m detector.main --config /app/slots.json --source /app/sample.mp4; sleep 1; done"]
