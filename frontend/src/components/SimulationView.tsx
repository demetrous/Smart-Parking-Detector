import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import clsx from 'clsx';
import { useTheme } from './ThemeProvider';

type SimObject = {
  id: string;
  label: string;
  color: string;
  width: number | string;
  height: number | string;
  left: string;
  top: string;
};

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
};

function yoloOverlays(tick: number): SimObject[] {
  const cruise = 34 + Math.sin(tick * 0.018) * 18;
  const pedestrian = 18 + ((tick * 0.035) % 24);
  return [
    { id: 'car-cruise', label: 'car 0.93', color: 'border-cyan-300', width: 110, height: 54, left: `${cruise}%`, top: '53%' },
    { id: 'car-parked-white', label: 'car 0.97', color: 'border-emerald-300', width: 128, height: 58, left: '16%', top: '58%' },
    { id: 'car-parked-red', label: 'car 0.91', color: 'border-rose-300', width: 76, height: 46, left: '52%', top: '28%' },
    { id: 'person-crossing', label: 'person 0.86', color: 'border-amber-300', width: 38, height: 86, left: `${pedestrian}%`, top: '25%' },
  ];
}

function detectionOverlays(result: DetectResponse): SimObject[] {
  return result.boxes.map((box, index) => ({
    id: `yolo-${index}`,
    label: `${box.className} ${box.confidence.toFixed(2)}`,
    color: 'border-lime-300',
    width: `${((box.x2 - box.x1) / result.imageWidth) * 100}%`,
    height: `${((box.y2 - box.y1) / result.imageHeight) * 100}%`,
    left: `${(box.x1 / result.imageWidth) * 100}%`,
    top: `${(box.y1 / result.imageHeight) * 100}%`,
  }));
}

type AnimatedCar = {
  group: THREE.Group;
  wheels: THREE.Object3D[];
  speed: number;
  zMin: number;
  zMax: number;
};

type AnimatedPedestrian = {
  group: THREE.Group;
  leftLeg: THREE.Object3D;
  rightLeg: THREE.Object3D;
  baseX: number;
  baseZ: number;
  amplitude: number;
  phase: number;
};

function material(color: number, roughness = 0.55): THREE.MeshStandardMaterial {
  return new THREE.MeshStandardMaterial({ color, roughness, metalness: 0.08 });
}

function box(size: [number, number, number], color: number): THREE.Mesh {
  return new THREE.Mesh(new THREE.BoxGeometry(...size), material(color));
}

function createCar(color: number, parked = false): { group: THREE.Group; wheels: THREE.Object3D[] } {
  const group = new THREE.Group();
  const body = box([1.85, 0.48, 3.35], color);
  body.position.y = 0.48;
  const cabin = box([1.35, 0.52, 1.45], 0x1f2937);
  cabin.position.set(0, 0.92, -0.2);
  const windshield = box([1.18, 0.04, 0.52], 0x93c5fd);
  windshield.position.set(0, 1.2, 0.52);
  const rearWindow = box([1.08, 0.04, 0.44], 0x93c5fd);
  rearWindow.position.set(0, 1.2, -0.98);
  const hood = box([1.65, 0.08, 0.9], color);
  hood.position.set(0, 0.78, 1.18);
  group.add(body, cabin, windshield, rearWindow, hood);

  const wheelMat = material(0x0f172a);
  const hubMat = material(0xd1d5db);
  const wheels: THREE.Object3D[] = [];
  for (const x of [-1.02, 1.02]) {
    for (const z of [-1.15, 1.15]) {
      const wheel = new THREE.Mesh(new THREE.CylinderGeometry(0.27, 0.27, 0.22, 24), wheelMat);
      wheel.rotation.z = Math.PI / 2;
      wheel.position.set(x, 0.33, z);
      const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, 0.24, 16), hubMat);
      hub.rotation.z = Math.PI / 2;
      hub.position.copy(wheel.position);
      group.add(wheel, hub);
      wheels.push(wheel);
    }
  }

  const leftLight = box([0.42, 0.08, 0.05], parked ? 0xfbbf24 : 0xfef3c7);
  const rightLight = leftLight.clone();
  leftLight.position.set(-0.45, 0.56, 1.72);
  rightLight.position.set(0.45, 0.56, 1.72);
  group.add(leftLight, rightLight);
  return { group, wheels };
}

function createPedestrian(color: number): AnimatedPedestrian {
  const group = new THREE.Group();
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.16, 0.62, 6, 12), material(color));
  body.position.y = 0.86;
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.18, 18, 18), material(0xf2c7a5));
  head.position.y = 1.38;
  const leftLeg = box([0.08, 0.52, 0.08], 0x111827);
  const rightLeg = box([0.08, 0.52, 0.08], 0x111827);
  leftLeg.position.set(-0.08, 0.32, 0);
  rightLeg.position.set(0.08, 0.32, 0);
  group.add(body, head, leftLeg, rightLeg);
  return { group, leftLeg, rightLeg, baseX: 0, baseZ: 0, amplitude: 1, phase: 0 };
}

function createTree(x: number, z: number): THREE.Group {
  const group = new THREE.Group();
  const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.16, 1.4, 12), material(0x7c2d12));
  trunk.position.y = 0.7;
  const leaves = new THREE.Mesh(new THREE.SphereGeometry(0.72, 18, 18), material(0x15803d));
  leaves.position.y = 1.65;
  group.position.set(x, 0, z);
  group.add(trunk, leaves);
  return group;
}

function createBuilding(x: number, z: number, width: number, depth: number, height: number, color: number): THREE.Group {
  const group = new THREE.Group();
  const shell = box([width, height, depth], color);
  shell.position.y = height / 2;
  group.add(shell);
  const windowMat = material(0xcbd5e1);
  for (let y = 0.8; y < height - 0.3; y += 0.75) {
    for (let wx = -width / 2 + 0.45; wx < width / 2 - 0.2; wx += 0.8) {
      const win = new THREE.Mesh(new THREE.BoxGeometry(0.28, 0.22, 0.03), windowMat);
      win.position.set(wx, y, depth / 2 + 0.02);
      group.add(win);
    }
  }
  group.position.set(x, 0, z);
  return group;
}

function createRoadText(text: string): THREE.Mesh {
  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 128;
  const ctx = canvas.getContext('2d');
  if (ctx) {
    ctx.fillStyle = 'rgba(255,255,255,0)';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = 'rgba(255,255,255,0.75)';
    ctx.font = '700 72px Arial';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, canvas.width / 2, canvas.height / 2);
  }
  const texture = new THREE.CanvasTexture(canvas);
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(4.6, 1.1), new THREE.MeshBasicMaterial({ map: texture, transparent: true }));
  mesh.rotation.x = -Math.PI / 2;
  mesh.rotation.z = -Math.PI / 2;
  mesh.position.set(0.15, 0.09, 0.8);
  return mesh;
}

export default function SimulationView() {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const uploadInputRef = useRef<HTMLInputElement | null>(null);
  const tickRef = useRef(0);
  const { theme } = useTheme();
  const [overlayTick, setOverlayTick] = useState(0);
  const [yoloEnabled, setYoloEnabled] = useState(false);
  const [detectorStatus, setDetectorStatus] = useState<'scripted' | 'live' | 'offline'>('scripted');
  const [detectorResult, setDetectorResult] = useState<DetectResponse | null>(null);
  const [uploadPreviewUrl, setUploadPreviewUrl] = useState<string | null>(null);
  const [uploadResult, setUploadResult] = useState<DetectResponse | null>(null);
  const [uploadStatus, setUploadStatus] = useState<'idle' | 'detecting' | 'ready' | 'error'>('idle');
  const detectorUrl = ((import.meta.env.VITE_DETECTOR_URL as string | undefined) ?? 'http://127.0.0.1:8010').replace(/\/$/, '');
  const overlays = yoloEnabled && detectorStatus === 'live' && detectorResult
    ? detectionOverlays(detectorResult)
    : yoloOverlays(overlayTick);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(theme === 'dark' ? 0x0f172a : 0xdbe4f0);

    const camera = new THREE.PerspectiveCamera(55, mount.clientWidth / mount.clientHeight, 0.1, 100);
    camera.position.set(0.6, 5.7, 10.8);
    camera.lookAt(0, 0.4, -3.8);

    const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    mount.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    scene.add(new THREE.HemisphereLight(0xffffff, 0x64748b, 2.1));
    const sun = new THREE.DirectionalLight(0xffffff, 2);
    sun.position.set(-5, 10, 7);
    scene.add(sun);

    const asphalt = box([10, 0.12, 22], 0x334155);
    asphalt.position.z = -2;
    scene.add(asphalt);

    const westSidewalk = box([3.1, 0.14, 22], 0xcbd5e1);
    westSidewalk.position.set(-6.55, 0.05, -2);
    const eastSidewalk = box([3.1, 0.14, 22], 0xcbd5e1);
    eastSidewalk.position.set(6.55, 0.05, -2);
    scene.add(westSidewalk, eastSidewalk);

    const busLane = box([1.5, 0.03, 20], 0xb91c1c);
    busLane.position.set(3.85, 0.1, -2);
    scene.add(busLane);

    const curbMaterial = material(0xf8fafc);
    for (const x of [-5.05, 5.05]) {
      const curb = new THREE.Mesh(new THREE.BoxGeometry(0.18, 0.22, 22), curbMaterial);
      curb.position.set(x, 0.18, -2);
      scene.add(curb);
    }

    const stripeMaterial = new THREE.MeshStandardMaterial({ color: 0xffffff });
    for (const x of [-1.55, 1.25]) {
      for (let z = -11; z <= 8; z += 3.2) {
        const stripe = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.02, 1.65), stripeMaterial);
        stripe.position.set(x, 0.14, z);
        scene.add(stripe);
      }
    }
    for (let x = -4.2; x <= 4.2; x += 0.7) {
      const crosswalk = new THREE.Mesh(new THREE.BoxGeometry(0.38, 0.025, 2.25), stripeMaterial);
      crosswalk.position.set(x, 0.16, -7.8);
      scene.add(crosswalk);
    }
    const busOnly = createRoadText('1st Ave N');
    scene.add(busOnly);

    scene.add(
      createBuilding(-8.9, -7, 2.6, 3.1, 4.2, 0x64748b),
      createBuilding(-8.6, -1.5, 2.9, 2.8, 3.2, 0x94a3b8),
      createBuilding(-8.8, 5.2, 2.4, 3.2, 4.8, 0x475569),
      createBuilding(8.7, -6.2, 2.8, 3.5, 3.8, 0x64748b),
      createBuilding(8.6, 1.2, 2.4, 3.2, 4.6, 0x94a3b8),
    );

    for (const z of [-8, -4, 0, 4, 8]) {
      scene.add(createTree(-5.9, z), createTree(5.9, z - 1.2));
    }

    const animatedCars: AnimatedCar[] = [];
    const blueCar = createCar(0x38bdf8);
    blueCar.group.position.set(0.1, 0, 6.5);
    scene.add(blueCar.group);
    animatedCars.push({ group: blueCar.group, wheels: blueCar.wheels, speed: 0.08, zMin: -10, zMax: 8.5 });

    const grayCar = createCar(0x9ca3af);
    grayCar.group.position.set(2.35, 0, -4.5);
    scene.add(grayCar.group);
    animatedCars.push({ group: grayCar.group, wheels: grayCar.wheels, speed: 0.045, zMin: -10, zMax: 8.5 });

    const parkedWhite = createCar(0xf8fafc, true);
    parkedWhite.group.position.set(-3.85, 0, 3.6);
    parkedWhite.group.rotation.y = -0.12;
    scene.add(parkedWhite.group);

    const parkedRed = createCar(0xef4444, true);
    parkedRed.group.position.set(-3.7, 0, -4.4);
    parkedRed.group.rotation.y = -0.1;
    scene.add(parkedRed.group);

    const pedestrians: AnimatedPedestrian[] = [
      createPedestrian(0x7c3aed),
      createPedestrian(0x0f766e),
      createPedestrian(0xf59e0b),
    ];
    pedestrians[0].baseX = -6.25;
    pedestrians[0].baseZ = -2.5;
    pedestrians[0].amplitude = 2.6;
    pedestrians[0].phase = 0;
    pedestrians[1].baseX = 6.25;
    pedestrians[1].baseZ = -5.4;
    pedestrians[1].amplitude = 1.8;
    pedestrians[1].phase = 1.2;
    pedestrians[2].baseX = -1.5;
    pedestrians[2].baseZ = -7.8;
    pedestrians[2].amplitude = 3.5;
    pedestrians[2].phase = 2.1;
    for (const ped of pedestrians) scene.add(ped.group);

    let frameId = 0;
    const animate = () => {
      tickRef.current += 1;
      const t = tickRef.current;
      for (const car of animatedCars) {
        car.group.position.z -= car.speed;
        if (car.group.position.z < car.zMin) car.group.position.z = car.zMax;
        for (const wheel of car.wheels) wheel.rotation.x += car.speed * 2.4;
      }
      for (const ped of pedestrians) {
        const stride = Math.sin(t * 0.08 + ped.phase);
        ped.group.position.set(ped.baseX + stride * ped.amplitude, 0, ped.baseZ + Math.cos(t * 0.04 + ped.phase) * 0.45);
        ped.leftLeg.rotation.x = stride * 0.45;
        ped.rightLeg.rotation.x = -stride * 0.45;
      }
      if (t % 3 === 0) setOverlayTick(t);
      renderer.render(scene, camera);
      frameId = requestAnimationFrame(animate);
    };
    animate();

    const resize = () => {
      camera.aspect = mount.clientWidth / mount.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(mount.clientWidth, mount.clientHeight);
    };
    window.addEventListener('resize', resize);

    return () => {
      cancelAnimationFrame(frameId);
      window.removeEventListener('resize', resize);
      rendererRef.current = null;
      renderer.dispose();
      if (renderer.domElement.parentNode === mount) {
        mount.removeChild(renderer.domElement);
      }
    };
  }, [theme]);

  useEffect(() => {
    if (!yoloEnabled) {
      setDetectorStatus('scripted');
      setDetectorResult(null);
      return;
    }

    let stopped = false;
    let inFlight = false;
    let retryDelayMs = 1200;
    let timer: number | undefined;

    const captureBlob = (canvas: HTMLCanvasElement): Promise<Blob | null> =>
      new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.82));

    const sendFrame = async () => {
      const renderer = rendererRef.current;
      if (!renderer || stopped || inFlight) return;
      inFlight = true;
      try {
        const blob = await captureBlob(renderer.domElement);
        if (!blob || stopped) return;
        const response = await fetch(`${detectorUrl}/detect?conf=0.2`, {
          method: 'POST',
          headers: { 'Content-Type': 'image/jpeg' },
          body: blob,
        });
        if (!response.ok) throw new Error(`Detector returned ${response.status}`);
        const result = (await response.json()) as DetectResponse;
        if (!stopped) {
          setDetectorResult(result);
          setDetectorStatus('live');
        }
        retryDelayMs = 1200;
      } catch {
        if (!stopped) {
          setDetectorStatus('offline');
          setDetectorResult(null);
          retryDelayMs = Math.min(retryDelayMs * 2, 10000);
        }
      } finally {
        inFlight = false;
        if (!stopped) {
          timer = window.setTimeout(sendFrame, retryDelayMs);
        }
      }
    };

    void sendFrame();
    return () => {
      stopped = true;
      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
    };
  }, [detectorUrl, yoloEnabled]);

  useEffect(() => {
    return () => {
      if (uploadPreviewUrl) {
        URL.revokeObjectURL(uploadPreviewUrl);
      }
    };
  }, [uploadPreviewUrl]);

  const detectUploadedImage = async (file: File) => {
    if (uploadPreviewUrl) {
      URL.revokeObjectURL(uploadPreviewUrl);
    }
    setUploadPreviewUrl(URL.createObjectURL(file));
    setUploadResult(null);
    setUploadStatus('detecting');
    try {
      const response = await fetch(`${detectorUrl}/detect?conf=0.2&include_people=true`, {
        method: 'POST',
        headers: { 'Content-Type': file.type || 'application/octet-stream' },
        body: file,
      });
      if (!response.ok) throw new Error(`Detector returned ${response.status}`);
      setUploadResult((await response.json()) as DetectResponse);
      setUploadStatus('ready');
    } catch {
      setUploadStatus('error');
    }
  };

  return (
    <div className="relative h-dvh w-full overflow-hidden bg-slate-950">
      <div ref={mountRef} className="h-full w-full" />
      <div className="absolute left-4 top-4 max-w-sm rounded-xl border border-white/15 bg-slate-950/75 p-4 text-sm text-white shadow-xl backdrop-blur">
        <h2 className="mb-1 font-semibold">Synthetic Street Demo</h2>
        <p className="text-slate-300">
          Optional visual layer for demos: scripted car, parking, pedestrian crossing, and YOLO-style overlays.
        </p>
        <div className="mt-3 flex items-center gap-2">
          <button
            type="button"
            className={clsx(
              'rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors',
              yoloEnabled
                ? 'border-lime-300 bg-lime-400/20 text-lime-100'
                : 'border-white/20 bg-white/10 text-white hover:bg-white/15',
            )}
            onClick={() => setYoloEnabled((enabled) => !enabled)}
          >
            {yoloEnabled ? 'YOLO feed on' : 'Start YOLO feed'}
          </button>
          <span className="text-xs text-slate-300">
            {detectorStatus === 'live'
              ? `${detectorResult?.boxes.length ?? 0} real boxes`
              : detectorStatus === 'offline'
                ? 'detector offline'
                : 'scripted boxes'}
          </span>
        </div>
        <div className="mt-3 border-t border-white/10 pt-3">
          <input
            ref={uploadInputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void detectUploadedImage(file);
              event.currentTarget.value = '';
            }}
          />
          <button
            type="button"
            className="rounded-lg border border-white/20 bg-white/10 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-white/15"
            onClick={() => uploadInputRef.current?.click()}
          >
            Upload street screenshot
          </button>
          <span className="ml-2 text-xs text-slate-300">
            {uploadStatus === 'detecting'
              ? 'detecting...'
              : uploadStatus === 'ready'
                ? `${uploadResult?.boxes.length ?? 0} people/cars`
                : uploadStatus === 'error'
                  ? 'detector error'
                  : 'people + cars'}
          </span>
        </div>
      </div>
      {overlays.map((box) => (
        <div
          key={box.id}
          className={clsx('absolute rounded border-2 bg-black/10 text-xs font-semibold text-white shadow', box.color)}
          style={{
            width: box.width,
            height: box.height,
            left: box.left,
            top: box.top,
          }}
        >
          <span className="absolute -top-5 left-0 rounded bg-black/70 px-1.5 py-0.5">{box.label}</span>
        </div>
      ))}
      <div className="absolute bottom-4 right-4 rounded-xl border border-white/15 bg-slate-950/75 px-4 py-3 text-xs text-slate-200 backdrop-blur">
        Source of truth stays backend/WebSocket; this view is demo-only.
      </div>
      {uploadPreviewUrl && (
        <div className="absolute bottom-16 left-4 w-[min(36rem,calc(100vw-2rem))] rounded-xl border border-white/15 bg-slate-950/85 p-3 text-white shadow-2xl backdrop-blur">
          <div className="mb-2 flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold">Uploaded Street Screenshot</h3>
              <p className="text-xs text-slate-300">
                {uploadStatus === 'ready'
                  ? `YOLO found ${uploadResult?.boxes.length ?? 0} cars/people.`
                  : uploadStatus === 'detecting'
                    ? 'Sending image to YOLO...'
                    : uploadStatus === 'error'
                      ? 'Could not reach the detector service.'
                      : 'Ready for detection.'}
              </p>
            </div>
            <button
              type="button"
              className="rounded-lg border border-white/20 px-2 py-1 text-xs text-slate-200 hover:bg-white/10"
              onClick={() => {
                URL.revokeObjectURL(uploadPreviewUrl);
                setUploadPreviewUrl(null);
                setUploadResult(null);
                setUploadStatus('idle');
              }}
            >
              Close
            </button>
          </div>
          <div className="relative overflow-hidden rounded-lg border border-white/10">
            <img src={uploadPreviewUrl} alt="Uploaded street screenshot" className="block max-h-[45vh] w-full object-contain bg-black" />
            {uploadResult && detectionOverlays(uploadResult).map((box) => (
              <div
                key={box.id}
                className={clsx('absolute rounded border-2 bg-black/10 text-xs font-semibold text-white shadow', box.color)}
                style={{
                  width: box.width,
                  height: box.height,
                  left: box.left,
                  top: box.top,
                }}
              >
                <span className="absolute -top-5 left-0 rounded bg-black/80 px-1.5 py-0.5">{box.label}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
