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
  // Many Android phones ignore the NV21 request and deliver the camera's native 3-plane YUV_420_888
  // frame instead. ML Kit reads NV21, so convert it rather than dropping every frame (which made
  // automatic capture silently never start).
  if (Platform.isAndroid && image.planes.length == 3) {
    final nv21 = yuv420ToNv21(
      width: image.width,
      height: image.height,
      yBytes: image.planes[0].bytes,
      yRowStride: image.planes[0].bytesPerRow,
      uBytes: image.planes[1].bytes,
      vBytes: image.planes[2].bytes,
      uvRowStride: image.planes[1].bytesPerRow,
      uvPixelStride: image.planes[1].bytesPerPixel ?? 1,
    );
    return InputImage.fromBytes(
      bytes: nv21,
      metadata: InputImageMetadata(
        size: Size(image.width.toDouble(), image.height.toDouble()),
        rotation: rotation,
        format: InputImageFormat.nv21,
        bytesPerRow: image.width,
      ),
    );
  }
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

/// Packs separate Y, U and V planes (any row/pixel stride) into one NV21 buffer: all Y bytes, then
/// interleaved V,U pairs at half resolution. Pure, so it is unit-tested without a camera.
Uint8List yuv420ToNv21({
  required int width,
  required int height,
  required Uint8List yBytes,
  required int yRowStride,
  required Uint8List uBytes,
  required Uint8List vBytes,
  required int uvRowStride,
  required int uvPixelStride,
}) {
  final out = Uint8List(width * height + 2 * ((width + 1) ~/ 2) * ((height + 1) ~/ 2));
  var o = 0;
  for (var row = 0; row < height; row++) {
    final start = row * yRowStride;
    out.setRange(o, o + width, yBytes, start);
    o += width;
  }
  for (var row = 0; row < (height + 1) ~/ 2; row++) {
    for (var col = 0; col < (width + 1) ~/ 2; col++) {
      final i = row * uvRowStride + col * uvPixelStride;
      out[o++] = vBytes[i];
      out[o++] = uBytes[i];
    }
  }
  return out;
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
