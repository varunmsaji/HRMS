import { ApiError } from "@/lib/api/errors";

/** Server codes for a self-service punch the web cannot satisfy: the web app has no camera and no
 * GPS, so a company that requires face verification or a location fix can only be punched from the
 * mobile app. `FACE_VERIFICATION_REQUIRED` is a 403 and `PUNCH_LOCATION_REQUIRED` a 422. */
const FACE_REQUIRED = "FACE_VERIFICATION_REQUIRED";
const LOCATION_REQUIRED = "PUNCH_LOCATION_REQUIRED";

/** Wording for those two refusals, or `null` for any other error. The server's own text for the
 * face case ("use the face punch flow") points at a flow that does not exist on the web. */
export function describeWebPunchRefusal(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null;
  const code = error.details[0]?.code ?? error.code;
  if (error.code === FACE_REQUIRED || code === FACE_REQUIRED) {
    return "Your company requires a face check to punch, and the web app cannot do one. Punch from the Krewoxa mobile app. If you cannot, ask HR to record the punch for you.";
  }
  if (error.code === LOCATION_REQUIRED || code === "LOCATION_REQUIRED") {
    return "Your company requires your location to punch, and the web app cannot send it. Punch from the Krewoxa mobile app. If you cannot, ask HR to record the punch for you.";
  }
  return null;
}
