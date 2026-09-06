import type {
  LeaveYearSetting,
  LeaveYearSettingUpsertPayload,
  LeaveYearType,
} from "@/lib/leave-year/types";

export interface LeaveYearFormValues {
  leaveYearType: LeaveYearType;
  startMonth: string;
  startDay: string;
}

export const EMPTY_LEAVE_YEAR_FORM_VALUES: LeaveYearFormValues = {
  leaveYearType: "CALENDAR",
  startMonth: "",
  startDay: "",
};

export interface LeaveYearFormErrors {
  startMonth?: string;
  startDay?: string;
}

export function validateLeaveYearForm(values: LeaveYearFormValues): LeaveYearFormErrors {
  const errors: LeaveYearFormErrors = {};
  if (values.leaveYearType === "CUSTOM") {
    if (!values.startMonth.trim()) errors.startMonth = "Required for a custom leave year.";
    if (!values.startDay.trim()) errors.startDay = "Required for a custom leave year.";
  }
  return errors;
}

export function leaveYearSettingToFormValues(setting: LeaveYearSetting): LeaveYearFormValues {
  return {
    leaveYearType: setting.leave_year_type,
    startMonth: setting.start_month === null ? "" : String(setting.start_month),
    startDay: setting.start_day === null ? "" : String(setting.start_day),
  };
}

export function buildLeaveYearSettingPayload(
  values: LeaveYearFormValues,
): LeaveYearSettingUpsertPayload {
  if (values.leaveYearType !== "CUSTOM") {
    return { leave_year_type: values.leaveYearType };
  }
  return {
    leave_year_type: values.leaveYearType,
    start_month: Number(values.startMonth),
    start_day: Number(values.startDay),
  };
}
