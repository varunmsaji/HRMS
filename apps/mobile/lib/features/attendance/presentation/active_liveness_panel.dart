import 'package:flutter/material.dart';

import '../domain/active_liveness.dart';

/// Employee-facing wording. Never exposes thresholds, landmarks or scores.
String livenessMessage(LivenessState state, LivenessHint hint, {LivenessChallenge? challenge, bool exhausted = false}) {
  if (exhausted && (state == LivenessState.challengeTimeout || state == LivenessState.challengeFailed)) {
    return 'Liveness verification could not be completed. Please try again later.';
  }
  switch (state) {
    case LivenessState.noFaceDetected:
      return 'Position your face inside the camera frame.';
    case LivenessState.multipleFacesDetected:
      return 'Only one person should be visible.';
    case LivenessState.challengeTimeout:
    case LivenessState.challengeFailed:
      return "We couldn't verify the movement. Please try again.";
    case LivenessState.cameraError:
      return 'Camera could not be started. Please try again.';
    case LivenessState.challengeActive:
      return challenge?.instruction ?? 'Follow the instruction on screen';
    case LivenessState.challengeCompleted:
    case LivenessState.nextChallenge:
      return 'Good. One more step.';
    case LivenessState.livenessPassed:
    case LivenessState.faceVerification:
      return 'Thanks. Hold still for a moment…';
    case LivenessState.submittingAttendance:
    case LivenessState.success:
    case LivenessState.cancelled:
    case LivenessState.idle:
    case LivenessState.initializingCamera:
    case LivenessState.waitingForFace:
      return switch (hint) {
        LivenessHint.moveCloser => 'Move a little closer.',
        LivenessHint.moveBack => 'Move a little further away.',
        LivenessHint.lookForward => 'Look straight at the camera.',
        _ => 'Look at the camera and hold still.',
      };
  }
}

IconData _iconFor(LivenessChallenge? c) => switch (c) {
      LivenessChallenge.blinkTwice => Icons.visibility,
      LivenessChallenge.turnLeft => Icons.arrow_back,
      LivenessChallenge.turnRight => Icons.arrow_forward,
      null => Icons.face,
    };

/// What the employee is asked to do, how far along they are, and what to do when it fails.
/// Pure presentation: state comes in, taps go out; it owns no timers and no engine.
class ActiveLivenessPanel extends StatelessWidget {
  const ActiveLivenessPanel({
    super.key,
    required this.state,
    required this.hint,
    required this.challenge,
    required this.challengeIndex,
    required this.challengeCount,
    required this.attemptsExhausted,
    required this.onRetry,
    required this.onClose,
  });

  final LivenessState state;
  final LivenessHint hint;
  final LivenessChallenge? challenge;
  final int challengeIndex;
  final int challengeCount;
  final bool attemptsExhausted;
  final VoidCallback onRetry;
  final VoidCallback onClose;

  bool get _failed =>
      state == LivenessState.challengeTimeout || state == LivenessState.challengeFailed || state == LivenessState.cameraError;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final text = Theme.of(context).textTheme;
    final message = livenessMessage(state, hint, challenge: challenge, exhausted: attemptsExhausted);
    final active = state == LivenessState.challengeActive;
    final showProgress = challengeCount > 0 && !_failed;
    final completed = switch (state) {
      LivenessState.challengeCompleted || LivenessState.nextChallenge => challengeIndex + 1,
      LivenessState.livenessPassed || LivenessState.faceVerification => challengeCount,
      _ => challengeIndex,
    };

    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 8, 20, 8),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Semantics(
          liveRegion: true,
          child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
            if (active) ...[Icon(_iconFor(challenge), color: scheme.primary), const SizedBox(width: 8)],
            Flexible(
              child: Text(
                message,
                textAlign: TextAlign.center,
                style: (active ? text.titleLarge : text.titleMedium)?.copyWith(color: _failed ? scheme.error : null),
              ),
            ),
          ]),
        ),
        if (showProgress) ...[
          const SizedBox(height: 10),
          Semantics(
            label: 'Step ${(completed + (active ? 1 : 0)).clamp(1, challengeCount)} of $challengeCount',
            excludeSemantics: true,
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              for (var i = 0; i < challengeCount; i++)
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 4),
                  child: Icon(i < completed ? Icons.check_circle : Icons.circle_outlined, size: 18, color: scheme.primary),
                ),
            ]),
          ),
          const SizedBox(height: 4),
          Text(
            'Step ${(completed + (active ? 1 : 0)).clamp(1, challengeCount)} of $challengeCount',
            style: text.bodySmall?.copyWith(color: scheme.onSurfaceVariant),
          ),
        ],
        if (_failed) ...[
          const SizedBox(height: 12),
          if (attemptsExhausted)
            FilledButton(onPressed: onClose, child: const Text('Close'))
          else
            Wrap(spacing: 12, runSpacing: 8, alignment: WrapAlignment.center, children: [
              FilledButton(onPressed: onRetry, child: const Text('Try again')),
              OutlinedButton(onPressed: onClose, child: const Text('Cancel')),
            ]),
        ],
      ]),
    );
  }
}
