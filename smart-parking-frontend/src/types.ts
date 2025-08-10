export type SpotStatus = 'available' | 'soon' | 'occupied';

export interface Spot {
  id: string;
  lat: number;
  lng: number;
  status: SpotStatus;
  confidence: number;
  updatedAt: string; // ISO string
  cameraId?: string | null;
}

export interface SpotUpdateEvent {
  type: 'spot.update';
  payload: Spot;
}


