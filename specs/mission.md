# Mission

ParkingSpotter tells a driver, live on a map, which parking spots are free,
taken, or about to open up. A camera watches a street or lot, a detector turns
frames into per-slot occupancy, and every open browser sees changes within a
second or two.

## Who it is for

- **Drivers** circling the block: they want the nearest green pin, and the
  yellow "soon" pin when nothing is green.
- **The operator** (today: Dmitrii): sets up a camera, draws slots, calibrates
  the scene, and keeps the system running.

## What makes it different

The yellow **"soon"** state: a spot is flagged before it frees up, from two
signals that feed the same pin.

1. Dwell-time prediction from each spot's parking history.
2. Motion detection: ByteTrack sees a parked car start pulling out.

## Where it stands (October 2026)

A hardened, pilot-ready codebase that has **never been validated against a
real camera**. The April 2026 work (P0–P3) is complete. The July 2026 readiness
push (R0–R3) is all open.

## What matters now

Contact with reality beats new surfaces. When choosing between adding a feature
and making an existing path measurable, choose measurable. The first honest
accuracy number (labeled footage → `detector/benchmark.py`) is the milestone
that unlocks everything after it.

## Principles

- **Benchmarks or it didn't happen.** Model, framework or transport changes
  cite `detector/benchmark.py` results on this repo's own labeled footage.
- **Privacy by design.** The system stores spot status only, never video frames
  or licence plates.
- **Secure by default.** Every write endpoint ships with auth and size limits.
- **Small, verifiable steps.** Each roadmap phase is one focused branch with its
  own spec, tests, and a passing verification gate.

## Non-goals (for now)

- Multi-lot product, operator dashboard, PWA, observability stack (R3, deferred
  until pilot metrics exist).
- VLMs in the per-frame loop.
- New features in the demo views (`HybridStreetMapView.tsx`,
  `SimulationView.tsx`) before the pilot produces accuracy metrics.
