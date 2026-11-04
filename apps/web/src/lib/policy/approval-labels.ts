/** Who approves, in words. Shared by overtime and regularization policies. */
export const APPROVAL_CHAIN_LABELS: Record<string, string> = {
  AUTO: "Approved automatically",
  MANAGER: "Manager approves",
  MANAGER_THEN_HR: "Manager approves, then HR",
  HR: "HR approves",
};
