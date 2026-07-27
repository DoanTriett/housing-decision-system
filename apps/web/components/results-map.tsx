"use client";

import { useEffect, useMemo } from "react";
import {
  CircleMarker,
  MapContainer,
  Marker,
  Popup,
  TileLayer,
  useMap,
} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

import type { RankedListingDetail } from "@/lib/types";

type ResultsMapProps = {
  anchorAddress?: string | null;
  anchorLat?: number | null;
  anchorLon?: number | null;
  listings: RankedListingDetail[];
};

const RANK_COLORS: Record<number, string> = {
  1: "#0f5444",
  2: "#1d6b9a",
  3: "#b45309",
};

function FitBounds({
  points,
}: {
  points: Array<[number, number]>;
}) {
  const map = useMap();
  useEffect(() => {
    if (points.length === 0) return;
    if (points.length === 1) {
      map.setView(points[0], 14);
      return;
    }
    map.fitBounds(L.latLngBounds(points.map(([lat, lon]) => [lat, lon])), {
      padding: [40, 40],
    });
  }, [map, points]);
  return null;
}

function rankIcon(rank: number) {
  const color = RANK_COLORS[rank] ?? "#475569";
  return L.divIcon({
    className: "",
    html: `<div style="
      width:28px;height:28px;border-radius:9999px;
      background:${color};color:#fff;font:700 12px/28px system-ui,sans-serif;
      text-align:center;border:2px solid #fff;
      box-shadow:0 1px 4px rgba(0,0,0,.35);
    ">${rank}</div>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
    popupAnchor: [0, -14],
  });
}

export function ResultsMap({
  anchorAddress,
  anchorLat,
  anchorLon,
  listings,
}: ResultsMapProps) {
  const pins = useMemo(
    () =>
      listings.filter(
        (item): item is RankedListingDetail & { lat: number; lon: number } =>
          typeof item.lat === "number" && typeof item.lon === "number"
      ),
    [listings]
  );

  const hasAnchor =
    typeof anchorLat === "number" && typeof anchorLon === "number";

  const center: [number, number] = hasAnchor
    ? [anchorLat, anchorLon]
    : pins[0]
      ? [pins[0].lat, pins[0].lon]
      : [30.2672, -97.7431]; // Austin fallback

  const boundsPoints: Array<[number, number]> = [
    ...(hasAnchor ? ([[anchorLat, anchorLon]] as Array<[number, number]>) : []),
    ...pins.map((p) => [p.lat, p.lon] as [number, number]),
  ];

  if (!hasAnchor && pins.length === 0) {
    return (
      <div className="flex h-[360px] items-center justify-center rounded-xl border border-dashed border-border bg-card/60 text-sm text-muted-foreground">
        Map coordinates unavailable for this result.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-border shadow-sm">
      <MapContainer
        center={center}
        zoom={13}
        scrollWheelZoom={false}
        className="h-[360px] w-full z-0"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds points={boundsPoints} />
        {hasAnchor ? (
          <CircleMarker
            center={[anchorLat, anchorLon]}
            radius={10}
            pathOptions={{
              color: "#7f1d1d",
              fillColor: "#dc2626",
              fillOpacity: 0.9,
              weight: 2,
            }}
          >
            <Popup>
              <div className="text-sm">
                <p className="font-semibold">Anchor</p>
                <p>{anchorAddress ?? "Commute origin"}</p>
              </div>
            </Popup>
          </CircleMarker>
        ) : null}
        {pins.map((listing) => (
          <Marker
            key={listing.listing_id}
            position={[listing.lat, listing.lon]}
            icon={rankIcon(listing.rank)}
          >
            <Popup>
              <div className="space-y-1 text-sm">
                <p className="font-semibold">
                  #{listing.rank}{" "}
                  {listing.title ?? listing.listing_id.slice(0, 8)}
                </p>
                {listing.price_monthly != null ? (
                  <p>${Math.round(listing.price_monthly).toLocaleString()}/mo</p>
                ) : null}
                {listing.walk_minutes != null ? (
                  <p>{listing.walk_minutes} min walk</p>
                ) : null}
              </div>
            </Popup>
          </Marker>
        ))}
      </MapContainer>
    </div>
  );
}
