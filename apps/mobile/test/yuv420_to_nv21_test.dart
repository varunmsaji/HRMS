import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:hrms_mobile/features/attendance/presentation/camera_input_image.dart';

void main() {
  test('packs Y, then interleaved V,U, honouring row and pixel strides', () {
    // 4x2 image. Y rows are padded to a stride of 6; U/V use pixel stride 2 and a row stride of 4.
    final y = Uint8List.fromList([1, 2, 3, 4, 99, 99, 5, 6, 7, 8, 99, 99]);
    final u = Uint8List.fromList([10, 0, 11, 0]);
    final v = Uint8List.fromList([20, 0, 21, 0]);
    final out = yuv420ToNv21(width: 4, height: 2, yBytes: y, yRowStride: 6, uBytes: u, vBytes: v, uvRowStride: 4, uvPixelStride: 2);
    expect(out, [1, 2, 3, 4, 5, 6, 7, 8, 20, 10, 21, 11]);
  });

  test('odd sizes round the chroma plane up', () {
    final out = yuv420ToNv21(
      width: 3,
      height: 3,
      yBytes: Uint8List.fromList(List.generate(9, (i) => i)),
      yRowStride: 3,
      uBytes: Uint8List.fromList([50, 51, 52, 53]),
      vBytes: Uint8List.fromList([60, 61, 62, 63]),
      uvRowStride: 2,
      uvPixelStride: 1,
    );
    expect(out.length, 9 + 2 * 2 * 2);
    expect(out.sublist(9), [60, 50, 61, 51, 62, 52, 63, 53]);
  });
}
