import { describe, expect, it } from "vitest";

import {
  formatMetres,
  isUsableGeofence,
  mapLink,
  outcomeLabel,
  type GeofenceWorkplace,
} from "@/lib/geofence/types";

const base: GeofenceWorkplace = {
  branch_id: "b",
  name: "HQ",
  code: null,
  is_active: true,
  latitude: 9.9312,
  longitude: 76.2673,
  radius_m: 100,
  configured: true,
  assigned_employee_count: 3,
  authorized_employee_count: 0,
};

describe("geofence helpers", () => {
  it("a geofence is usable only when active and configured", () => {
    expect(isUsableGeofence(base)).toBe(true);
    expect(isUsableGeofence({ ...base, is_active: false })).toBe(false);
    expect(isUsableGeofence({ ...base, configured: false })).toBe(false);
  });

  it("labels known outcomes in plain language and falls back to the code", () => {
    expect(outcomeLabel("OUTSIDE_GEOFENCE")).toBe("Outside the workplace");
    expect(outcomeLabel("SOMETHING_NEW")).toBe("SOMETHING_NEW");
  });

  it("formats metres defensively", () => {
    expect(formatMetres("12.34")).toBe("12 m");
    expect(formatMetres(null)).toBe("—");
    expect(formatMetres("abc")).toBe("—");
  });

  it("links to an external map without bundling a provider", () => {
    expect(mapLink(9.9312, 76.2673)).toContain("openstreetmap.org");
    expect(mapLink(9.9312, 76.2673)).toContain("mlat=9.9312");
  });
});
