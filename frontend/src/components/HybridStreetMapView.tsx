import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import clsx from 'clsx';
import ParkingMap from './ParkingMap';
import SimulationView from './SimulationView';
import type { Spot } from '../types';

type MediaMode = 'image' | 'video' | 'synthetic';
type DetectStatus = 'idle' | 'detecting' | 'ready' | 'offline' | 'syncing' | 'synced' | 'error';

type DetectBox = {
  classId: number;
  className: string;
  confidence: number;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
};

type DetectResponse = {
  imageWidth: number;
  imageHeight: number;
  boxes: DetectBox[];
  experimental?: {
    makeModel?: {
      enabled: boolean;
      stage?: string;
      reason?: string;
    };
  };
};

type GeometryLine = {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  length: number;
};

type GeometryResponse = {
  imageWidth: number;
  imageHeight: number;
  lines: GeometryLine[];
};

type CalibrationPoint = {
  id?: string;
  label?: string;
  pixel: [number, number];
  lat: number;
  lng: number;
};

type CalibrationSlot = {
  id: string;
  lat: number;
  lng: number;
  polygon: [number, number][];
};

type ScaleReference = {
  pixelA: [number, number];
  pixelB: [number, number];
  meters: number;
};

type StreetCalibration = {
  schema_version?: number;
  camera_id: string;
  frame_size: [number, number];
  reference_points?: CalibrationPoint[];
  parking_slots?: CalibrationSlot[];
  scale_reference_meters?: ScaleReference;
};

type OccupancyUpdate = {
  id: string;
  lat: number;
  lng: number;
  status: 'available' | 'occupied';
  confidence: number;
};

type MediaLayout = {
  left: number;
  top: number;
  width: number;
  height: number;
};

type Size = {
  width: number;
  height: number;
};

const VEHICLE_CLASS_IDS = new Set([2, 3, 5, 7]);
const DETECTOR_URL = ((import.meta.env.VITE_DETECTOR_URL as string | undefined) ?? 'http://127.0.0.1:8010').replace(/\/$/, '');

function toOverlay(box: DetectBox, imageWidth: number, imageHeight: number, layout: MediaLayout) {
  return {
    left: (box.x1 / imageWidth) * layout.width,
    top: (box.y1 / imageHeight) * layout.height,
    width: ((box.x2 - box.x1) / imageWidth) * layout.width,
    height: ((box.y2 - box.y1) / imageHeight) * layout.height,
  };
}

function slotOverlay(slot: CalibrationSlot, frameSize: [number, number]) {
  const [w, h] = frameSize;
  return slot.polygon.map(([x, y]) => `${(x / w) * 100}% ${(y / h) * 100}%`).join(', ');
}

function containedLayout(stage: Size, media: Size | null): MediaLayout {
  if (!media || stage.width <= 0 || stage.height <= 0 || media.width <= 0 || media.height <= 0) {
    return { left: 0, top: 0, width: stage.width, height: stage.height };
  }
  const scale = Math.min(stage.width / media.width, stage.height / media.height);
  const width = media.width * scale;
  const height = media.height * scale;
  return {
    left: (stage.width - width) / 2,
    top: (stage.height - height) / 2,
    width,
    height,
  };
}

function bboxFromPolygon(polygon: [number, number][]): [number, number, number, number] {
  const xs = polygon.map(([x]) => x);
  const ys = polygon.map(([, y]) => y);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

function iou(a: [number, number, number, number], b: [number, number, number, number]) {
  const ix1 = Math.max(a[0], b[0]);
  const iy1 = Math.max(a[1], b[1]);
  const ix2 = Math.min(a[2], b[2]);
  const iy2 = Math.min(a[3], b[3]);
  const iw = Math.max(0, ix2 - ix1);
  const ih = Math.max(0, iy2 - iy1);
  const inter = iw * ih;
  if (inter === 0) return 0;
  const areaA = (a[2] - a[0]) * (a[3] - a[1]);
  const areaB = (b[2] - b[0]) * (b[3] - b[1]);
  return inter / (areaA + areaB - inter);
}

function vehicleBoxes(result: DetectResponse | null) {
  return result?.boxes.filter((box) => VEHICLE_CLASS_IDS.has(box.classId)) ?? [];
}

function mapPointFromPixel(pixel: [number, number], calibration: StreetCalibration): { lat: number; lng: number } | null {
  const anchors = calibration.reference_points ?? [];
  if (anchors.length === 0) return null;
  const weighted = anchors.reduce(
    (acc, point) => {
      const distance = Math.hypot(pixel[0] - point.pixel[0], pixel[1] - point.pixel[1]);
      const weight = 1 / Math.max(distance, 1) ** 2;
      return {
        weight: acc.weight + weight,
        lat: acc.lat + point.lat * weight,
        lng: acc.lng + point.lng * weight,
      };
    },
    { weight: 0, lat: 0, lng: 0 },
  );
  if (weighted.weight === 0) return null;
  return { lat: weighted.lat / weighted.weight, lng: weighted.lng / weighted.weight };
}

function estimateOccupancy(result: DetectResponse | null, calibration: StreetCalibration | null): OccupancyUpdate[] {
  if (!result || !calibration?.parking_slots?.length) return [];
  const vehicles = vehicleBoxes(result).map((box) => ({
    box,
    bbox: [box.x1, box.y1, box.x2, box.y2] as [number, number, number, number],
  }));
  return calibration.parking_slots.map((slot) => {
    const slotBox = bboxFromPolygon(slot.polygon);
    const best = vehicles.reduce((max, vehicle) => Math.max(max, iou(slotBox, vehicle.bbox)), 0);
    return {
      id: slot.id,
      lat: slot.lat,
      lng: slot.lng,
      status: best >= 0.08 ? 'occupied' : 'available',
      confidence: Number(Math.max(0.5, Math.min(0.99, best || 0.9)).toFixed(3)),
    };
  });
}

function detectedVehicleSpots(result: DetectResponse | null, calibration: StreetCalibration | null): Spot[] {
  if (!result || !calibration?.reference_points?.length) return [];
  const spots: Spot[] = [];
  for (const [index, box] of vehicleBoxes(result).entries()) {
    const groundPoint = mapPointFromPixel([(box.x1 + box.x2) / 2, box.y2], calibration);
    if (groundPoint) {
      spots.push({
        id: `detected-car-${index + 1}`,
        lat: groundPoint.lat,
        lng: groundPoint.lng,
        status: 'occupied' as const,
        confidence: box.confidence,
        updatedAt: new Date().toISOString(),
        cameraId: calibration.camera_id,
      });
    }
  }
  return spots;
}

function distanceSummary(result: DetectResponse | null, calibration: StreetCalibration | null) {
  const vehicles = vehicleBoxes(result);
  if (vehicles.length < 2) return [];
  const scale = calibration?.scale_reference_meters;
  const metersPerPixel = scale
    ? scale.meters / Math.hypot(scale.pixelA[0] - scale.pixelB[0], scale.pixelA[1] - scale.pixelB[1])
    : null;
  return vehicles.slice(0, 4).flatMap((a, i) =>
    vehicles.slice(i + 1, 4).map((b, j) => {
      const ax = (a.x1 + a.x2) / 2;
      const ay = a.y2;
      const bx = (b.x1 + b.x2) / 2;
      const by = b.y2;
      const px = Math.hypot(ax - bx, ay - by);
      return {
        id: `${i}-${j + i + 1}`,
        label: metersPerPixel ? `${(px * metersPerPixel).toFixed(1)} m` : `${Math.round(px)} px`,
      };
    }),
  );
}

async function detectBlob(blob: Blob): Promise<DetectResponse> {
  const response = await fetch(`${DETECTOR_URL}/detect?conf=0.2&include_people=true`, {
    method: 'POST',
    headers: { 'Content-Type': blob.type || 'application/octet-stream' },
    body: blob,
  });
  if (!response.ok) throw new Error(`Detector returned ${response.status}`);
  return response.json();
}

async function detectGeometry(blob: Blob): Promise<GeometryResponse> {
  const response = await fetch(`${DETECTOR_URL}/geometry/lines`, {
    method: 'POST',
    headers: { 'Content-Type': blob.type || 'application/octet-stream' },
    body: blob,
  });
  if (!response.ok) throw new Error(`Geometry returned ${response.status}`);
  return response.json();
}

function canvasToBlob(canvas: HTMLCanvasElement): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.82));
}

export default function HybridStreetMapView() {
  const [topPercent, setTopPercent] = useState(67);
  const [mediaMode, setMediaMode] = useState<MediaMode>('image');
  const [mediaUrl, setMediaUrl] = useState<string | null>(null);
  const [detectResult, setDetectResult] = useState<DetectResponse | null>(null);
  const [geometryResult, setGeometryResult] = useState<GeometryResponse | null>(null);
  const [calibration, setCalibration] = useState<StreetCalibration | null>(null);
  const [status, setStatus] = useState<DetectStatus>('idle');
  const [autoVideo, setAutoVideo] = useState(false);
  const [mediaLayout, setMediaLayout] = useState<MediaLayout>({ left: 0, top: 0, width: 0, height: 0 });
  const [mediaNaturalSize, setMediaNaturalSize] = useState<Size | null>(null);
  const splitRef = useRef<HTMLDivElement | null>(null);
  const mediaStageRef = useRef<HTMLDivElement | null>(null);
  const imageInputRef = useRef<HTMLInputElement | null>(null);
  const videoInputRef = useRef<HTMLInputElement | null>(null);
  const calibrationInputRef = useRef<HTMLInputElement | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const occupancy = useMemo(() => estimateOccupancy(detectResult, calibration), [calibration, detectResult]);
  const detectedSpots = useMemo(() => detectedVehicleSpots(detectResult, calibration), [calibration, detectResult]);
  const distances = useMemo(() => distanceSummary(detectResult, calibration), [calibration, detectResult]);

  useEffect(() => {
    return () => {
      if (mediaUrl) URL.revokeObjectURL(mediaUrl);
    };
  }, [mediaUrl]);

  const replaceMedia = (file: File, mode: MediaMode) => {
    if (mediaUrl) URL.revokeObjectURL(mediaUrl);
    setMediaMode(mode);
    setMediaUrl(URL.createObjectURL(file));
    setDetectResult(null);
    setGeometryResult(null);
    setMediaNaturalSize(null);
    setStatus('idle');
  };

  const updateMediaLayout = useCallback((naturalSize = mediaNaturalSize) => {
    const stage = mediaStageRef.current;
    if (!stage) {
      setMediaLayout({ left: 0, top: 0, width: 0, height: 0 });
      return;
    }
    const stageRect = stage.getBoundingClientRect();
    setMediaLayout(containedLayout({ width: stageRect.width, height: stageRect.height }, naturalSize));
  }, [mediaNaturalSize]);

  const detectImageFile = async (file: File) => {
    replaceMedia(file, 'image');
    setStatus('detecting');
    try {
      setDetectResult(await detectBlob(file));
      setStatus('ready');
    } catch {
      setStatus('offline');
    }
  };

  const detectVideoFrame = async () => {
    const video = videoRef.current;
    if (!video || video.videoWidth === 0 || video.videoHeight === 0) return;
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d')?.drawImage(video, 0, 0, canvas.width, canvas.height);
    const blob = await canvasToBlob(canvas);
    if (!blob) return;
    setStatus('detecting');
    try {
      setDetectResult(await detectBlob(blob));
      setStatus('ready');
    } catch {
      setStatus('offline');
    }
  };

  const currentMediaBlob = async (): Promise<Blob | null> => {
    if (mediaMode === 'video') {
      const video = videoRef.current;
      if (!video || video.videoWidth === 0 || video.videoHeight === 0) return null;
      const canvas = document.createElement('canvas');
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext('2d')?.drawImage(video, 0, 0, canvas.width, canvas.height);
      return canvasToBlob(canvas);
    }
    if (!mediaUrl || mediaMode !== 'image') return null;
    return fetch(mediaUrl).then((response) => response.blob());
  };

  const detectStreetGeometry = async () => {
    const blob = await currentMediaBlob();
    if (!blob) return;
    setStatus('detecting');
    try {
      setGeometryResult(await detectGeometry(blob));
      setStatus('ready');
    } catch {
      setStatus('offline');
    }
  };

  const syncOccupancy = async (updates = occupancy) => {
    if (!calibration || updates.length === 0) return;
    setStatus('syncing');
    try {
      const response = await fetch(`${DETECTOR_URL}/spots/sync`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          cameraId: calibration.camera_id,
          spots: updates,
        }),
      });
      if (!response.ok) throw new Error(`Sync returned ${response.status}`);
      setStatus('synced');
    } catch {
      setStatus('error');
    }
  };

  useEffect(() => {
    if (!autoVideo || mediaMode !== 'video') return;
    const timer = window.setInterval(() => {
      void detectVideoFrame();
    }, 2500);
    return () => window.clearInterval(timer);
  }, [autoVideo, mediaMode]);

  const startDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    const root = splitRef.current;
    if (!root) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const onMove = (moveEvent: PointerEvent) => {
      const rect = root.getBoundingClientRect();
      const next = ((moveEvent.clientY - rect.top) / rect.height) * 100;
      setTopPercent(Math.max(35, Math.min(82, next)));
      window.requestAnimationFrame(() => updateMediaLayout());
    };
    const onUp = () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  };

  useEffect(() => {
    updateMediaLayout();
    const onResize = () => updateMediaLayout();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [mediaMode, mediaUrl, mediaNaturalSize, topPercent, updateMediaLayout]);

  return (
    <div ref={splitRef} className="h-dvh w-full overflow-hidden bg-slate-950">
      <section className="relative overflow-hidden border-b border-slate-800" style={{ height: `${topPercent}%` }}>
        {mediaMode === 'synthetic' ? (
          <SimulationView embedded />
        ) : mediaUrl ? (
          <div ref={mediaStageRef} className="relative h-full w-full bg-black">
              <div
                className="absolute"
                style={{ left: mediaLayout.left, top: mediaLayout.top, width: mediaLayout.width, height: mediaLayout.height }}
              >
              {mediaMode === 'image' ? (
                <img
                  src={mediaUrl}
                  alt="Street reference"
                  className="h-full w-full"
                  onLoad={(event) => {
                    const nextSize = {
                      width: event.currentTarget.naturalWidth,
                      height: event.currentTarget.naturalHeight,
                    };
                    setMediaNaturalSize(nextSize);
                    updateMediaLayout(nextSize);
                  }}
                />
              ) : (
                <video
                  ref={videoRef}
                  src={mediaUrl}
                  className="h-full w-full"
                  controls
                  muted
                  loop
                  playsInline
                  onLoadedMetadata={(event) => {
                    const nextSize = {
                      width: event.currentTarget.videoWidth,
                      height: event.currentTarget.videoHeight,
                    };
                    setMediaNaturalSize(nextSize);
                    updateMediaLayout(nextSize);
                  }}
                />
              )}
              {calibration?.parking_slots?.map((slot) => (
                <div
                  key={slot.id}
                  className="pointer-events-none absolute border-2 border-sky-300/80 bg-sky-300/10 text-xs font-semibold text-white"
                  style={{
                    clipPath: `polygon(${slotOverlay(slot, calibration.frame_size)})`,
                    inset: 0,
                  }}
                >
                  <span className="absolute rounded bg-sky-950/80 px-1.5 py-0.5">{slot.id}</span>
                </div>
              ))}
              {detectResult?.boxes.map((box, index) => (
                <div
                  key={`${box.className}-${index}`}
                  className={clsx(
                    'absolute rounded border-2 bg-black/10 text-xs font-semibold text-white shadow',
                    VEHICLE_CLASS_IDS.has(box.classId) ? 'border-lime-300' : 'border-amber-300',
                  )}
                  style={toOverlay(box, detectResult.imageWidth, detectResult.imageHeight, mediaLayout)}
                >
                  <span className="absolute -top-5 left-0 rounded bg-black/80 px-1.5 py-0.5">
                    {box.className} {box.confidence.toFixed(2)}
                  </span>
                </div>
              ))}
              <svg
                className="pointer-events-none absolute inset-0 h-full w-full"
                viewBox={`0 0 ${geometryResult?.imageWidth ?? 1} ${geometryResult?.imageHeight ?? 1}`}
                preserveAspectRatio="none"
              >
                {geometryResult?.lines.slice(0, 30).map((line, index) => (
                  <line
                    key={`${line.x1}-${line.y1}-${index}`}
                    x1={line.x1}
                    y1={line.y1}
                    x2={line.x2}
                    y2={line.y2}
                    stroke="rgba(56, 189, 248, 0.82)"
                    strokeWidth="3"
                  />
                ))}
              </svg>
              </div>
          </div>
        ) : (
          <div className="grid h-full place-items-center bg-slate-950 text-center text-white">
            <div className="max-w-lg px-6">
              <h2 className="text-xl font-semibold">Street View Source</h2>
              <p className="mt-2 text-sm text-slate-300">
                Upload a stable street screenshot or video. YOLO detections and calibrated parking slots will render here.
              </p>
            </div>
          </div>
        )}

        <div className="absolute left-2 right-2 top-16 z-40 max-w-xl rounded-xl border border-white/15 bg-slate-950/80 p-3 text-xs text-white shadow-xl backdrop-blur sm:left-4 sm:right-auto md:left-40 md:top-4">
          <div className="mb-2 flex flex-wrap gap-2">
            {(['image', 'video', 'synthetic'] as MediaMode[]).map((mode) => (
              <button
                key={mode}
                type="button"
                className={clsx(
                  'rounded-lg border px-3 py-1.5 font-semibold capitalize transition-colors',
                  mediaMode === mode ? 'border-lime-300 bg-lime-400/20 text-lime-100' : 'border-white/20 bg-white/10 hover:bg-white/15',
                )}
                onClick={() => setMediaMode(mode)}
              >
                {mode}
              </button>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <input ref={imageInputRef} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void detectImageFile(file);
              e.currentTarget.value = '';
            }} />
            <input ref={videoInputRef} type="file" accept="video/*" className="hidden" onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) replaceMedia(file, 'video');
              e.currentTarget.value = '';
            }} />
            <input ref={calibrationInputRef} type="file" accept="application/json,.json" className="hidden" onChange={async (e) => {
              const file = e.target.files?.[0];
              if (file) setCalibration(JSON.parse(await file.text()) as StreetCalibration);
              e.currentTarget.value = '';
            }} />
            <button type="button" className="rounded-lg border border-white/20 bg-white/10 px-3 py-1.5 font-semibold hover:bg-white/15" onClick={() => imageInputRef.current?.click()}>
              Upload screenshot
            </button>
            <button type="button" className="rounded-lg border border-white/20 bg-white/10 px-3 py-1.5 font-semibold hover:bg-white/15" onClick={() => videoInputRef.current?.click()}>
              Upload video
            </button>
            <button type="button" className="rounded-lg border border-white/20 bg-white/10 px-3 py-1.5 font-semibold hover:bg-white/15" onClick={() => calibrationInputRef.current?.click()}>
              Load calibration
            </button>
            {mediaMode === 'video' && (
              <>
                <button type="button" className="rounded-lg border border-white/20 bg-white/10 px-3 py-1.5 font-semibold hover:bg-white/15" onClick={() => void detectVideoFrame()}>
                  Detect frame
                </button>
                <button
                  type="button"
                  className={clsx('rounded-lg border px-3 py-1.5 font-semibold', autoVideo ? 'border-lime-300 bg-lime-400/20 text-lime-100' : 'border-white/20 bg-white/10 hover:bg-white/15')}
                  onClick={() => setAutoVideo((on) => !on)}
                >
                  Auto video
                </button>
              </>
            )}
            <button type="button" className="rounded-lg border border-white/20 bg-white/10 px-3 py-1.5 font-semibold hover:bg-white/15 disabled:opacity-50" disabled={occupancy.length === 0} onClick={() => void syncOccupancy()}>
              Sync map pins
            </button>
            <button type="button" className="rounded-lg border border-white/20 bg-white/10 px-3 py-1.5 font-semibold hover:bg-white/15 disabled:opacity-50" disabled={!mediaUrl || mediaMode === 'synthetic'} onClick={() => void detectStreetGeometry()}>
              Detect geometry
            </button>
          </div>

          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-slate-300">
            <span>Status: {status}</span>
            <span>Detections: {detectResult?.boxes.length ?? 0}</span>
            <span>Map cars: {detectedSpots.length}</span>
            <span>Lines: {geometryResult?.lines.length ?? 0}</span>
            <span>Slots: {calibration?.parking_slots?.length ?? 0}</span>
            <span>Occupancy: {occupancy.filter((s) => s.status === 'occupied').length}/{occupancy.length}</span>
            <span>Make/model: {detectResult?.experimental?.makeModel?.stage ?? 'not run'}</span>
            {distances.slice(0, 3).map((distance) => (
              <span key={distance.id}>Gap: {distance.label}</span>
            ))}
          </div>
        </div>
      </section>

      <div
        className="grid h-3 cursor-row-resize place-items-center bg-slate-800 text-[10px] font-semibold uppercase tracking-wide text-slate-300"
        onPointerDown={startDrag}
        role="separator"
        aria-label="Resize street and map panes"
      >
        Drag
      </div>

      <section className="relative" style={{ height: `calc(${100 - topPercent}% - 0.75rem)` }}>
        <ParkingMap className="h-full" spotsOverride={detectedSpots} hideRecentlyOccupied={false} />
      </section>
    </div>
  );
}
