import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/attendance_repository.dart';
import '../domain/outside_shift_window.dart';
import '../domain/punch_location.dart';
import '../domain/face_liveness_capture.dart';
import '../state/punch_controller.dart';
import 'face_punch_card.dart';
import 'punch_location_flow.dart';

/// [PunchUi] backed by a widget's `BuildContext`: the dialogs, camera route and snackbars the
/// punch flows used to open inline.
class ContextPunchUi implements PunchUi {
  ContextPunchUi(this.context, this.ref, {this.onPunchedCallback, this.onFaceNotEnrolledCallback, this.snackBarClearance});

  final BuildContext context;
  final WidgetRef ref;
  final VoidCallback? onPunchedCallback;
  final VoidCallback? onFaceNotEnrolledCallback;

  /// Height of a bar pinned under the screen's body. When set, messages float above it instead of
  /// covering the punch buttons.
  final double Function()? snackBarClearance;

  @override
  bool get active => context.mounted;

  @override
  Future<PunchLocationPlan> planLocation() => planPunchLocation(context, ref);

  @override
  Future<PunchLocationPlan> captureLocation(GeofencePolicyMe policy) => captureForPolicy(context, ref, policy);

  @override
  Future<bool> showLocationProblem(LocationFailure failure, LocationCapture capture) => showLocationProblemDialog(context, failure, capture);

  @override
  Future<bool> showGeofenceRejected(String code, String message) => showGeofenceRejectedDialog(context, code, message);

  @override
  Future<void> showOutsideShiftWindow(OutsideShiftWindow window) => showOutsideShiftWindowDialog(context, window);

  @override
  Future<FaceCaptureOutcome> captureFace(FaceLivenessSession session) => ref.read(faceLivenessCaptureProvider)(context, session);

  @override
  void message(String text) {
    if (!context.mounted) return;
    final clearance = snackBarClearance?.call();
    ScaffoldMessenger.of(context).showSnackBar(clearance == null
        ? SnackBar(content: Text(text))
        : SnackBar(content: Text(text), behavior: SnackBarBehavior.floating, margin: EdgeInsets.fromLTRB(16, 0, 16, clearance + 8)));
  }

  @override
  void onPunched() => onPunchedCallback?.call();

  @override
  void onFaceNotEnrolled() => onFaceNotEnrolledCallback?.call();
}
