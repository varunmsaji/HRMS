import type { OnboardingMessageStatus } from "@/lib/onboarding/types";

/** Inserts `{{key}}` at the caret (or over the selection) and returns the new text + caret. */
export function insertPlaceholder(
  value: string,
  selectionStart: number,
  selectionEnd: number,
  key: string,
): { value: string; caret: number } {
  const token = `{{${key}}}`;
  const start = Math.max(0, Math.min(selectionStart, value.length));
  const end = Math.max(start, Math.min(selectionEnd, value.length));
  return { value: value.slice(0, start) + token + value.slice(end), caret: start + token.length };
}

export interface MessageStatusInfo {
  label: string;
  description: string;
  tone: "neutral" | "warning" | "success" | "danger";
  /** A new invitation (new link; revokes the previous one) is the only remedy. */
  needsResend: boolean;
}

/** Wording is deliberate: "Accepted by mail provider" is NOT "delivered" - no delivery or bounce
 * events are processed, so inbox delivery is never claimed. */
export function describeMessageStatus(status: OnboardingMessageStatus): MessageStatusInfo {
  switch (status) {
    case "QUEUED":
      return { label: "Queued", description: "Waiting to be handed to the mail provider.", tone: "neutral", needsResend: false };
    case "SENDING":
      return { label: "Sending", description: "Being handed to the mail provider now.", tone: "neutral", needsResend: false };
    case "RETRYING":
      return { label: "Retrying", description: "A delivery attempt failed; it is being retried automatically with the same link.", tone: "warning", needsResend: false };
    case "PROVIDER_ACCEPTED":
      return { label: "Accepted by mail provider", description: "The provider accepted the message. This does not confirm it reached the inbox.", tone: "success", needsResend: false };
    case "FAILED":
      return { label: "Failed", description: "The message could not be delivered. The link in it cannot be re-sent; send a new invitation.", tone: "danger", needsResend: true };
    case "NOT_QUEUED":
      return { label: "Not queued", description: "The email was not queued. The link was created but nothing was sent; send a new invitation.", tone: "danger", needsResend: true };
    default:
      return { label: "Unknown", description: "Delivery status is unavailable.", tone: "neutral", needsResend: false };
  }
}
