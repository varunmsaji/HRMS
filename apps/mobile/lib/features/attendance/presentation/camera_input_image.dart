import 'dart:io';

import 'package:camera/camera.dart';
import 'package:flutter/services.dart';
import 'package:google_mlkit_face_detection/google_mlkit_face_detection.dart';

const _orientations = {
  DeviceOrientation.portraitUp: 0,
  DeviceOrientation.landscapeLeft: 90,
  DeviceOrientation.portraitDown: 180,
  DeviceOrientation.landscapeRight: 270,
};

/// Camera frame -> ML Kit input (the plugin's documented conversion: NV21 on Android,
/// BGRA8888 on iOS, single plane, rotation from sensor + device orientation). Null when the
/// frame cannot be converted; the caller just skips it.
InputImage? cameraFrameToInputImage(CameraImage image, CameraDescription camera, CameraController controller) {
  final sensorOrientation = camera.sensorOrientation;
  InputImageRotation? rotation;
  if (Platform.isIOS) {
    rotation = InputImageRotationValue.fromRawValue(sensorOrientation);
  } else {
    var compensation = _orientations[controller.value.deviceOrientation];
    if (compensation == null) return null;
    compensation = camera.lensDirection == CameraLensDirection.front
        ? (sensorOrientation + compensation) % 360
        : (sensorOrientation - compensation + 360) % 360;
    rotation = InputImageRotationValue.fromRawValue(compensation);
  }
  if (rotation == null) return null;
  final format = InputImageFormatValue.fromRawValue(image.format.raw);
  if (format == null ||
      (Platform.isAndroid && format != InputImageFormat.nv21) ||
      (Platform.isIOS && format != InputImageFormat.bgra8888) ||
      image.planes.length != 1) {
    return null;
  }
  final plane = image.planes.first;
  return InputImage.fromBytes(
    bytes: plane.bytes,
    metadata: InputImageMetadata(
      size: Size(image.width.toDouble(), image.height.toDouble()),
      rotation: rotation,
      format: format,
      bytesPerRow: plane.bytesPerRow,
    ),
  );
}

/// The frame's width as ML Kit sees it once rotated upright (face boxes are in that space).
double uprightWidth(InputImage input) {
  final metadata = input.metadata!;
  final quarterTurn = metadata.rotation == InputImageRotation.rotation90deg || metadata.rotation == InputImageRotation.rotation270deg;
  return quarterTurn ? metadata.size.height : metadata.size.width;
}

/// Reads a captured photo and deletes the camera's temporary file straight away, so no face
/// image is left on the device.
Future<Uint8List> readAndDeleteCapture(XFile file) async {
  try {
    return await file.readAsBytes();
  } finally {
    try {
      await File(file.path).delete();
    } catch (_) {
      // Already gone, or the platform keeps it elsewhere; nothing else to do.
    }
  }
}
