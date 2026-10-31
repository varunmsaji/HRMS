import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_client.dart';
import '../../../core/api/api_error.dart';
import '../data/attendance_repository.dart';
import '../data/location_provider.dart';
import '../domain/face_liveness_capture.dart';
import '../domain/outside_shift_window.dart';
import '../domain/punch_location.dart';
import '../presentation/punch_location_flow.dart';
import 'active_liveness_config.dart';

/// Where a face punch is in its flow (drives the face card's sentence and disables its buttons).
enum FacePhase { idle, locating, challenge, capturing, verifying }

@immutable
class PunchState {
  const PunchState({this.plainBusy = false, this.facePhase = FacePhase.idle, this.faceRequired = false});

  /// A plain punch is in flight (including its location step). Both plain buttons are disabled.
  final bool plainBusy;
  final FacePhase facePhase;

  /// The server says this employee must punch with their face (enrolled): the plain buttons are
  /// not offered at all. Learned from the face status or from a `FACE_VERIFICATION_REQUIRED` answer.
  final bool faceRequired;

  bool get faceBusy => facePhase != FacePhase.idle;

  PunchState copyWith({bool? plainBusy, FacePhase? facePhase, bool? faceRequired}) => PunchState(
        plainBusy: plainBusy ?? this.plainBusy,
        facePhase: facePhase ?? this.facePhase,
        faceRequired: faceRequired ?? this.faceRequired,
      );

  @override
  bool operator ==(Object other) => other is PunchState && other.plainBusy == plainBusy && other.facePhase == facePhase && other.faceRequired == faceRequired;

  @override
  int get hashCode => Object.hash(plainBusy, facePhase, faceRequired);
}

/// The parts of a punch that need a screen: dialogs, the camera route, snackbars. A screen passes
/// one in per call, so the controller holds no `BuildContext` and the same logic serves Attendance
/// and Home.
abstract class PunchUi {
  /// False once the screen that started the punch has gone (logout, session loss, navigation).
  bool get active;

  /// Plain punch: the employee's geofence policy and, when it asks, one fresh fix (`planPunchLocation`).
  Future<PunchLocationPlan> planLocation();

  /// Face punch: a fresh fix for an already-known [policy] (`captureForPolicy`).
  Future<PunchLocationPlan> captureLocation(GeofencePolicyMe policy);

  /// "Location needed" dialog; true = try again.
  Future<bool> showLocationProblem(LocationFailure failure, LocationCapture capture);

  /// "Punch not recorded" dialog; true = try again.
  Future<bool> showGeofenceRejected(String code, String message);

  /// "Too early to punch in" warning; nothing was recorded and there is nothing to retry.
  Future<void> showOutsideShiftWindow(OutsideShiftWindow window);

  /// Opens the camera for the server's challenge.
  Future<FaceCaptureOutcome> captureFace(FaceLivenessSession session);

  void message(String text);

  /// A punch was recorded: refresh what the screen shows.
  void onPunched();

  /// The server said there is no enrolled face: re-read the enrollment status.
  void onFaceNotEnrolled();
}

/// Owns the self-punch flows (plain and face) for the signed-in employee. This is the former
/// `AttendanceSelfScreen._punch/_punchOnce` and `FacePunchCard._punch`, moved unchanged in
/// behaviour (docs/design/employee-mobile/PUNCH_BEHAVIOUR.md), so Home and Attendance share one
/// in-flight guard and one idempotency record.
///
/// Auto-disposed: when the last screen using it goes (sign-out, session loss) the pending
/// idempotency keys go with it, exactly as they did with the old `State` fields, so one user's
/// unconfirmed punch can never be replayed for the next.
class PunchController extends StateNotifier<PunchState> {
  PunchController(this._ref) : super(const PunchState());

  final Ref _ref;

  /// Key of a plain punch whose outcome is unknown (no HTTP response). A retry of the *same*
  /// direction reuses it so a punch that did reach the server is not recorded twice.
  ({String direction, String key})? _plainPending;

  /// Same, for a face punch ([facePunchOutcomeUnknown]); the retry gets a new challenge and capture.
  ({String direction, String key})? _facePending;

  /// Updates state unless the controller has been disposed (the last screen using it is gone:
  /// sign-out, session loss). A request still in flight then completes without touching state.
  void _patch({bool? plainBusy, FacePhase? facePhase, bool? faceRequired}) {
    if (!mounted) return;
    final next = state.copyWith(plainBusy: plainBusy, facePhase: facePhase, faceRequired: faceRequired);
    if (next != state) state = next;
  }

  /// Reported by the face card once it knows the enrollment status.
  void setFaceRequired(bool required) => _patch(faceRequired: required);

  // ---------------------------------------------------------------------------------------
  // Plain punch
  // ---------------------------------------------------------------------------------------

  Future<void> punchPlain(String direction, PunchUi ui) async {
    if (state.plainBusy) return; // one attempt at a time, including the location capture
    _patch(plainBusy: true);
    try {
      var again = true;
      while (again && ui.active) {
        again = await _plainOnce(direction, ui);
      }
    } finally {
      _patch(plainBusy: false);
    }
  }

  /// One attempt. Returns true when the employee chose to try again after a location refusal.
  Future<bool> _plainOnce(String direction, PunchUi ui) async {
    // Only when the employee's policy asks for it, and only now, for this punch: one fresh
    // foreground fix. Nothing is collected in the background.
    final plan = await ui.planLocation();
    if (!plan.proceed || !ui.active) return false;

    final pending = _plainPending;
    final key = pending != null && pending.direction == direction ? pending.key : ApiClient.newIdempotencyKey();
    try {
      await _ref.read(attendanceRepositoryProvider).punchMe(
            direction: direction,
            idempotencyKey: key,
            location: plan.location,
            locationError: plan.locationError,
          );
      _plainPending = null;
      if (ui.active) ui.message(direction == 'IN' ? 'Punched in.' : 'Punched out.');
      if (ui.active) ui.onPunched();
      return false;
    } catch (error) {
      if (error is ApiError && error.code == 'FACE_VERIFICATION_REQUIRED') {
        _patch(faceRequired: true);
      }
      // No response: keep the key for a retry. Any real answer settles this attempt.
      _plainPending = error is ApiError && error.status == 0 ? (direction: direction, key: key) : null;
      if (error is ApiError && isGeofenceError(error) && ui.active) {
        // A refused location is a real answer: nothing was recorded, so retrying is safe.
        return ui.showGeofenceRejected(error.code, error.message);
      }
      final shiftWindow = OutsideShiftWindow.fromError(error);
      if (shiftWindow != null) {
        if (ui.active) await ui.showOutsideShiftWindow(shiftWindow);
        return false;
      }
      if (ui.active) ui.message(describeApiError(error));
      return false;
    }
  }

  // ---------------------------------------------------------------------------------------
  // Face punch
  // ---------------------------------------------------------------------------------------

  Future<void> punchFace(String direction, PunchUi ui) async {
    if (state.faceBusy) return; // one attempt at a time
    final repository = _ref.read(attendanceRepositoryProvider);
    _patch(facePhase: FacePhase.locating);
    List<List<int>>? frames;
    var retryAfter = false;
    try {
      // Location policy first (cheap): if a REQUIRED location cannot be had at all (services
      // off, permission refused) say so before the employee does the slow face capture.
      var policy = GeofencePolicyMe.disabled;
      try {
        policy = await repository.getMyGeofencePolicy();
      } catch (_) {
        // Offline / unknown: attempt the punch; the server enforces and will say if it needed one.
      }
      if (!policy.isDisabled) {
        final location = _ref.read(locationCaptureProvider);
        var blocked = await location.preflight();
        while (blocked != null && policy.isRequired) {
          if (!ui.active) return;
          final retry = await ui.showLocationProblem(blocked, location);
          if (!retry || !ui.active) return;
          blocked = await location.preflight();
        }
      }
      if (!ui.active) return;
      _patch(facePhase: FacePhase.challenge);
      final FaceLivenessSession session;
      try {
        session = await repository.startFaceLivenessSession(direction);
      } catch (error) {
        _say(ui, describeApiError(error));
        if (error is ApiError && error.code == 'FACE_NOT_ENROLLED') _notEnrolled(ui);
        return;
      }
      if (!ui.active) return;

      _patch(facePhase: FacePhase.capturing);
      final outcome = await ui.captureFace(session);
      switch (outcome) {
        case FaceCaptureFrames(frames: final captured, activeLivenessPassed: final live):
          frames = captured;
          // Defence in depth: when active liveness is required, frames that did not come out of
          // a completed challenge are never submitted, whatever produced them.
          if (_ref.read(activeLivenessConfigProvider).enabled && !live) {
            _say(ui, 'Face verification could not be completed. Please try again.');
            return;
          }
        case FaceCaptureCancelled():
          return;
        case FaceCapturePermissionDenied():
          _say(ui, 'Camera access is off. Allow camera access for this app in your phone settings, then try again.');
          return;
        case FaceCaptureExpired():
          _say(ui, 'That took too long. Please try again.');
          return;
        case FaceCaptureFailed(message: final message):
          _say(ui, message);
          return;
      }
      if (!ui.active) return;

      // The fix is taken now, right before submitting, so it is fresh when the server judges it
      // (the face capture above can take a while). Never reused from earlier.
      var plan = const PunchLocationPlan.skip();
      if (!policy.isDisabled) {
        _patch(facePhase: FacePhase.locating);
        plan = await ui.captureLocation(policy);
        if (!plan.proceed || !ui.active) return;
      }

      _patch(facePhase: FacePhase.verifying);
      final pending = _facePending;
      final key = pending != null && pending.direction == direction ? pending.key : ApiClient.newIdempotencyKey();
      try {
        final result = await repository.facePunchMe(
          direction: direction,
          livenessSessionId: session.sessionId,
          frames: frames,
          idempotencyKey: key,
          location: plan.location,
          locationError: plan.locationError,
        );
        _facePending = null;
        final label = result.direction == 'IN' ? 'Punched in' : 'Punched out';
        _say(ui, '$label · face verified (${(result.similarity * 100).round()}% match)');
        if (ui.active) ui.onPunched();
      } catch (error) {
        if (error is ApiError && isGeofenceError(error)) {
          // Refused on location: nothing was recorded. A retry needs a new face challenge, so
          // the whole punch starts again once this attempt has been cleaned up.
          _facePending = null;
          if (ui.active) retryAfter = await ui.showGeofenceRejected(error.code, error.message);
        } else if (OutsideShiftWindow.fromError(error) case final shiftWindow?) {
          // Refused as too early for the shift: nothing was recorded, and retrying cannot help.
          _facePending = null;
          if (ui.active) await ui.showOutsideShiftWindow(shiftWindow);
        } else {
          final unknown = facePunchOutcomeUnknown(error);
          // Unknown outcome: keep the key for the retry. Any real answer settles this attempt.
          _facePending = unknown ? (direction: direction, key: key) : null;
          _say(
            ui,
            unknown
                ? 'No response from the server — your punch may have been recorded. Trying again is safe: it will not be recorded twice.'
                : describeApiError(error),
          );
          if (error is ApiError && error.code == 'FACE_NOT_ENROLLED') _notEnrolled(ui);
        }
      }
    } finally {
      frames?.clear(); // drop the face images as soon as the attempt is over
      _patch(facePhase: FacePhase.idle);
    }
    if (retryAfter && ui.active) await punchFace(direction, ui);
  }

  void _say(PunchUi ui, String text) {
    if (ui.active) ui.message(text);
  }

  void _notEnrolled(PunchUi ui) {
    if (ui.active) ui.onFaceNotEnrolled();
  }
}

/// One controller per running app session of the screens that punch (Attendance, Home, the face card).
final punchControllerProvider = StateNotifierProvider.autoDispose<PunchController, PunchState>((ref) => PunchController(ref));
