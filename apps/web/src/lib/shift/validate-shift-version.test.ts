import { describe, expect, it } from "vitest";

import type { ShiftVersion } from "@/lib/shift/types";
import {
  EMPTY_SHIFT_VERSION_FORM_VALUES,
  buildShiftVersionPatch,
  mapShiftVersionApiErrors,
  shiftVersionToFormValues,
  validateShiftVersionForm,
} from "@/lib/shift/validate-shift-version";

const baseVersion: ShiftVersion = {
  id: "version-1",
  company_id: "company-1",
  shift_id: "shift-1",
  status: "DRAFT",
  version: 1,
  effective_from: null,
  effective_to: null,
  shift_type: null,
  timezone: null,
  start_time: null,
  end_time: null,
  window_start: null,
  window_end: null,
  core_start: null,
  core_end: null,
  required_minutes: null,
  scheduled_minutes: null,
  min_scheduled_minutes: null,
  max_scheduled_minutes: null,
  is_night_shift: false,
  is_cross_midnight: false,
  is_ot_eligible: false,
  operates_on_holiday: false,
  operates_on_weekly_off: false,
  weekly_off_pattern_id: null,
  publish_reason: null,
  published_at: null,
  published_by: null,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
  breaks: [],
  duty_blocks: [],
};

describe("validateShiftVersionForm", () => {
  it("requires a shift type", () => {
    const errors = validateShiftVersionForm(EMPTY_SHIFT_VERSION_FORM_VALUES);
    expect(errors.shiftType).toBeDefined();
  });

  it("requires start/end time for FIXED", () => {
    const errors = validateShiftVersionForm({
      ...EMPTY_SHIFT_VERSION_FORM_VALUES,
      shiftType: "FIXED",
    });
    expect(errors.startTime).toBeDefined();
    expect(errors.endTime).toBeDefined();
  });

  it("rejects equal start/end time for FIXED", () => {
    const errors = validateShiftVersionForm({
      ...EMPTY_SHIFT_VERSION_FORM_VALUES,
      shiftType: "FIXED",
      startTime: "09:00",
      endTime: "09:00",
    });
    expect(errors.endTime).toMatch(/must differ/i);
  });

  it("accepts a valid FIXED shift including cross-midnight times", () => {
    const errors = validateShiftVersionForm({
      ...EMPTY_SHIFT_VERSION_FORM_VALUES,
      shiftType: "FIXED",
      startTime: "22:00",
      endTime: "06:00",
    });
    expect(errors).toEqual({});
  });

  it("requires window and required minutes for FLEXIBLE", () => {
    const errors = validateShiftVersionForm({
      ...EMPTY_SHIFT_VERSION_FORM_VALUES,
      shiftType: "FLEXIBLE",
    });
    expect(errors.windowStart).toBeDefined();
    expect(errors.windowEnd).toBeDefined();
    expect(errors.requiredMinutes).toBeDefined();
  });

  it("does not require core hours to nest inside the window", () => {
    const errors = validateShiftVersionForm({
      ...EMPTY_SHIFT_VERSION_FORM_VALUES,
      shiftType: "FLEXIBLE",
      windowStart: "07:00",
      windowEnd: "11:00",
      requiredMinutes: "480",
      coreStart: "10:00",
      coreEnd: "16:00",
    });
    expect(errors).toEqual({});
  });

  it("requires core start and end together", () => {
    const errors = validateShiftVersionForm({
      ...EMPTY_SHIFT_VERSION_FORM_VALUES,
      shiftType: "FLEXIBLE",
      windowStart: "07:00",
      windowEnd: "11:00",
      requiredMinutes: "480",
      coreStart: "10:00",
    });
    expect(errors.coreEnd).toBeDefined();
  });

  it("requires at least 2 duty blocks for SPLIT", () => {
    const errors = validateShiftVersionForm({
      ...EMPTY_SHIFT_VERSION_FORM_VALUES,
      shiftType: "SPLIT",
      dutyBlocks: [{ startTime: "09:00", endTime: "13:00" }],
    });
    expect(errors.dutyBlocks).toBeDefined();
  });

  it("accepts a valid SPLIT shift with 2 duty blocks", () => {
    const errors = validateShiftVersionForm({
      ...EMPTY_SHIFT_VERSION_FORM_VALUES,
      shiftType: "SPLIT",
      dutyBlocks: [
        { startTime: "09:00", endTime: "13:00" },
        { startTime: "17:00", endTime: "21:00" },
      ],
    });
    expect(errors.dutyBlocks).toBeUndefined();
  });

  it("validates break rows by kind", () => {
    const errors = validateShiftVersionForm({
      ...EMPTY_SHIFT_VERSION_FORM_VALUES,
      shiftType: "FIXED",
      startTime: "09:00",
      endTime: "18:00",
      breaks: [
        { name: "", breakKind: "FIXED_WINDOW", startTime: "", endTime: "", windowStart: "", windowEnd: "", minMinutes: "", maxMinutes: "", scheduledMinutes: "", isPaid: false, isMandatory: true, allowsSplit: false },
      ],
    });
    expect(errors.breakRows?.[0].name).toBeDefined();
    expect(errors.breakRows?.[0].startTime).toBeDefined();
    expect(errors.breakRows?.[0].endTime).toBeDefined();
  });
});

describe("shiftVersionToFormValues / buildShiftVersionPatch", () => {
  it("round-trips a FIXED version", () => {
    const version: ShiftVersion = {
      ...baseVersion,
      shift_type: "FIXED",
      effective_from: "2026-01-01",
      start_time: "09:00",
      end_time: "18:00",
    };
    const values = shiftVersionToFormValues(version);
    expect(values.shiftType).toBe("FIXED");
    expect(values.startTime).toBe("09:00");

    const patch = buildShiftVersionPatch(values, version);
    expect(patch).toMatchObject({
      shift_type: "FIXED",
      effective_from: "2026-01-01",
      start_time: "09:00",
      end_time: "18:00",
    });
  });

  it("omits FLEXIBLE-only fields when the type is FIXED", () => {
    const values = {
      ...EMPTY_SHIFT_VERSION_FORM_VALUES,
      shiftType: "FIXED" as const,
      startTime: "09:00",
      endTime: "18:00",
    };
    const patch = buildShiftVersionPatch(values, null);
    expect(patch.window_start).toBeUndefined();
    expect(patch.required_minutes).toBeUndefined();
  });

  it("includes breaks when the form holds rows", () => {
    const values = {
      ...EMPTY_SHIFT_VERSION_FORM_VALUES,
      shiftType: "FIXED" as const,
      startTime: "09:00",
      endTime: "18:00",
      breaks: [
        {
          name: "Lunch",
          breakKind: "FIXED_WINDOW" as const,
          startTime: "13:00",
          endTime: "14:00",
          windowStart: "",
          windowEnd: "",
          minMinutes: "",
          maxMinutes: "",
          scheduledMinutes: "",
          isPaid: false,
          isMandatory: true,
          allowsSplit: false,
        },
      ],
    };
    const patch = buildShiftVersionPatch(values, null);
    expect(patch.breaks).toEqual([
      {
        name: "Lunch",
        break_kind: "FIXED_WINDOW",
        is_paid: false,
        is_mandatory: true,
        allows_split: false,
        sort_order: 0,
        scheduled_minutes: null,
        start_time: "13:00",
        end_time: "14:00",
      },
    ]);
  });

  it("clears breaks by sending an empty array when the draft previously had some", () => {
    const version: ShiftVersion = {
      ...baseVersion,
      breaks: [
        {
          id: "break-1",
          shift_version_id: "version-1",
          name: "Lunch",
          break_kind: "FIXED_WINDOW",
          start_time: "13:00",
          end_time: "14:00",
          window_start: null,
          window_end: null,
          min_minutes: null,
          max_minutes: null,
          scheduled_minutes: null,
          is_paid: false,
          is_mandatory: true,
          allows_split: false,
          crosses_midnight: false,
          sort_order: 0,
        },
      ],
    };
    const values = shiftVersionToFormValues(version);
    values.breaks = [];
    const patch = buildShiftVersionPatch(values, version);
    expect(patch.breaks).toEqual([]);
  });
});

describe("mapShiftVersionApiErrors", () => {
  it("maps top-level fields", () => {
    const errors = mapShiftVersionApiErrors([
      { field: "end_time", code: "INVALID_SHIFT_VERSION_TIME_RANGE", message: "bad range" },
    ]);
    expect(errors.endTime).toBe("bad range");
  });

  it("maps compound breaks.N.field paths onto breakRows", () => {
    const errors = mapShiftVersionApiErrors([
      { field: "breaks.1.end_time", code: "INVALID_SHIFT_BREAK", message: "bad break" },
    ]);
    expect(errors.breakRows?.[1]?.endTime).toBe("bad break");
  });

  it("falls back to a general breaks message without an index", () => {
    const errors = mapShiftVersionApiErrors([
      { field: "breaks", code: "INVALID_SHIFT_BREAK_OVERLAP", message: "overlap" },
    ]);
    expect(errors.breaks).toBe("overlap");
  });

  it("maps duty_blocks errors", () => {
    const errors = mapShiftVersionApiErrors([
      {
        field: "duty_blocks",
        code: "INVALID_SHIFT_VERSION_DUTY_BLOCK_COUNT",
        message: "need 2 blocks",
      },
    ]);
    expect(errors.dutyBlocks).toBe("need 2 blocks");
  });
});
