import { describe, expect, it } from "vitest";

import {
  EMPTY_ATTENDANCE_POLICY_VERSION_FORM_VALUES,
  buildAttendancePolicyVersionPayload,
  mapAttendancePolicyVersionApiErrors,
  validateAttendancePolicyVersionForm,
} from "@/lib/attendance-policy/validate-attendance-policy";

const base = EMPTY_ATTENDANCE_POLICY_VERSION_FORM_VALUES;

describe("attendance policy geofence fields", () => {
  it("defaults to DISABLED so existing behaviour is unchanged", () => {
    expect(base.geofenceMode).toBe("DISABLED");
    const payload = buildAttendancePolicyVersionPayload(base);
    expect(payload.geofence_mode).toBe("DISABLED");
    expect(payload.geofence_max_accuracy_m).toBe(100);
    expect(payload.geofence_max_age_seconds).toBe(60);
  });

  it("sends the chosen mode and thresholds", () => {
    const payload = buildAttendancePolicyVersionPayload({
      ...base,
      geofenceMode: "REQUIRED",
      geofenceMaxAccuracyM: "40",
      geofenceMaxAgeSeconds: "20",
    });
    expect(payload).toMatchObject({
      geofence_mode: "REQUIRED",
      geofence_max_accuracy_m: 40,
      geofence_max_age_seconds: 20,
    });
  });

  it.each([
    ["4", "geofenceMaxAccuracyM"],
    ["501", "geofenceMaxAccuracyM"],
    ["", "geofenceMaxAccuracyM"],
    ["abc", "geofenceMaxAccuracyM"],
  ])("rejects accuracy %s", (value) => {
    const errors = validateAttendancePolicyVersionForm({ ...base, geofenceMaxAccuracyM: value });
    expect(errors.geofenceMaxAccuracyM).toMatch(/5-500/);
  });

  it.each(["4", "301", ""])("rejects max age %s", (value) => {
    const errors = validateAttendancePolicyVersionForm({ ...base, geofenceMaxAgeSeconds: value });
    expect(errors.geofenceMaxAgeSeconds).toMatch(/5-300/);
  });

  it("accepts the bounds", () => {
    const errors = validateAttendancePolicyVersionForm({
      ...base,
      geofenceMaxAccuracyM: "5",
      geofenceMaxAgeSeconds: "300",
    });
    expect(errors.geofenceMaxAccuracyM).toBeUndefined();
    expect(errors.geofenceMaxAgeSeconds).toBeUndefined();
  });

  it("maps server field errors back onto the form", () => {
    const errors = mapAttendancePolicyVersionApiErrors([
      { field: "geofence_max_accuracy_m", code: "X", message: "too low" },
    ] as never);
    expect(errors.geofenceMaxAccuracyM).toBe("too low");
  });
});

describe("attendance policy early punch-in allowance", () => {
  it("is blank (no limit) by default and sent as null", () => {
    expect(base.earlyInAllowanceMinutes).toBe("");
    expect(buildAttendancePolicyVersionPayload(base).early_in_allowance_minutes).toBeNull();
    expect(validateAttendancePolicyVersionForm(base).earlyInAllowanceMinutes).toBeUndefined();
  });

  it("sends the chosen number of minutes", () => {
    const payload = buildAttendancePolicyVersionPayload({ ...base, earlyInAllowanceMinutes: "60" });
    expect(payload.early_in_allowance_minutes).toBe(60);
  });

  it("accepts 0 and rejects a negative value", () => {
    expect(
      validateAttendancePolicyVersionForm({ ...base, earlyInAllowanceMinutes: "0" })
        .earlyInAllowanceMinutes,
    ).toBeUndefined();
    expect(
      validateAttendancePolicyVersionForm({ ...base, earlyInAllowanceMinutes: "-5" })
        .earlyInAllowanceMinutes,
    ).toBeTruthy();
  });

  it("maps a server field error onto the form", () => {
    expect(
      mapAttendancePolicyVersionApiErrors([
        { field: "early_in_allowance_minutes", code: "X", message: "Bad" },
      ]).earlyInAllowanceMinutes,
    ).toBe("Bad");
  });
});
